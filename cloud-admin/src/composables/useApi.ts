import type { Ref } from 'vue';
import axios from 'axios';
import { ElMessage } from 'element-plus';
import {
  formatNumber,
  formatValue,
  formatBytes,
  formatDuration,
} from '../../../shared/formatters';

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

  // formatNumber / formatValue / formatBytes / formatDuration 已迁移至
  // ../../../shared/formatters（V5-P3-05），上方通过 import 引入。
  // 此处仅保留 formatStatCard：它依赖 cloud-admin 特有的 Row + card.format 语义，
  // 不适合作为通用函数共享。

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
