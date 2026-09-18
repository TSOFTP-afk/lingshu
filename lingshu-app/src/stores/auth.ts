/**
 * 认证 Store — 用户登录状态管理
 */
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import api, { getAuthToken, setAuthToken, tokenReady } from '../utils/api';
import { useCloudStore } from './cloud';
import { useEventBus } from '../composables/useEventBus';
import type { AuthUser, LoginResponse, ApiError } from '../../../shared/types';

// AuthUser / LoginResponse / ApiError 已迁移至 ../../../shared/types（V5-P3-05），
// 此处通过 re-export 保留对外契约，避免破坏现有 import { AuthUser } from './auth' 的代码。
export type { AuthUser, LoginResponse };

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(getAuthToken() || '');
  const user = ref<AuthUser | null>(null);
  const initialized = ref<boolean>(false);
  const loading = ref<boolean>(false);
  const error = ref<string>('');

  const isLoggedIn = computed<boolean>(() => !!token.value);
  const isAuthor = computed<boolean>(() => user.value?.is_author === 1);

  async function login(username: string, password: string): Promise<LoginResponse> {
    return runAuthRequest(async () => {
      const { data } = await api.post('/auth/login', { username, password });
      applySession(data);
      triggerCloudSync();
      return data;
    });
  }

  async function register(username: string, password: string, isAuthor: number = 1): Promise<LoginResponse> {
    return runAuthRequest(async () => {
      const { data } = await api.post('/auth/register', { username, password, is_author: isAuthor });
      applySession(data);
      triggerCloudSync();
      return data;
    });
  }

  async function fetchMe(): Promise<AuthUser | null> {
    if (!token.value) {
      initialized.value = true;
      return null;
    }
    loading.value = true;
    error.value = '';
    try {
      const { data } = await api.get('/auth/me');
      user.value = data;
      initialized.value = true;
      return data;
    } catch (e: unknown) {
      error.value = authErrorMessage(e as ApiError);
      logout();
      return null;
    } finally {
      loading.value = false;
    }
  }

  async function init(): Promise<AuthUser | null> {
    if (initialized.value) return user.value;
    await tokenReady;
    if (!token.value && getAuthToken()) {
      token.value = getAuthToken() || '';
    }
    if (!token.value) {
      initialized.value = true;
      return null;
    }
    return fetchMe();
  }

  function logout(): void {
    token.value = '';
    user.value = null;
    error.value = '';
    initialized.value = true;
    setAuthToken('');
  }

  function applySession(data: LoginResponse | null): void {
    const accessToken = data?.access_token || '';
    token.value = accessToken;
    user.value = data?.user || null;
    initialized.value = true;
    error.value = '';
    setAuthToken(accessToken);
  }

  async function runAuthRequest<T>(action: () => Promise<T>): Promise<T> {
    loading.value = true;
    error.value = '';
    try {
      return await action();
    } catch (e: unknown) {
      error.value = authErrorMessage(e as ApiError);
      throw e;
    } finally {
      loading.value = false;
    }
  }

  function authErrorMessage(e: ApiError): string {
    const detail = e?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') return detail.message || '认证失败';
    return e?.message || '认证失败';
  }

  function triggerCloudSync(): void {
    try {
      const cloudStore = useCloudStore();
      cloudStore.syncUploadedBooks().catch(() => {});
    } catch {
      // cloud store 未初始化时忽略
    }
  }

  function requireAuth(): boolean {
    if (isLoggedIn.value) return true;
    const { emit } = useEventBus();
    emit('lingshu:open-login');
    return false;
  }

  function requireAiAccess(): boolean {
    return requireAuth();
  }

  return {
    token,
    user,
    initialized,
    loading,
    error,
    isLoggedIn,
    isAuthor,
    init,
    login,
    register,
    fetchMe,
    logout,
    requireAuth,
    requireAiAccess,
  };
});
