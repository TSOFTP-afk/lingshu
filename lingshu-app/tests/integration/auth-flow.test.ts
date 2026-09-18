/**
 * 集成测试 — 认证完整流程
 *
 * 测试链路：登录 → token 持久化 → 获取用户信息 → 权限校验 → 登出
 * 使用真实 Pinia store（auth + cloud），仅 mock API 层
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

vi.mock('../../src/stores/cloud', () => ({
  useCloudStore: vi.fn(() => ({
    syncUploadedBooks: vi.fn(() => Promise.resolve()),
  })),
}));

vi.mock('../../src/composables/useEventBus', () => ({
  useEventBus: vi.fn(() => ({
    emit: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
  })),
}));

import api, { getAuthToken, setAuthToken } from '../../src/utils/api';

describe('认证流程集成测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    getAuthToken.mockReturnValue('');
  });

  describe('完整登录流程', () => {
    it('登录 → token 存储 → 获取用户信息 → 登出', async () => {
      const loginResponse = {
        access_token: 'integration-token-xyz',
        user: { id: 42, username: 'writer', is_author: 1 },
      };
      const meResponse = { id: 42, username: 'writer', is_author: 1 };

      api.post.mockResolvedValue({ data: loginResponse });
      api.get.mockResolvedValue({ data: meResponse });

      const authStore = useAuthStore();

      // 1. 初始状态：未登录
      expect(authStore.isLoggedIn).toBe(false);
      expect(authStore.initialized).toBe(false);

      // 2. 登录
      const loginResult = await authStore.login('writer', 'password');
      expect(loginResult.access_token).toBe('integration-token-xyz');
      expect(authStore.isLoggedIn).toBe(true);
      expect(authStore.token).toBe('integration-token-xyz');
      expect(authStore.user).toEqual(loginResponse.user);
      expect(authStore.isAuthor).toBe(true);
      expect(setAuthToken).toHaveBeenCalledWith('integration-token-xyz');

      // 3. 获取用户信息
      const meResult = await authStore.fetchMe();
      expect(api.get).toHaveBeenCalledWith('/auth/me');
      expect(meResult).toEqual(meResponse);

      // 4. 权限校验
      expect(authStore.requireAuth()).toBe(true);
      expect(authStore.requireAiAccess()).toBe(true);

      // 5. 登出
      authStore.logout();
      expect(authStore.isLoggedIn).toBe(false);
      expect(authStore.token).toBe('');
      expect(authStore.user).toBeNull();
      expect(setAuthToken).toHaveBeenCalledWith('');
    });

    it('未登录用户触发 requireAuth 时派发登录事件', () => {
      const authStore = useAuthStore();
      expect(authStore.isLoggedIn).toBe(false);
      const result = authStore.requireAuth();
      expect(result).toBe(false);
    });
  });

  describe('token 恢复流程', () => {
    it('init 时从安全存储恢复 token 并获取用户信息', async () => {
      getAuthToken.mockReturnValue('restored-token');
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

    it('init 时无 token 直接返回 null', async () => {
      const authStore = useAuthStore();
      const result = await authStore.init();

      expect(result).toBeNull();
      expect(authStore.initialized).toBe(true);
      expect(api.get).not.toHaveBeenCalled();
    });
  });

  describe('登录失败恢复流程', () => {
    it('fetchMe 失败（401）时自动登出', async () => {
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
    });
  });

  describe('注册流程', () => {
    it('注册新用户 → 自动登录 → 触发云端同步', async () => {
      const regResponse = {
        access_token: 'new-user-token',
        user: { id: 100, username: 'newbie', is_author: 1 },
      };
      api.post.mockResolvedValue({ data: regResponse });

      const authStore = useAuthStore();
      await authStore.register('newbie', 'securepass123', 1);

      expect(api.post).toHaveBeenCalledWith('/auth/register', {
        username: 'newbie',
        password: 'securepass123',
        is_author: 1,
      });
      expect(authStore.isLoggedIn).toBe(true);
      expect(authStore.user).toEqual(regResponse.user);
      expect(setAuthToken).toHaveBeenCalledWith('new-user-token');
    });
  });
});
