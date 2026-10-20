import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useAuthStore } from '../../../src/stores/auth';

vi.mock('../../../src/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  getAuthToken: vi.fn(() => ''),
  setAuthToken: vi.fn(),
  buildWsUrl: vi.fn(),
  sendWsAuth: vi.fn(),
  // auth store init() 会等待 token 就绪 Promise
  tokenReady: Promise.resolve(),
}));

import api, { getAuthToken, setAuthToken } from '../../../src/utils/api';

describe('useAuthStore（本地单用户模式）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    getAuthToken.mockReturnValue('');
  });

  describe('初始状态', () => {
    it('初始时 token 为空，user 为 null，未登录', () => {
      const store = useAuthStore();
      expect(store.token).toBe('');
      expect(store.user).toBeNull();
      expect(store.isLoggedIn).toBe(false);
      expect(store.initialized).toBe(false);
    });

    it('isAuthor 在 user 为 null 时为 false', () => {
      const store = useAuthStore();
      expect(store.isAuthor).toBe(false);
    });
  });

  describe('isLoggedIn 语义（本地模式 init 即登录）', () => {
    it('无 token 但 init 探测到本地用户时视为已登录', async () => {
      const localUser = { id: 1, username: 'local', is_author: 1 };
      api.get.mockResolvedValue({ data: localUser });

      const store = useAuthStore();
      expect(store.isLoggedIn).toBe(false);

      await store.init();

      expect(store.user).toEqual(localUser);
      expect(store.isLoggedIn).toBe(true);
    });

    it('init 探测失败（后端未就绪）时维持未登录', async () => {
      api.get.mockRejectedValue(new Error('network down'));

      const store = useAuthStore();
      const result = await store.init();

      expect(result).toBeNull();
      expect(store.user).toBeNull();
      expect(store.isLoggedIn).toBe(false);
      expect(store.initialized).toBe(true);
    });
  });

  describe('logout', () => {
    it('登出时清除所有状态', () => {
      const store = useAuthStore();
      store.token = 'token';
      store.user = { id: 1, username: 'test' };

      store.logout();

      expect(store.token).toBe('');
      expect(store.user).toBeNull();
      expect(store.initialized).toBe(true);
      expect(store.isLoggedIn).toBe(false);
      expect(setAuthToken).toHaveBeenCalledWith('');
    });
  });

  describe('fetchMe', () => {
    it('无 token 时直接返回 null 并标记 initialized', async () => {
      const store = useAuthStore();
      const result = await store.fetchMe();

      expect(result).toBeNull();
      expect(store.initialized).toBe(true);
      expect(api.get).not.toHaveBeenCalled();
    });

    it('有 token 时请求 /auth/me 并设置 user', async () => {
      getAuthToken.mockReturnValue('valid-token');
      const userData = { id: 1, username: 'test', is_author: 1 };

      // 需要重新创建 store 以使用 mock token
      setActivePinia(createPinia());
      const store = useAuthStore();
      store.token = 'valid-token';

      api.get.mockResolvedValue({ data: userData });

      const result = await store.fetchMe();

      expect(api.get).toHaveBeenCalledWith('/auth/me');
      expect(store.user).toEqual(userData);
      expect(store.isLoggedIn).toBe(true);
      expect(result).toEqual(userData);
    });

    it('fetchMe 失败时调用 logout', async () => {
      const store = useAuthStore();
      store.token = 'bad-token';

      api.get.mockRejectedValue(new Error('Unauthorized'));

      const result = await store.fetchMe();

      expect(result).toBeNull();
      expect(store.token).toBe('');
      expect(store.user).toBeNull();
      expect(store.isLoggedIn).toBe(false);
    });
  });

  describe('init', () => {
    it('已初始化时直接返回 user', async () => {
      const store = useAuthStore();
      store.initialized = true;
      store.user = { id: 1, username: 'test' };

      const result = await store.init();

      expect(result).toEqual({ id: 1, username: 'test' });
      expect(api.get).not.toHaveBeenCalled();
    });

    it('未初始化且无 token 时探测 /auth/me（本地模式入口）', async () => {
      const store = useAuthStore();
      await store.init();

      expect(api.get).toHaveBeenCalledWith('/auth/me');
      expect(store.initialized).toBe(true);
    });

    it('未初始化且有 token 时调用 fetchMe', async () => {
      const store = useAuthStore();
      store.token = 'valid-token';
      api.get.mockResolvedValue({ data: { id: 1, username: 'test' } });

      await store.init();

      expect(api.get).toHaveBeenCalledWith('/auth/me');
    });
  });

  describe('requireAuth', () => {
    it('已登录时返回 true', () => {
      const store = useAuthStore();
      store.token = 'valid-token';

      expect(store.requireAuth()).toBe(true);
    });

    it('未登录时返回 false（本地模式无登录框）', () => {
      const store = useAuthStore();
      store.token = '';
      store.user = null;

      expect(store.requireAuth()).toBe(false);
    });
  });

  describe('requireAiAccess', () => {
    it('委托给 requireAuth', () => {
      const store = useAuthStore();
      store.token = 'valid-token';
      expect(store.requireAiAccess()).toBe(true);

      store.token = '';
      store.user = null;
      expect(store.requireAiAccess()).toBe(false);
    });
  });

  describe('isAuthor', () => {
    it('user.is_author 为 1 时返回 true', () => {
      const store = useAuthStore();
      store.user = { id: 1, is_author: 1 };
      expect(store.isAuthor).toBe(true);
    });

    it('user.is_author 不为 1 时返回 false', () => {
      const store = useAuthStore();
      store.user = { id: 1, is_author: 0 };
      expect(store.isAuthor).toBe(false);
    });
  });
});
