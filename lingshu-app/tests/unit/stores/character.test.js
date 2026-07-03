import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useCharacterStore } from '../../../src/stores/character';

describe('useCharacterStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 characters 为空数组，loading 为 false', () => {
      const store = useCharacterStore();
      expect(store.characters).toEqual([]);
      expect(store.loading).toBe(false);
    });
  });

  describe('方法存在性', () => {
    it('包含 fetchCharacters 方法', () => {
      const store = useCharacterStore();
      expect(typeof store.fetchCharacters).toBe('function');
    });
  });

  describe('fetchCharacters', () => {
    it('调用后 characters 被清空为空数组', async () => {
      const store = useCharacterStore();
      store.characters = [{ id: 1, name: '角色1' }];

      await store.fetchCharacters(1);

      expect(store.characters).toEqual([]);
    });

    it('返回值为 undefined（占位实现无返回值）', async () => {
      const store = useCharacterStore();
      const result = await store.fetchCharacters(1);
      expect(result).toBeUndefined();
    });

    it('调用后 loading 状态不变', async () => {
      const store = useCharacterStore();
      expect(store.loading).toBe(false);
      await store.fetchCharacters(1);
      expect(store.loading).toBe(false);
    });

    it('可接受 bookId 参数且不抛错', async () => {
      const store = useCharacterStore();
      await expect(store.fetchCharacters(42)).resolves.toBeUndefined();
    });
  });
});
