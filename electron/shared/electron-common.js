// ============================================================
//  灵枢 / 灵镜 共享 Electron 主进程工具
//  — writeMainLog、isPathAllowed、safeStorage IPC、文件 IPC
// ============================================================

const { app, ipcMain, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');

// ------------------------------------------------------------------
//  日志
// ------------------------------------------------------------------

function writeMainLog(level, message, extra = '') {
  const line = `[${new Date().toISOString()}] [${level}] ${message}${extra ? ` ${extra}` : ''}\n`;
  try {
    const logDir = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(path.join(logDir, 'main.log'), line, 'utf-8');
  } catch (_err) {
    // File logging must never block app startup.
  }
  const writer = level === 'ERROR' ? console.error : console.log;
  writer(line.trimEnd());
}

// ------------------------------------------------------------------
//  路径白名单校验：只允许访问 userData 目录
//  使用 realpathSync 解析符号链接，防止通过符号链接绕过白名单
// ------------------------------------------------------------------

function isPathAllowed(filePath) {
  const userDataPath = app.getPath('userData');
  let resolved;
  try {
    resolved = fs.realpathSync(path.resolve(filePath));
  } catch (_err) {
    // 文件不存在时无法解析符号链接，使用 resolve 结果
    resolved = path.resolve(filePath);
  }
  let realUserDataPath;
  try {
    realUserDataPath = fs.realpathSync(userDataPath);
  } catch (_err) {
    realUserDataPath = userDataPath;
  }
  return resolved.startsWith(realUserDataPath + path.sep) || resolved === realUserDataPath;
}

// ------------------------------------------------------------------
//  密钥安全存储 IPC（secure:protect / secure:unprotect）
// ------------------------------------------------------------------

function registerSafeStorageHandlers() {
  ipcMain.handle('secure:protect', (_event, secret) => {
    try {
      if (safeStorage.isEncryptionAvailable()) {
        const encrypted = safeStorage.encryptString(secret);
        return encrypted.toString('base64');
      }
      throw new Error('Electron safeStorage is unavailable; refusing to store secrets without encryption');
    } catch (err) {
      console.error('secure:protect error:', err);
      throw err;
    }
  });

  ipcMain.handle('secure:unprotect', (_event, encryptedBase64) => {
    try {
      if (safeStorage.isEncryptionAvailable()) {
        const buf = Buffer.from(encryptedBase64, 'base64');
        return safeStorage.decryptString(buf);
      }
      throw new Error('Electron safeStorage is unavailable; refusing to read secrets without encryption');
    } catch (err) {
      console.error('secure:unprotect error:', err);
      throw err;
    }
  });
}

// ------------------------------------------------------------------
//  文件读写 IPC（fs:readFile / fs:writeFile / fs:stat）
//  含大小限制与路径白名单校验
// ------------------------------------------------------------------

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

function registerFileIpcHandlers() {
  ipcMain.handle('fs:readFile', async (_event, filePath) => {
    if (typeof filePath !== 'string' || !filePath) {
      throw new Error('Invalid argument: filePath must be a non-empty string');
    }
    if (!isPathAllowed(filePath)) {
      throw new Error('Access denied: path outside allowed directory');
    }
    const stat = await fs.promises.stat(filePath);
    if (stat.size > MAX_FILE_SIZE) {
      throw new Error(`File too large: ${stat.size} bytes (max ${MAX_FILE_SIZE} bytes)`);
    }
    return await fs.promises.readFile(filePath, 'utf-8');
  });

  ipcMain.handle('fs:writeFile', async (_event, filePath, content) => {
    if (typeof filePath !== 'string' || !filePath) {
      throw new Error('Invalid argument: filePath must be a non-empty string');
    }
    if (typeof content !== 'string') {
      throw new Error('Invalid argument: content must be a string');
    }
    if (!isPathAllowed(filePath)) {
      throw new Error('Access denied: path outside allowed directory');
    }
    if (content.length > MAX_FILE_SIZE) {
      throw new Error(`Content too large: ${content.length} bytes (max ${MAX_FILE_SIZE} bytes)`);
    }
    await fs.promises.writeFile(filePath, content, 'utf-8');
    return true;
  });

  ipcMain.handle('fs:stat', async (_event, filePath) => {
    if (typeof filePath !== 'string' || !filePath) {
      throw new Error('Invalid argument: filePath must be a non-empty string');
    }
    if (!isPathAllowed(filePath)) {
      throw new Error('Access denied: path outside allowed directory');
    }
    const stat = await fs.promises.stat(filePath);
    return {
      size: stat.size,
      mtime: stat.mtime.getTime(),
      isFile: stat.isFile(),
      isDirectory: stat.isDirectory(),
    };
  });
}

// ------------------------------------------------------------------
//  导出
// ------------------------------------------------------------------

module.exports = {
  writeMainLog,
  isPathAllowed,
  registerSafeStorageHandlers,
  registerFileIpcHandlers,
  MAX_FILE_SIZE,
};
