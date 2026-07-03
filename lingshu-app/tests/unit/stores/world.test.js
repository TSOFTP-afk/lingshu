import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useWorldStore } from '../../../src/stores/world';

describe('useWorldStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 worldData 为 null', () => {
      const store = useWorldStore();
      expect(store.worldData).toBeNull();
    });
  });

  describe('方法存在性', () => {
    it('包含 fetchWorld 方法', () => {
      const store = useWorldStore();
      expect(typeof store.fetchWorld).toBe('function');
    });
  });

  describe('fetchWorld', () => {
    it('调用后 worldData 仍为 null（占位实现未填充数据）', async () => {
      const store = useWorldStore();
      await store.fetchWorld(1);
      expect(store.worldData).toBeNull();
    });

    it('返回值为 undefined（占位实现无返回值）', async () => {
      const store = useWorldStore();
      const result = await store.fetchWorld(1);
      expect(result).toBeUndefined();
    });

    it('可接受 bookId 参数且不抛错', async () => {
      const store = useWorldStore();
      await expect(store.fetchWorld(42)).resolves.toBeUndefined();
    });
  });
});
