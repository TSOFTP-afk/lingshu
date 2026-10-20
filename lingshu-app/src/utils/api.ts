import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios';

/**
 * Electron 桥接对象类型 —— 由主进程通过 preload 注入到 window.lingshu。
 */
export interface LingshuBridge {
  apiBaseUrl?: string;
  wsBaseUrl?: string;
  /** safeStorage 加密保护明文密钥 */
  protectSecret?: (secret: string) => Promise<string>;
  /** safeStorage 解密已加密密钥 */
  unprotectSecret?: (encrypted: string) => Promise<string>;
}

declare global {
  interface Window {
    lingshu?: LingshuBridge;
  }
}

const electronBridge: LingshuBridge | null =
  typeof window !== 'undefined' ? window.lingshu ?? null : null;

function _sameOriginApiBase(): string {
  if (typeof location === 'undefined' || !location.origin || location.origin === 'null') return '/api';
  return `${location.origin}/api`;
}

function _sameOriginWsBase(): string {
  if (typeof location === 'undefined' || !location.host) return '/ws';
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${location.host}/ws`;
}

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL
  || electronBridge?.apiBaseUrl
  || _sameOriginApiBase();

export const WS_BASE_URL: string =
  import.meta.env.VITE_WS_BASE_URL
  || electronBridge?.wsBaseUrl
  || _sameOriginWsBase();

function _normalizeWsUrl(rawUrl: string): URL {
  const url = new URL(rawUrl);
  if (!['ws:', 'wss:'].includes(url.protocol)) {
    throw new Error('WebSocket URL must use ws:// or wss://');
  }
  if (url.username || url.password) {
    throw new Error('WebSocket URL must not include credentials');
  }
  if (!url.pathname.startsWith('/ws')) {
    throw new Error('WebSocket URL path must start with /ws');
  }
  return url;
}

function _allowedWsOrigins(): Set<string> {
  const origins = new Set<string>();
  try {
    origins.add(_normalizeWsUrl(WS_BASE_URL).origin);
  } catch {
    // Invalid configured base URL will be reported when buildWsUrl is used.
  }
  const sameOriginBase = _sameOriginWsBase();
  if (sameOriginBase) {
    origins.add(new URL(sameOriginBase).origin);
  }
  return origins;
}

function _assertAllowedWsUrl(rawUrl: string): string {
  const url = _normalizeWsUrl(rawUrl);
  if (!_allowedWsOrigins().has(url.origin)) {
    throw new Error(`WebSocket URL origin is not allowed: ${url.origin}`);
  }
  return url.toString();
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 0,
});

// ============================================================
//  Token 安全存储
//  - Electron 环境：safeStorage 加密存 localStorage['lingshu_token_encrypted']
//  - 纯浏览器环境：localStorage['lingshu_token_web'] 持久化（刷新不丢失登录）
//  - 内存 _memoryToken 始终是运行时唯一来源
// ============================================================

const WEB_TOKEN_KEY = 'lingshu_token_web';

let _memoryToken: string = '';

// Token 初始化就绪 Promise：防止异步解密未完成时请求发出 401
// 使用 definite assignment assertion：Promise 构造器同步执行时会立即赋值
let _tokenReadyResolve!: () => void;
export const tokenReady: Promise<void> = new Promise<void>((resolve) => {
  _tokenReadyResolve = resolve;
});

function _initTokenFromSafeStorage(): void {
  if (electronBridge?.unprotectSecret) {
    // Electron：safeStorage 解密
    const encrypted = localStorage.getItem('lingshu_token_encrypted');
    if (encrypted) {
      electronBridge.unprotectSecret(encrypted)
        .then((decrypted: string) => {
          if (decrypted) _memoryToken = decrypted;
          _tokenReadyResolve();
        })
        .catch(() => {
          // safeStorage 解密失败，不回退到明文 Token，强制重新登录
          localStorage.removeItem('lingshu_token_encrypted');
          localStorage.removeItem('lingshu_token');
          localStorage.removeItem(WEB_TOKEN_KEY);
          _tokenReadyResolve();
        });
    } else {
      // Electron 下无加密 token，但可能从浏览器会话迁入，尝试 web key
      const webToken = localStorage.getItem(WEB_TOKEN_KEY);
      if (webToken) _memoryToken = webToken;
      _tokenReadyResolve();
    }
  } else {
    // 纯浏览器：从 localStorage 恢复
    const webToken = localStorage.getItem(WEB_TOKEN_KEY);
    if (webToken) _memoryToken = webToken;
    localStorage.removeItem('lingshu_token'); // 清理历史明文 key
    _tokenReadyResolve();
  }
}

function _migrateToSafeStorage(token: string): void {
  localStorage.removeItem('lingshu_token');
  if (!electronBridge?.protectSecret || !token) return;
  electronBridge.protectSecret(token)
    .then((encrypted: string) => {
      localStorage.setItem('lingshu_token_encrypted', encrypted);
      localStorage.removeItem('lingshu_token');
      localStorage.removeItem(WEB_TOKEN_KEY); // Electron 下不再使用 web key
    })
    .catch(() => {
      // safeStorage 加密失败时只保留内存 token，不回退到明文 localStorage
      localStorage.removeItem('lingshu_token_encrypted');
      localStorage.removeItem('lingshu_token');
      localStorage.removeItem(WEB_TOKEN_KEY);
    });
}

function _clearTokenStorage(): void {
  _memoryToken = '';
  localStorage.removeItem('lingshu_token');
  localStorage.removeItem('lingshu_token_encrypted');
  localStorage.removeItem(WEB_TOKEN_KEY);
}

// 初始化：从安全存储加载 token
_initTokenFromSafeStorage();

export function getAuthToken(): string {
  return _memoryToken || '';
}

// 暴露 tokenReady 供 auth store 等待异步恢复完成（Electron safeStorage 解密）
// （已在上方通过 export const tokenReady 同步导出）

export function setAuthToken(token: string | null | undefined): void {
  if (token) {
    _memoryToken = token;
    if (electronBridge?.protectSecret) {
      // Electron 环境：仅使用 safeStorage 加密存储
      _migrateToSafeStorage(token);
    } else {
      // 纯浏览器环境：持久化到 localStorage，刷新后仍保持登录
      localStorage.setItem(WEB_TOKEN_KEY, token);
      localStorage.removeItem('lingshu_token');
    }
  } else {
    _clearTokenStorage();
  }
}

export function buildWsUrl(path: string | null | undefined): string {
  const value = String(path || '');
  if (value.startsWith('ws://') || value.startsWith('wss://')) {
    return _assertAllowedWsUrl(value);
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(value)) {
    throw new Error('WebSocket URL must be a /ws path or ws(s) URL');
  }
  const base = _normalizeWsUrl(WS_BASE_URL || _sameOriginWsBase());
  const basePath = base.pathname.replace(/\/+$/, '');
  const childPath = value.startsWith('/') ? value : `/${value}`;
  const finalPath =
    childPath === basePath || childPath.startsWith(`${basePath}/`)
      ? childPath
      : `${basePath}${childPath}`;
  return _assertAllowedWsUrl(`${base.protocol}//${base.host}${finalPath}`);
}

export function sendWsAuth(ws: WebSocket): string {
  const token = getAuthToken();
  ws.send(JSON.stringify({ type: 'auth', payload: { token } }));
  return token;
}

// 请求拦截器：等待 Token 就绪后自动附加 Authorization
api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  await tokenReady;
  const token = getAuthToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器：401 时清理本地 token（登录界面已随多用户产品形态移除）
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      _clearTokenStorage();
    }
    return Promise.reject(error);
  },
);

export default api;
