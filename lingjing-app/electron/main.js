const { app, BrowserWindow, ipcMain, dialog, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { writeMainLog, isPathAllowed, registerSafeStorageHandlers, registerFileIpcHandlers } = require('../../electron/shared/electron-common');

// ============================================================
//  灵镜管理台 Electron 主进程
// ============================================================

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
let mainWindow = null;

// 内存中缓存的密钥（不暴露给渲染进程）
let _cachedSecret = null;
let _cachedSecretExpiresAt = 0;
const KEY_CACHE_TTL_MS = Math.max(
  60 * 1000,
  Number.parseInt(process.env.LINGJING_KEY_CACHE_TTL_MS || `${15 * 60 * 1000}`, 10) || 15 * 60 * 1000,
);

function cacheSecret(secret) {
  _cachedSecret = secret || null;
  _cachedSecretExpiresAt = _cachedSecret ? Date.now() + KEY_CACHE_TTL_MS : 0;
}

function clearCachedSecret() {
  _cachedSecret = null;
  _cachedSecretExpiresAt = 0;
}

function getCachedSecret() {
  if (!_cachedSecret) return null;
  if (Date.now() >= _cachedSecretExpiresAt) {
    clearCachedSecret();
    return null;
  }
  return _cachedSecret;
}

function publicKeyData(keyData) {
  return {
    key_id: keyData.key_id,
    issued_to: keyData.issued_to,
    cache_expires_at: _cachedSecretExpiresAt,
  };
}

// 服务器配置
const SERVER_HOST = process.env.LINGJING_SERVER_HOST || 'www.ling-shu.top';
const SERVER_PORT = process.env.LINGJING_SERVER_PORT || '';
const SERVER_PROTOCOL = process.env.LINGJING_SERVER_PROTOCOL || 'https';
const SERVER_BASE_URL = (
  process.env.LINGJING_SERVER_BASE_URL
  || `${SERVER_PROTOCOL}://${SERVER_HOST}${SERVER_PORT ? `:${SERVER_PORT}` : ''}`
).replace(/\/+$/, '');

function createWindow() {
  writeMainLog('INFO', 'createWindow', `isDev=${isDev}`);

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    title: '灵镜管理台',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
    frame: true,
    backgroundColor: '#1a2e44',
    show: false,
  });

  mainWindow.setMenuBarVisibility(false);

  if (isDev) {
    mainWindow.loadURL('http://127.0.0.1:5176');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    const indexPath = path.join(__dirname, '..', 'dist', 'index.html');
    writeMainLog('INFO', 'loadFile', indexPath);
    mainWindow.loadFile(indexPath);
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ============================================================
//  路径白名单校验 — isPathAllowed 由共享模块提供
//  密钥文件路径校验仍保留在此（灵镜特有逻辑）
// ============================================================

function isKeyFilePathAllowed(filePath) {
  let resolved = path.resolve(filePath);
  // 只允许 .lingshu-key 扩展名的文件
  if (!resolved.endsWith('.lingshu-key')) return false;
  // 解析符号链接，防止通过符号链接绕过目录限制
  try {
    resolved = fs.realpathSync(resolved);
  } catch {
    return false; // 文件不存在或无法解析
  }
  // 限制文件必须在 userData 目录或用户常用目录下
  const userDataPath = app.getPath('userData');
  const homePath = app.getPath('home');
  const allowedDirs = [userDataPath, path.join(homePath, 'Desktop'), path.join(homePath, 'Documents'), path.join(homePath, 'Downloads')];
  // 解析白名单目录的真实路径（处理本地化目录名）
  const resolvedAllowedDirs = allowedDirs.map(dir => {
    try { return fs.realpathSync(dir); } catch { return dir; }
  });
  const inAllowedDir = resolvedAllowedDirs.some(dir => resolved.startsWith(dir + path.sep) || resolved === dir);
  if (!inAllowedDir) return false;
  return true;
}

// ============================================================
//  IPC — 密钥安全存储 & 文件访问（共享模块注册）
// ============================================================

registerSafeStorageHandlers();
registerFileIpcHandlers();

// ============================================================
//  IPC — 密钥文件管理（灵镜特有）
// ============================================================

// 读取密钥文件（仅允许 .lingshu-key 文件）
ipcMain.handle('key:readFile', async (_event, filePath) => {
  try {
    if (typeof filePath !== 'string' || !filePath) {
      return { ok: false, error: '参数错误：filePath 必须为非空字符串' };
    }
    if (!isKeyFilePathAllowed(filePath)) {
      return { ok: false, error: '访问被拒绝：仅允许读取受信任目录下的 .lingshu-key 密钥文件' };
    }
    // 使用 realpathSync 解析后的路径读取，防止符号链接绕过
    const resolved = fs.realpathSync(path.resolve(filePath));
    const content = fs.readFileSync(resolved, 'utf-8');
    const keyData = JSON.parse(content);

    // 验证密钥文件格式
    if (!keyData.key_id || !keyData.secret || !keyData.issued_to) {
      return { ok: false, error: '密钥文件格式无效' };
    }

    // 缓存密钥到主进程内存（不返回secret给渲染进程）
    cacheSecret(keyData.secret);
    return { ok: true, keyData: publicKeyData(keyData) };
  } catch (err) {
    return { ok: false, error: `读取密钥文件失败: ${err.message}` };
  }
});

// 选择密钥文件对话框
ipcMain.handle('key:openFileDialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: '灵镜密钥文件', extensions: ['lingshu-key'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || result.filePaths.length === 0) {
    return { ok: false, canceled: true };
  }
  return { ok: true, filePath: result.filePaths[0] };
});

