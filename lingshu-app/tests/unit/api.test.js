import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ============================================================
//  Mocks — 必须在 import api.js 之前设置
// ============================================================

// Mock axios so we can inspect interceptors
const _requestInterceptors = [];
const _responseInterceptors = [];

vi.mock('axios', () => {
  const instance = {
    interceptors: {
      request: { use: vi.fn((fn) => { _requestInterceptors.push(fn); }) },
      response: { use: vi.fn((fulfilled, rejected) => { _responseInterceptors.push({ fulfilled, rejected }); }) },
    },
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  };
  return {
    default: {
      create: vi.fn(() => instance),
    },
  };
});

// Helper: reset interceptor arrays per test
function resetInterceptors() {
  _requestInterceptors.length = 0;
  _responseInterceptors.length = 0;
}

// ============================================================
//  Tests
// ============================================================

describe('api.js', () => {
  let apiModule;
  let originalLingshu;

  beforeEach(async () => {
    // Reset all mocks
    vi.restoreAllMocks();
    resetInterceptors();

    // Save & clear Electron bridge
    originalLingshu = window.lingshu;
    delete window.lingshu;

    // Reset localStorage
    localStorage.clear();
    vi.clearAllMocks();

    // Clear document.dispatchEvent mock
    if (document.dispatchEvent && vi.isMockFunction(document.dispatchEvent)) {
      document.dispatchEvent.mockClear();
    }

    // Remove cached module so each test gets a fresh import
    vi.resetModules();

    // Re-import module fresh
    apiModule = await import('../../src/utils/api.js');
  });

  afterEach(() => {
    // Restore Electron bridge
    if (originalLingshu !== undefined) {
      window.lingshu = originalLingshu;
    } else {
      delete window.lingshu;
    }
  });

  // ----------------------------------------------------------
  //  1. API_BASE_URL & WS_BASE_URL defaults
  // ----------------------------------------------------------
  describe('API_BASE_URL and WS_BASE_URL', () => {
    // 现行为：无 env / electron 桥时回退到 same-origin（由 vite dev proxy 转发到后端）
    it('should have default API_BASE_URL when no env or electron bridge', () => {
      expect(apiModule.API_BASE_URL).toBe(`${location.origin}/api`);
    });

    it('should have default WS_BASE_URL when no env or electron bridge', () => {
      expect(apiModule.WS_BASE_URL).toBe(`ws://${location.host}/ws`);
    });
  });

  // ----------------------------------------------------------
  //  2. getAuthToken()
  // ----------------------------------------------------------
  describe('getAuthToken()', () => {
    it('returns empty string when no token is stored', () => {
      expect(apiModule.getAuthToken()).toBe('');
    });

    it('ignores plaintext localStorage tokens when no memory token', () => {
      localStorage.setItem('lingshu_token', 'local-token');
      expect(apiModule.getAuthToken()).toBe('');
    });

    it('prefers memory token over localStorage', () => {
      apiModule.setAuthToken('memory-token');
      localStorage.setItem('lingshu_token', 'local-token');
      expect(apiModule.getAuthToken()).toBe('memory-token');
    });
  });

  // ----------------------------------------------------------
  //  3. setAuthToken(token)
  // ----------------------------------------------------------
  describe('setAuthToken(token)', () => {
    it('sets memory token without saving plaintext localStorage in non-Electron environment', () => {
      apiModule.setAuthToken('my-token');
      expect(apiModule.getAuthToken()).toBe('my-token');
      expect(localStorage.setItem).not.toHaveBeenCalledWith('lingshu_token', 'my-token');
    });

    it('clears all storage when token is empty string', () => {
      apiModule.setAuthToken('existing-token');
      apiModule.setAuthToken('');
      expect(apiModule.getAuthToken()).toBe('');
      expect(localStorage.removeItem).toHaveBeenCalledWith('lingshu_token');
      expect(localStorage.removeItem).toHaveBeenCalledWith('lingshu_token_encrypted');
    });

    it('clears all storage when token is null/undefined', () => {
      apiModule.setAuthToken('existing-token');
      apiModule.setAuthToken(null);
      expect(apiModule.getAuthToken()).toBe('');
    });

    it('in Electron environment, calls protectSecret instead of localStorage', async () => {
      const protectSecret = vi.fn().mockResolvedValue('encrypted-value');
      window.lingshu = { protectSecret };

      // Reset modules so the next import picks up window.lingshu
      vi.resetModules();
      resetInterceptors();
      const mod = await import('../../src/utils/api.js');
      mod.setAuthToken('electron-token');
      expect(protectSecret).toHaveBeenCalledWith('electron-token');
      // Should NOT save plaintext to localStorage
      expect(localStorage.setItem).not.toHaveBeenCalledWith('lingshu_token', 'electron-token');

      // Clean up
      delete window.lingshu;
    });
  });

  // ----------------------------------------------------------
  //  4. Request interceptor — Authorization header
  // ----------------------------------------------------------
  describe('request interceptor', () => {
    it('adds Authorization header when token exists', async () => {
      apiModule.setAuthToken('test-token');
      const config = { headers: {} };
      const result = await _requestInterceptors[0](config);
      expect(result.headers.Authorization).toBe('Bearer test-token');
    });

    it('does not add Authorization header when no token', async () => {
      apiModule.setAuthToken('');
      const config = { headers: {} };
      const result = await _requestInterceptors[0](config);
      expect(result.headers.Authorization).toBeUndefined();
    });

    it('returns the config object', async () => {
      const config = { headers: {} };
      const result = await _requestInterceptors[0](config);
      expect(result).toBe(config);
    });
  });

  // ----------------------------------------------------------
  //  5. Response interceptor — 401 handling
  // ----------------------------------------------------------
  describe('response interceptor', () => {
    let rejectedHandler;

    beforeEach(() => {
      // The rejected handler is the second argument of response.use()
      const interceptor = _responseInterceptors.find((i) => i.rejected);
      rejectedHandler = interceptor?.rejected;
      expect(rejectedHandler).toBeDefined();

      // Clear event spies
      window.dispatchEvent = vi.fn();
      document.dispatchEvent = vi.fn();
    });

    it('clears token storage on 401', async () => {
      apiModule.setAuthToken('will-be-cleared');
      const error = {
        response: { status: 401 },
        config: { url: '/some/protected' },
      };
      await expect(rejectedHandler(error)).rejects.toBe(error);
      expect(apiModule.getAuthToken()).toBe('');
    });

    it('clears token storage on 401 even for auth endpoint errors', async () => {
      apiModule.setAuthToken('stale-token');
      const error = {
        response: { status: 401 },
        config: { url: '/auth/login' },
      };
      await expect(rejectedHandler(error)).rejects.toBe(error);
      expect(apiModule.getAuthToken()).toBe('');
    });

    it('keeps token storage for non-401 errors', async () => {
      apiModule.setAuthToken('keep-me');
      const error = {
        response: { status: 500 },
        config: { url: '/some/endpoint' },
      };
      await expect(rejectedHandler(error)).rejects.toBe(error);
      expect(apiModule.getAuthToken()).toBe('keep-me');
    });

    it('rejects the promise with the original error', async () => {
      const error = {
        response: { status: 401 },
        config: { url: '/test' },
      };
      await expect(rejectedHandler(error)).rejects.toBe(error);
    });

    it('handles 401 with missing config gracefully', async () => {
      const error = {
        response: { status: 401 },
        config: undefined,
      };
      // Should not throw
      await expect(rejectedHandler(error)).rejects.toBe(error);
    });
  });

  // ----------------------------------------------------------
  //  6. buildWsUrl(path)
  // ----------------------------------------------------------
  describe('buildWsUrl(path)', () => {
    it('accepts absolute ws:// URLs from the configured origin', () => {
      expect(apiModule.buildWsUrl(`ws://${location.host}/ws/socket`)).toBe(`ws://${location.host}/ws/socket`);
    });

    it('rejects absolute WebSocket URLs from other origins', () => {
      expect(() => apiModule.buildWsUrl('ws://example.com/ws/socket')).toThrow(/origin is not allowed/);
    });

    it('rejects non-WebSocket absolute URLs', () => {
      expect(() => apiModule.buildWsUrl('https://127.0.0.1:8787/ws/socket')).toThrow(/must be a \/ws path/);
    });

    it('rejects WebSocket URLs with credentials', () => {
      expect(() => apiModule.buildWsUrl('ws://user:pass@127.0.0.1:8787/ws/socket')).toThrow(/credentials/);
    });

    it('rejects WebSocket URLs outside /ws', () => {
      expect(() => apiModule.buildWsUrl('ws://127.0.0.1:8787/socket')).toThrow(/path must start/);
    });

    it('prepends WS_BASE_URL when path is relative', () => {
      expect(apiModule.buildWsUrl('/chat')).toBe(`ws://${location.host}/ws/chat`);
    });

    it('normalizes relative path without leading slash', () => {
      expect(apiModule.buildWsUrl('chat')).toBe(`ws://${location.host}/ws/chat`);
    });

    it('does not duplicate /ws when path already includes it', () => {
      expect(apiModule.buildWsUrl('/ws/chat')).toBe(`ws://${location.host}/ws/chat`);
    });
  });

  // ----------------------------------------------------------
  //  7. sendWsAuth(ws)
  // ----------------------------------------------------------
  describe('sendWsAuth(ws)', () => {
    it('sends auth message with token on WebSocket', () => {
      apiModule.setAuthToken('ws-token');
      const ws = { send: vi.fn() };
      const returnedToken = apiModule.sendWsAuth(ws);
      expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: 'auth', payload: { token: 'ws-token' } }));
      expect(returnedToken).toBe('ws-token');
    });

    it('sends auth message with empty token when not authenticated', () => {
      apiModule.setAuthToken('');
      const ws = { send: vi.fn() };
      const returnedToken = apiModule.sendWsAuth(ws);
      expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: 'auth', payload: { token: '' } }));
      expect(returnedToken).toBe('');
    });
  });
});
