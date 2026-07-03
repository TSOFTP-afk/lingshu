import type { Ref } from 'vue';
import axios from 'axios';
import { ElMessage } from 'element-plus';

export type Row = Record<string, any>;

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// 生成或获取加密密钥（基于域名派生，同一域名下稳定）
async function _getCryptoKey(): Promise<CryptoKey> {
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode('lingshu-admin-token-encryption-key-v1'),
    { name: 'PBKDF2' },
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: new TextEncoder().encode(location.hostname),
      iterations: 100000,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

export async function _obfuscate(str: string): Promise<string> {
  try {
    const key = await _getCryptoKey();
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      key,
      new TextEncoder().encode(str),
    );
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);
    return btoa(String.fromCharCode(...combined));
  } catch {
    return '';
  }
}

export async function _deobfuscate(str: string): Promise<string> {
  try {
    const combined = Uint8Array.from(atob(str), (c) => c.charCodeAt(0));
    const iv = combined.slice(0, 12);
    const data = combined.slice(12);
    const key = await _getCryptoKey();
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      key,
      data,
    );
    return new TextDecoder().decode(decrypted);
  } catch {
    return '';
  }
}

export function isNetworkError(err: any): boolean {
  return !err.response;
}

export function showNetworkError(action: string): string {
  const msg = `无法连接到远程服务器（${action}）。请检查网络连接或确认服务器是否在线。`;
  ElMessage({ message: msg, type: 'error', duration: 5000, showClose: true });
  return msg;
}

export function useApi(token: Ref<string>) {
  function authHeaders() {
    return token.value ? { Authorization: `Bearer ${token.value}` } : {};
  }

  async function apiGet(path: string, params: Row = {}) {
    const response = await axios.get(`${API_BASE}${path}`, { params, headers: authHeaders() });
    return response.data;
  }

  async function apiPatch(path: string, payload: Row) {
    const response = await axios.patch(`${API_BASE}${path}`, payload, { headers: authHeaders() });
    return response.data;
  }

  async function apiPost(path: string, payload: Row = {}) {
    const response = await axios.post(`${API_BASE}${path}`, payload, { headers: authHeaders() });
    return response.data;
  }

  async function apiDelete(path: string) {
    const response = await axios.delete(`${API_BASE}${path}`, { headers: authHeaders() });
    return response.data;
  }

  function formatNumber(value: number | string | undefined | null) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) return '0';
    return Math.round(num).toLocaleString();
  }

  function formatValue(value: unknown) {
    if (value === null || value === undefined || value === '') return '-';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function formatBytes(bytes: number | undefined | null) {
    if (!bytes && bytes !== 0) return '-';
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    let val = bytes;
    while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
    return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function formatDuration(seconds: number | string | undefined | null) {
    const total = Math.max(0, Math.floor(Number(seconds || 0)));
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (days > 0) return `${days}天 ${hours}小时`;
    if (hours > 0) return `${hours}小时 ${minutes}分钟`;
    if (minutes > 0) return `${minutes}分钟`;
    return `${total}秒`;
  }

  function formatStatCard(card: Row) {
    if (card.format === 'duration') return formatDuration(card.value);
    if (card.format === 'bytes') return formatBytes(card.value);
    return formatNumber(card.value);
  }

  return {
    API_BASE,
    authHeaders,
    apiGet,
    apiPatch,
    apiPost,
    apiDelete,
    formatNumber,
    formatValue,
    formatBytes,
    formatDuration,
    formatStatCard,
  };
}
