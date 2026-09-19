const { app, BrowserWindow, ipcMain, dialog, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn } = require('child_process');
const { writeMainLog, isPathAllowed, registerSafeStorageHandlers, registerFileIpcHandlers } = require('./shared/electron-common');

// ============================================================
//  灵枢 Electron 壳 — 对应 Qt 项目 packaging/Launcher.cs
// ============================================================

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
const backendPort = process.env.LINGSHU_BACKEND_PORT || '8787';
const backendHost = process.env.LINGSHU_BACKEND_HOST || '127.0.0.1';
const localBackendBaseUrl = (process.env.LINGSHU_LOCAL_BASE_URL || `http://${backendHost}:${backendPort}`).replace(/\/+$/, '');
const localHealthUrl = `${localBackendBaseUrl}/api/health`;
const cloudHealthUrl = process.env.LINGSHU_CLOUD_HEALTH_URL || 'https://www.ling-shu.top/api/health';
let mainWindow = null;
let splashWindow = null;
let backendProcess = null;
let lastSplashStage = { stage: '正在启动灵枢', detail: '启动本地工作台服务' };

if (process.env.LINGSHU_PORTABLE_DATA_DIR) {
  try {
    fs.mkdirSync(process.env.LINGSHU_PORTABLE_DATA_DIR, { recursive: true });
    app.setPath('userData', process.env.LINGSHU_PORTABLE_DATA_DIR);
  } catch (_err) {
    // Fall back to Electron's default userData path if the portable directory is unavailable.
  }
}

process.on('uncaughtException', (err) => {
  writeMainLog('ERROR', 'uncaughtException', err && err.stack ? err.stack : String(err));
});

process.on('unhandledRejection', (err) => {
  writeMainLog('ERROR', 'unhandledRejection', err && err.stack ? err.stack : String(err));
});

function splashImagePath() {
  const candidates = [
    path.join(process.resourcesPath, 'branding', 'startup.png'),
    path.join(__dirname, '..', 'branding', 'startup.png'),
    path.join(__dirname, 'assets', 'splash.png'),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

function createSplashWindow() {
  if (splashWindow && !splashWindow.isDestroyed()) return;
  splashWindow = new BrowserWindow({
    width: 640,
    height: 400,
    resizable: false,
    maximizable: false,
    minimizable: false,
    frame: false,
    center: true,
    show: false,
    backgroundColor: '#0b1220',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });

  splashWindow.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.show();
  });
  splashWindow.webContents.once('did-finish-load', () => {
    setSplashStage(lastSplashStage.stage, lastSplashStage.detail);
  });
  splashWindow.on('closed', () => {
    splashWindow = null;
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'), {
    query: { image: splashImagePath() },
  }).catch((err) => writeMainLog('ERROR', 'splash load failed', String(err)));
}

function setSplashStage(stage, detail) {
  lastSplashStage = { stage, detail };
  writeMainLog('INFO', 'splash stage', `${stage} | ${detail}`);
  if (!splashWindow || splashWindow.isDestroyed()) return;
  const payload = JSON.stringify({ stage, detail });
  splashWindow.webContents.executeJavaScript(
    `window.setSplashStage && window.setSplashStage(${payload})`,
  ).catch((err) => writeMainLog('ERROR', 'splash stage update failed', String(err)));
}

function closeSplashWindow() {
  if (!splashWindow || splashWindow.isDestroyed()) return;
  splashWindow.close();
  splashWindow = null;
}

