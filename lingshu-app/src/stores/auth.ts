/**
 * 认证 Store — 本地单用户模式入口
 *
 * 本地模式下后端 /auth/me 无 token 也返回本地用户（200），
 * init() 探测成功即视为登录态，前端不再提供登录/注册/登出界面。
 */
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import api, { getAuthToken, setAuthToken, tokenReady } from '../utils/api';
import type { AuthUser } from '../../../shared/types';

// AuthUser 已迁移至 ../../../shared/types（V5-P3-05），
// 此处通过 re-export 保留对外契约，避免破坏现有 import { AuthUser } from './auth' 的代码。
export type { AuthUser };

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(getAuthToken() || '');
  const user = ref<AuthUser | null>(null);
  const initialized = ref<boolean>(false);

  // 本地模式：init 探测 /auth/me 命中本地用户（无 token）即视为已登录
  const isLoggedIn = computed<boolean>(() => Boolean(token.value || user.value));
  const isAuthor = computed<boolean>(() => user.value?.is_author === 1);

  async function fetchMe(): Promise<AuthUser | null> {
    if (!token.value) {
      initialized.value = true;
      return null;
    }
    try {
      const { data } = await api.get('/auth/me');
      user.value = data;
      initialized.value = true;
      return data;
    } catch {
      logout();
      return null;
    }
  }

  async function init(): Promise<AuthUser | null> {
    if (initialized.value) return user.value;
    await tokenReady;
    if (!token.value && getAuthToken()) {
      token.value = getAuthToken() || '';
    }
    if (!token.value) {
      // 本地单用户模式：后端 /auth/me 无 token 也返回本地用户（200），
      // 借此免登录直达工作台。
      try {
        const { data } = await api.get('/auth/me');
        const me = (data as AuthUser | null) ?? null;
        user.value = me;
        initialized.value = true;
        return me;
      } catch {
        // 探测失败（后端未就绪等）：静默维持未登录，不弹错误
        initialized.value = true;
        return null;
      }
    }
    return fetchMe();
  }

  function logout(): void {
    token.value = '';
    user.value = null;
    initialized.value = true;
    setAuthToken('');
  }

  function requireAuth(): boolean {
    return isLoggedIn.value;
  }

  function requireAiAccess(): boolean {
    return requireAuth();
  }

  return {
    token,
    user,
    initialized,
    isLoggedIn,
    isAuthor,
    init,
    fetchMe,
    logout,
    requireAuth,
    requireAiAccess,
  };
});
