import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useWsStore } from '../../../src/stores/websocket';

vi.mock('../../../src/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  getAuthToken: vi.fn(() => 'test-token'),
  setAuthToken: vi.fn(),
  buildWsUrl: vi.fn((path) => `ws://localhost:8787/ws${path}`),
  // store 会在 onopen 后检查 sendWsAuth 返回的 token，为空则视为未认证并主动关闭
  sendWsAuth: vi.fn(() => 'test-token'),
}));

import { buildWsUrl, sendWsAuth } from '../../../src/utils/api';

// Mock WebSocket
class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static CONNECTING = 0;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    this._setIntentionalClose = null;
    this.sentMessages = [];

    // 模拟异步连接
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) this.onopen();
    }, 0);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose();
  }

  send(data) {
    this.sentMessages.push(data);
  }

  // 测试辅助方法
  simulateError() {
    if (this.onerror) this.onerror(new Event('error'));
  }

  simulateClose() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose();
  }
}

describe('useWsStore', () => {
  let originalWebSocket;

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    originalWebSocket = global.WebSocket;
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
  });

  describe('初始状态', () => {
    it('初始时 connections 和 status 为空', () => {
      const store = useWsStore();
      expect(store.connections).toEqual({});
      expect(store.status).toEqual({});
    });
  });

  describe('connect', () => {
    it('创建 WebSocket 连接', async () => {
      const store = useWsStore();
      const ws = store.connect('/chat');

      expect(buildWsUrl).toHaveBeenCalledWith('/chat');
      expect(ws).toBeTruthy();
      expect(store.status['/chat']).toBe('connecting');
    });

    it('连接成功后状态变为 connected 并发送认证', async () => {
      const store = useWsStore();
      const ws = store.connect('/chat');

      // 等待 onopen 触发
      await vi.waitFor(() => {
        expect(store.status['/chat']).toBe('connected');
      });

      expect(sendWsAuth).toHaveBeenCalledWith(ws);
    });

    it('重复连接同一 URL 返回已有连接', () => {
      const store = useWsStore();
      const ws1 = store.connect('/chat');
      const ws2 = store.connect('/chat');

      // reactive 代理对象用 toStrictEqual 比较
      expect(ws2).toStrictEqual(ws1);
    });

    it('连接关闭后自动重连（非主动关闭）', async () => {
      vi.useFakeTimers();
      const store = useWsStore();
      const ws = store.connect('/chat');

      // 等待连接建立
      await vi.waitFor(() => {
        expect(store.status['/chat']).toBe('connected');
      });

      // 模拟非主动关闭
      ws.simulateClose();
      expect(store.status['/chat']).toBe('disconnected');

      // 推进时间触发重连
      vi.advanceTimersByTime(6000);

      // 应该已重新连接
      expect(buildWsUrl).toHaveBeenCalledTimes(2);

      vi.useRealTimers();
    });

    it('主动关闭后不重连', async () => {
      const store = useWsStore();
      const ws = store.connect('/chat');

      await vi.waitFor(() => {
        expect(store.status['/chat']).toBe('connected');
      });

      // 主动关闭
      store.disconnect('/chat');
      expect(store.status['/chat']).toBe('disconnected');

      // 不应重连
      const callCount = buildWsUrl.mock.calls.length;
      expect(buildWsUrl).toHaveBeenCalledTimes(callCount);
    });

    it('连接错误时状态变为 error', () => {
      const store = useWsStore();
      const ws = store.connect('/chat');

      ws.simulateError();

      expect(store.status['/chat']).toBe('error');
    });
  });

  describe('disconnect', () => {
    it('断开指定连接', async () => {
      const store = useWsStore();
      const ws = store.connect('/chat');

      await vi.waitFor(() => {
        expect(store.status['/chat']).toBe('connected');
      });

      store.disconnect('/chat');

      expect(store.connections['/chat']).toBeUndefined();
    });

    it('断开不存在的连接无操作', () => {
      const store = useWsStore();
      store.disconnect('/nonexistent'); // 不应抛错
    });
  });

  describe('send', () => {
    it('连接打开时发送消息', async () => {
      const store = useWsStore();
      const ws = store.connect('/chat');

      await vi.waitFor(() => {
        expect(store.status['/chat']).toBe('connected');
      });

      const message = { type: 'chat', content: 'hello' };
      store.send('/chat', message);

      expect(ws.sentMessages).toContain(JSON.stringify(message));
    });

    it('连接未打开时不发送', () => {
      const store = useWsStore();
      // 不建立连接直接发送
      store.send('/chat', { type: 'chat' });
      // 不应抛错
    });

    it('连接关闭时不发送', async () => {
      const store = useWsStore();
      const ws = store.connect('/chat');

      await vi.waitFor(() => {
        expect(store.status['/chat']).toBe('connected');
      });

      ws.readyState = MockWebSocket.CLOSED;
      ws.sentMessages = [];

      store.send('/chat', { type: 'chat' });

      expect(ws.sentMessages).toHaveLength(0);
    });
  });

  describe('disconnectAll', () => {
    it('断开所有连接', async () => {
      const store = useWsStore();
      store.connect('/chat1');
      store.connect('/chat2');

      await vi.waitFor(() => {
        expect(store.status['/chat1']).toBe('connected');
        expect(store.status['/chat2']).toBe('connected');
      });

      store.disconnectAll();

      expect(Object.keys(store.connections)).toHaveLength(0);
    });
  });
});