// 安全存储密钥（使用 Electron safeStorage）
ipcMain.handle('key:store', (_event, keyDataJson) => {
  try {
    const userDataPath = app.getPath('userData');
    const keyStorePath = path.join(userDataPath, 'admin_key.enc');

    if (safeStorage.isEncryptionAvailable()) {
      const parsed = JSON.parse(keyDataJson);
      const secret = parsed.secret || getCachedSecret();
      if (!parsed.key_id || !secret || !parsed.issued_to) {
        return { ok: false, error: '密钥数据不完整或内存缓存已过期，请重新导入密钥文件' };
      }
      const fullKeyData = { ...parsed, secret };
      const encrypted = safeStorage.encryptString(JSON.stringify(fullKeyData));
      fs.writeFileSync(keyStorePath, encrypted);
      cacheSecret(secret);
      return { ok: true };
    }
    return { ok: false, error: 'safeStorage不可用，拒绝明文存储管理密钥' };
  } catch (err) {
    return { ok: false, error: `存储密钥失败: ${err.message}` };
  }
});

// 读取已存储的密钥
ipcMain.handle('key:load', () => {
  try {
    const userDataPath = app.getPath('userData');
    const keyStorePath = path.join(userDataPath, 'admin_key.enc');

    if (!fs.existsSync(keyStorePath)) {
      return { ok: false, error: '未找到已存储的密钥' };
    }

    const buffer = fs.readFileSync(keyStorePath);

    if (safeStorage.isEncryptionAvailable()) {
      const decrypted = safeStorage.decryptString(buffer);
      const keyData = JSON.parse(decrypted);
      // 缓存密钥到主进程内存
      cacheSecret(keyData.secret);
      // 不返回secret给渲染进程
      return { ok: true, keyData: publicKeyData(keyData) };
    }
    return { ok: false, error: 'safeStorage不可用，拒绝读取可能未加密的管理密钥' };
  } catch (err) {
    return { ok: false, error: `加载密钥失败: ${err.message}` };
  }
});

// 删除已存储的密钥
ipcMain.handle('key:remove', () => {
  try {
    clearCachedSecret();
    const userDataPath = app.getPath('userData');
    const keyStorePath = path.join(userDataPath, 'admin_key.enc');
    if (fs.existsSync(keyStorePath)) {
      fs.unlinkSync(keyStorePath);
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, error: `删除密钥失败: ${err.message}` };
  }
});

// 计算HMAC签名 — 密钥由主进程内部管理，渲染进程只传消息
ipcMain.handle('key:computeHmac', (_event, message) => {
  try {
    if (typeof message !== 'string') {
      return { ok: false, error: '参数错误：message 必须为字符串' };
    }
    const secret = getCachedSecret();
    if (!secret) {
      return { ok: false, error: '密钥缓存已过期，请重新导入密钥文件' };
    }
    const hmac = crypto.createHmac('sha256', secret);
    hmac.update(message);
    return { ok: true, signature: hmac.digest('hex') };
  } catch (err) {
    return { ok: false, error: `计算签名失败: ${err.message}` };
  }
});

// 检查是否已有存储的密钥
ipcMain.handle('key:hasStored', () => {
  const userDataPath = app.getPath('userData');
  const keyStorePath = path.join(userDataPath, 'admin_key.enc');
  return fs.existsSync(keyStorePath);
});

// 获取服务器地址
ipcMain.handle('app:getServerUrl', () => {
  return SERVER_BASE_URL;
});

// ============================================================
//  自动更新 & 代码签名验证
//
//  生产环境代码签名要求：
//    Windows: 需配置环境变量 WIN_CSC_LINK（证书路径）和 WIN_CSC_KEY_PASSWORD（证书密码）
//    macOS:   需配置环境变量 MAC_CSC_NAME（签名身份名称）
//    更新源:  https://update.ling-shu.top（需 HTTPS）
//
//  启用自动更新时，取消下方注释并安装 electron-updater：
//    const { autoUpdater } = require('electron-updater');
//    autoUpdater.verifyUpdateCodeSignature = true;  // Windows 代码签名验证
//    autoUpdater.setFeedURL({ provider: 'generic', url: 'https://update.ling-shu.top' });
// ============================================================

// ============================================================
//  应用生命周期
// ============================================================

app.whenReady().then(() => {
  writeMainLog('INFO', 'app ready', `isPackaged=${app.isPackaged}`);
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