function createWindow() {
  writeMainLog('INFO', 'createWindow', `isDev=${isDev} dirname=${__dirname}`);
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    title: '灵枢',
    icon: path.join(__dirname, '..', 'packaging', 'app_icon.ico'),
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
    frame: true,
    backgroundColor: '#f5f7fa',
    show: false,
  });
  mainWindow.setMenuBarVisibility(false);

  // 加载 Vue SPA
  if (isDev) {
    mainWindow.loadURL('http://127.0.0.1:5175');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    // Production: dist files are bundled inside app.asar at dist/
    const indexPath = path.join(__dirname, 'dist', 'index.html');
    writeMainLog('INFO', 'loadFile', indexPath);
    mainWindow.loadFile(indexPath);
  }

  mainWindow.webContents.on('did-fail-load', (_event, code, description, validatedUrl) => {
    writeMainLog('ERROR', 'renderer did-fail-load', `${code} ${description} ${validatedUrl}`);
  });

  mainWindow.webContents.on('before-input-event', (event, input) => {
    const key = String(input.key || '').toLowerCase();
    if ((input.control || input.meta) && !input.alt && key === 'f') {
      event.preventDefault();
      mainWindow.webContents.stopFindInPage('clearSelection');
      mainWindow.webContents.send('app:open-search');
    }
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    closeSplashWindow();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ============================================================
//  Python 后端进程管理
// ============================================================

const https = require('https');

function requestBackendHealth(healthUrl = localHealthUrl, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const client = healthUrl.startsWith('https:') ? https : http;
    const req = client.get(healthUrl, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.setTimeout(timeoutMs, () => {
      req.destroy();
      resolve(false);
    });
    req.on('error', () => resolve(false));
  });
}

async function waitForBackend(healthUrl = localHealthUrl, attempts = 20, delayMs = 700) {
  for (let i = 0; i < attempts; i += 1) {
    if (i === 3) setSplashStage('正在启动本地工作台服务', '等待 FastAPI 就绪');
    // eslint-disable-next-line no-await-in-loop
    if (await requestBackendHealth(healthUrl)) return true;
    // eslint-disable-next-line no-await-in-loop
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return false;
}

function backendRoot() {
  return isDev ? path.resolve(__dirname, '..') : path.join(process.resourcesPath, 'backend');
}

function resolvePythonCommand() {
  if (process.env.LINGSHU_PYTHON) {
    return { command: process.env.LINGSHU_PYTHON, args: [] };
  }

  if (!isDev) {
    const bundledPython = path.join(process.resourcesPath, 'python', process.platform === 'win32' ? 'python.exe' : 'bin/python3');
    if (fs.existsSync(bundledPython)) {
      return { command: bundledPython, args: [] };
    }
  }

  if (process.platform === 'win32') {
    return { command: 'python', args: [] };
  }
  return { command: 'python3', args: [] };
}

function backendEnvironment() {
  const dataDir = path.join(app.getPath('userData'), 'data');
  try {
    fs.mkdirSync(dataDir, { recursive: true });
  } catch (_err) {
    // The backend will surface a clearer error if the data directory is unusable.
  }
  return {
    ...process.env,
    BOOKSTORE_DB_PATH: process.env.BOOKSTORE_DB_PATH || path.join(dataDir, 'bookstore_demo.db'),
    LINGSHU_BACKEND_HOST: backendHost,
    LINGSHU_BACKEND_PORT: backendPort,
  };
}

function launchBackendProcess() {
  if (backendProcess) return;
  const python = resolvePythonCommand();
  const args = [
    ...python.args,
    '-m',
    'uvicorn',
    'lingshu_api.main:app',
    '--host',
    backendHost,
    '--port',
    backendPort,
  ];
  const cwd = backendRoot();
  writeMainLog('INFO', 'starting local backend', `${python.command} ${args.join(' ')} cwd=${cwd}`);
  backendProcess = spawn(python.command, args, {
    cwd,
    env: backendEnvironment(),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  backendProcess.stdout.on('data', (chunk) => writeMainLog('INFO', 'backend stdout', chunk.toString().trim()));
  backendProcess.stderr.on('data', (chunk) => writeMainLog('ERROR', 'backend stderr', chunk.toString().trim()));
  backendProcess.on('exit', (code, signal) => {
    writeMainLog('INFO', 'backend exited', `code=${code} signal=${signal || ''}`);
    backendProcess = null;
  });
  backendProcess.on('error', (err) => {
    writeMainLog('ERROR', 'backend spawn failed', err && err.stack ? err.stack : String(err));
    backendProcess = null;
  });
}

async function startBackend() {
  setSplashStage('正在启动本地工作台服务', '检查本地 FastAPI');
  if (await requestBackendHealth(localHealthUrl)) {
    writeMainLog('INFO', 'Local backend reachable', localHealthUrl);
    setSplashStage('本地服务已就绪', '准备加载主界面');
    return true;
  }

  if (process.env.LINGSHU_DISABLE_LOCAL_BACKEND !== '1') {
    launchBackendProcess();
  } else {
    writeMainLog('INFO', 'local backend launch disabled by env', 'LINGSHU_DISABLE_LOCAL_BACKEND=1');
  }

  if (await waitForBackend(localHealthUrl)) {
    writeMainLog('INFO', 'Local backend started', localHealthUrl);
    setSplashStage('本地服务已启动', '准备加载主界面');
    return true;
  }

  const cloudReachable = await requestBackendHealth(cloudHealthUrl, 1500);
  writeMainLog('ERROR', 'Local backend unavailable', `${localHealthUrl}; cloudReachable=${cloudReachable}`);
  return false;
}

function stopBackend() {
  if (!backendProcess) return;
  try {
    backendProcess.kill();
  } catch (err) {
    writeMainLog('ERROR', 'backend kill failed', String(err));
  }
  backendProcess = null;
}

// ============================================================
//  IPC 处理 — 本地文件访问 & 密钥安全存储
// ============================================================

// 密钥安全存储 (对应 Qt secure_storage.py 的 DPAPI)
registerSafeStorageHandlers();

// 文件选择对话框
ipcMain.handle('dialog:openFile', async (_event, options) => {
  if (options !== undefined && (typeof options !== 'object' || options === null)) {
    throw new Error('Invalid argument: options must be an object if provided');
  }
  const result = await dialog.showOpenDialog(mainWindow, options || {
    properties: ['openFile'],
    filters: [
      { name: '文档', extensions: ['txt', 'md', 'docx'] },
      { name: '全部', extensions: ['*'] },
    ],
  });
  return result;
});

// 文件读写（异步）— 由共享模块注册
registerFileIpcHandlers();

// 获取应用数据路径（白名单校验，防止获取系统任意目录）
const ALLOWED_PATH_NAMES = ['userData', 'logs', 'desktop', 'documents', 'downloads', 'temp'];
ipcMain.handle('app:getPath', (_event, name) => {
  if (!ALLOWED_PATH_NAMES.includes(name)) {
    throw new Error(`Access denied: path name '${name}' not in whitelist`);
  }
  return app.getPath(name);
});

// ============================================================
//  自动更新 (对应 packaging/BUILD_RULES.txt)
//
//  生产环境代码签名要求：
//    Windows: 需配置环境变量 WIN_CSC_LINK（证书路径）和 WIN_CSC_KEY_PASSWORD（证书密码）
//    macOS:   需配置环境变量 MAC_CSC_NAME（签名身份名称）
//    更新源:  https://update.ling-shu.top（需 HTTPS）
// ============================================================

function setupAutoUpdater() {
  // 仅在打包后的生产环境启用自动更新
  if (isDev) {
    writeMainLog('INFO', 'Auto-updater skipped in development mode');
    return;
  }

  try {
    const { autoUpdater } = require('electron-updater');

    // Windows 代码签名验证 — 拒绝未签名的更新包
    autoUpdater.verifyUpdateCodeSignature = true;

    autoUpdater.setFeedURL({
      provider: 'generic',
      url: 'https://update.ling-shu.top',
    });

    autoUpdater.on('update-available', (info) => {
      writeMainLog('INFO', 'update available', JSON.stringify(info));
    });

    autoUpdater.on('update-downloaded', (info) => {
      writeMainLog('INFO', 'update downloaded', JSON.stringify(info));
    });

    autoUpdater.on('error', (err) => {
      writeMainLog('ERROR', 'auto-updater error', err && err.stack ? err.stack : String(err));
    });

    autoUpdater.checkForUpdates().catch((err) => {
      writeMainLog('ERROR', 'checkForUpdates failed', err && err.stack ? err.stack : String(err));
    });

    writeMainLog('INFO', 'Auto-updater initialized with code signature verification enabled');
  } catch (err) {
    writeMainLog('WARN', 'Auto-updater not available', err && err.message ? err.message : String(err));
  }
}

// ============================================================
//  应用生命周期
// ============================================================

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  writeMainLog('INFO', 'app ready', `isPackaged=${app.isPackaged} resourcesPath=${process.resourcesPath}`);
  createSplashWindow();
  setSplashStage('正在启动灵枢', '启动本地工作台服务');
  const backendReady = await startBackend();
  if (!backendReady) {
    setSplashStage('本地服务启动失败', '请检查本地 Python/FastAPI 环境');
    dialog.showErrorBox(
      '无法启动本地工作台服务',
      `无法连接到本地灵枢服务：${localHealthUrl}\n\n请检查 Python/FastAPI 环境，或设置 LINGSHU_BACKEND_HOST / LINGSHU_BACKEND_PORT 指向已有本地服务。`,
    );
  } else {
    setSplashStage('正在加载主界面', '灵枢工作台即将打开');
  }
  createWindow();
  setupAutoUpdater();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopBackend();
});
