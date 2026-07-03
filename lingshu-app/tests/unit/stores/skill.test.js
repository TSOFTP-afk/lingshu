import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useSkillStore } from '../../../src/stores/skill';

describe('useSkillStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 skills 为空数组', () => {
      const store = useSkillStore();
      expect(store.skills).toEqual([]);
    });
  });

  describe('方法存在性', () => {
    it('包含 fetchSkills 方法', () => {
      const store = useSkillStore();
      expect(typeof store.fetchSkills).toBe('function');
    });
  });

  describe('fetchSkills', () => {
    it('调用后 skills 仍为空数组（占位实现未填充数据）', async () => {
      const store = useSkillStore();
      await store.fetchSkills(1);
      expect(store.skills).toEqual([]);
    });

    it('返回值为 undefined（占位实现无返回值）', async () => {
      const store = useSkillStore();
      const result = await store.fetchSkills(1);
      expect(result).toBeUndefined();
    });

    it('可接受 bookId 参数且不抛错', async () => {
      const store = useSkillStore();
      await expect(store.fetchSkills(42)).resolves.toBeUndefined();
    });
  });
});
