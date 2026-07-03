/**
 * 认证 Store — 用户登录状态管理
 */
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import api, { getAuthToken, setAuthToken, tokenReady } from '../utils/api';
import { useCloudStore } from './cloud';
import { useEventBus } from '../composables/useEventBus';

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getAuthToken());
  const user = ref(null);
  const initialized = ref(false);
  const loading = ref(false);
  const error = ref('');

  const isLoggedIn = computed(() => !!token.value);
  const isAuthor = computed(() => user.value?.is_author === 1);

  async function login(username, password) {
    return runAuthRequest(async () => {
      const { data } = await api.post('/auth/login', { username, password });
      applySession(data);
      triggerCloudSync();
      return data;
    });
  }

  async function register(username, password, isAuthor = 1) {
    return runAuthRequest(async () => {
      const { data } = await api.post('/auth/register', { username, password, is_author: isAuthor });
      applySession(data);
      triggerCloudSync();
      return data;
    });
  }

  async function fetchMe() {
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
    } catch (e) {
      error.value = authErrorMessage(e);
      logout();
      return null;
    } finally {
      loading.value = false;
    }
  }

  async function init() {
    if (initialized.value) return user.value;
    // 等待 token 异步恢复完成（Electron safeStorage 解密 / 浏览器 localStorage 同步读取）
    await tokenReady;
    // 恢复完成后，若 store state 还为空但内存 token 已就位，回填 store state
    if (!token.value && getAuthToken()) {
      token.value = getAuthToken();
    }
    if (!token.value) {
      initialized.value = true;
      return null;
    }
    return fetchMe();
  }

  function logout() {
    token.value = '';
    user.value = null;
    error.value = '';
    initialized.value = true;
    setAuthToken('');
  }

  function applySession(data) {
    const accessToken = data?.access_token || '';
    token.value = accessToken;
    user.value = data?.user || null;
    initialized.value = true;
    error.value = '';
    setAuthToken(accessToken);
  }

  async function runAuthRequest(action) {
    loading.value = true;
    error.value = '';
    try {
      return await action();
    } catch (e) {
      error.value = authErrorMessage(e);
      throw e;
    } finally {
      loading.value = false;
    }
  }

  function authErrorMessage(e) {
    const detail = e?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') return detail.message || '认证失败';
    return e?.message || '认证失败';
  }

  function triggerCloudSync() {
    try {
      const cloudStore = useCloudStore();
      cloudStore.syncUploadedBooks().catch(() => {});
    } catch {
      // cloud store 未初始化时忽略
    }
  }

  function requireAuth() {
    if (isLoggedIn.value) return true;
    const { emit } = useEventBus();
    emit('lingshu:open-login');
    return false;
  }

  function requireAiAccess() {
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
