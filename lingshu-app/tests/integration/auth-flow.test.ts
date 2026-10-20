/**
 * 集成测试 — 本地单用户模式认证流程
 *
 * 测试链路：init 探测 /auth/me → 本地用户直接进入登录态 → 权限校验 → token 恢复 → 失效登出
 * 使用真实 Pinia store（auth），仅 mock API 层。
 * 登录/注册/云端同步流程已随多用户产品形态移除。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useAuthStore } from '../../src/stores/auth';

vi.mock('../../src/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    put: vi.fn(),
  },
  getAuthToken: vi.fn(() => ''),
  setAuthToken: vi.fn(),
  tokenReady: Promise.resolve(),
  buildWsUrl: vi.fn(),
  sendWsAuth: vi.fn(),
  API_BASE_URL: '/api',
  WS_BASE_URL: '/ws',
}));

import api, { setAuthToken } from '../../src/utils/api';

const LOCAL_USER = { id: 1, username: 'local', is_author: 1, bind_reader_id: null, bind_reader_name: null };

describe('本地模式认证流程集成测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('本地模式进入流程', () => {
    it('init 无 token 探测 /auth/me 命中本地用户 → 直接进入登录态', async () => {
      api.get.mockResolvedValueOnce({ data: LOCAL_USER });

      const authStore = useAuthStore();

      // 1. 初始状态：未登录、未初始化
      expect(authStore.isLoggedIn).toBe(false);
      expect(authStore.initialized).toBe(false);

      // 2. init 探测
      const result = await authStore.init();

      expect(api.get).toHaveBeenCalledWith('/auth/me');
      expect(result).toEqual(LOCAL_USER);
      expect(authStore.user).toEqual(LOCAL_USER);

      // 3. 本地模式 init 即登录
      expect(authStore.isLoggedIn).toBe(true);
      expect(authStore.isAuthor).toBe(true);

      // 4. 权限校验通过
      expect(authStore.requireAuth()).toBe(true);
      expect(authStore.requireAiAccess()).toBe(true);
    });

    it('init 探测失败时维持未登录，权限校验不通过', async () => {
      api.get.mockRejectedValueOnce(new Error('backend not ready'));

      const authStore = useAuthStore();
      const result = await authStore.init();

      expect(result).toBeNull();
      expect(authStore.isLoggedIn).toBe(false);
      expect(authStore.requireAiAccess()).toBe(false);
    });
  });

  describe('token 恢复流程', () => {
    it('init 时从安全存储恢复 token 并获取用户信息', async () => {
      const userData = { id: 7, username: 'returning_user', is_author: 0 };

      const authStore = useAuthStore();
      authStore.token = 'restored-token';
      api.get.mockResolvedValue({ data: userData });

      const result = await authStore.init();

      expect(api.get).toHaveBeenCalledWith('/auth/me');
      expect(authStore.initialized).toBe(true);
      expect(authStore.user).toEqual(userData);
      expect(authStore.isLoggedIn).toBe(true);
      expect(result).toEqual(userData);
    });

    it('fetchMe 失效（401）时自动登出并清除会话', async () => {
      const authStore = useAuthStore();
      authStore.token = 'expired-token';

      api.get.mockRejectedValue({
        response: { status: 401, data: { detail: 'Token expired' } },
      });

      const result = await authStore.fetchMe();

      expect(result).toBeNull();
      expect(authStore.isLoggedIn).toBe(false);
      expect(authStore.token).toBe('');
      expect(authStore.user).toBeNull();
      expect(setAuthToken).toHaveBeenCalledWith('');
    });
  });
});
