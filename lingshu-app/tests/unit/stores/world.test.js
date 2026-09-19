import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useWorldStore } from '../../../src/stores/world';

vi.mock('../../../src/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from '../../../src/utils/api';

describe('useWorldStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 worldData 为空对象', () => {
      const store = useWorldStore();
      expect(store.worldData).toEqual({});
    });
  });

  describe('方法存在性', () => {
    it('包含 fetchWorld 方法', () => {
      const store = useWorldStore();
      expect(typeof store.fetchWorld).toBe('function');
    });
  });

  describe('fetchWorld', () => {
    it('调用后 worldData 填充为接口返回数据', async () => {
      api.get.mockResolvedValue({
        data: { world_text: '文本', world_data: { factions: [] }, world_schema: [] },
      });

      const store = useWorldStore();
      await store.fetchWorld(1);

      expect(api.get).toHaveBeenCalledWith('/workspace/books/1/world');
      expect(store.worldData).toEqual({ factions: [] });
    });

    it('接口失败时 worldData 重置为空对象', async () => {
      api.get.mockRejectedValue(new Error('Network Error'));

      const store = useWorldStore();
      await store.fetchWorld(1);

      expect(store.worldData).toEqual({});
    });

    it('返回值为 undefined（无返回值）', async () => {
      api.get.mockResolvedValue({ data: {} });

      const store = useWorldStore();
      const result = await store.fetchWorld(1);
      expect(result).toBeUndefined();
    });

    it('可接受 bookId 参数且不抛错', async () => {
      api.get.mockResolvedValue({ data: {} });

      const store = useWorldStore();
      await expect(store.fetchWorld(42)).resolves.toBeUndefined();
    });
  });
});
