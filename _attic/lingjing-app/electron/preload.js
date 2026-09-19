const { contextBridge, ipcRenderer } = require('electron');

const serverHost = process.env.LINGJING_SERVER_HOST || 'www.ling-shu.top';
const serverPort = process.env.LINGJING_SERVER_PORT || '';
const serverProtocol = process.env.LINGJING_SERVER_PROTOCOL || 'https';
const serverBaseUrl = (
  process.env.LINGJING_SERVER_BASE_URL
  || `${serverProtocol}://${serverHost}${serverPort ? `:${serverPort}` : ''}`
).replace(/\/+$/, '');

/**
 * 灵镜管理台 preload — 暴露密钥管理和API工具到渲染进程
 */
contextBridge.exposeInMainWorld('lingjing', {
  // 服务器地址
  serverBaseUrl,
  getServerUrl: () => ipcRenderer.invoke('app:getServerUrl'),

  // 密钥文件管理
  keyOpenFileDialog: () => ipcRenderer.invoke('key:openFileDialog'),
  keyReadFile: (filePath) => ipcRenderer.invoke('key:readFile', filePath),
  keyStore: (keyData) => ipcRenderer.invoke('key:store', JSON.stringify(keyData)),
  keyLoad: () => ipcRenderer.invoke('key:load'),
  keyRemove: () => ipcRenderer.invoke('key:remove'),
  keyHasStored: () => ipcRenderer.invoke('key:hasStored'),

  // HMAC签名（密钥由主进程管理，渲染进程只传消息）
  computeHmac: (message) => ipcRenderer.invoke('key:computeHmac', message),

  // 环境标识
  isElectron: true,
  platform: process.platform,
});
