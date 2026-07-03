const { contextBridge, ipcRenderer } = require('electron');

const backendPort = process.env.LINGSHU_BACKEND_PORT || '8787';
const backendHost = process.env.LINGSHU_BACKEND_HOST || '127.0.0.1';
const cloudBaseUrl = process.env.LINGSHU_CLOUD_BASE_URL || 'https://www.ling-shu.top';
const localBaseUrl = (process.env.LINGSHU_LOCAL_BASE_URL || `http://${backendHost}:${backendPort}`).replace(/\/+$/, '');
const cloudWsBaseUrl = process.env.LINGSHU_CLOUD_WS_BASE_URL || cloudBaseUrl.replace(/^http/, 'ws').replace(/\/+$/, '') + '/ws';

/**
 * 灵枢 preload 脚本 — 暴露安全 API 到渲染进程
 * 对应 Qt: secure_storage.py (DPAPI) + QFileDialog (文件访问)
 */
contextBridge.exposeInMainWorld('lingshu', {
  apiBaseUrl: process.env.LINGSHU_API_BASE_URL || `${localBaseUrl}/api`,
  wsBaseUrl: process.env.LINGSHU_WS_BASE_URL || `${localBaseUrl.replace(/^http/, 'ws')}/ws`,
  cloudBaseUrl,
  cloudApiBaseUrl: `${cloudBaseUrl.replace(/\/+$/, '')}/api`,
  cloudWsBaseUrl,

  // 密钥安全存储 (对应 secure_storage.py DPAPI)
  protectSecret: (secret) => ipcRenderer.invoke('secure:protect', secret),
  unprotectSecret: (encrypted) => ipcRenderer.invoke('secure:unprotect', encrypted),

  // 文件系统
  openFileDialog: (options) => ipcRenderer.invoke('dialog:openFile', options),
  readFile: (filePath) => ipcRenderer.invoke('fs:readFile', filePath),
  writeFile: (filePath, content) => ipcRenderer.invoke('fs:writeFile', filePath, content),
  statFile: (filePath) => ipcRenderer.invoke('fs:stat', filePath),

  // 应用信息
  getPath: (name) => ipcRenderer.invoke('app:getPath', name),
  onOpenSearch: (callback) => {
    const handler = () => {
      if (typeof callback === 'function') callback();
    };
    ipcRenderer.on('app:open-search', handler);
    return () => ipcRenderer.removeListener('app:open-search', handler);
  },
  platform: process.platform,
  isElectron: true,
});
