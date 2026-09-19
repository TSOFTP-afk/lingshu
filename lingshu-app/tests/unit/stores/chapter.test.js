import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useChapterStore } from '../../../src/stores/chapter';

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
}));

import api from '../../../src/utils/api';

describe('useChapterStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 chapters 为空数组，currentChapter 为 null', () => {
      const store = useChapterStore();
      expect(store.chapters).toEqual([]);
      expect(store.currentChapter).toBeNull();
      expect(store.loading).toBe(false);
      expect(store.saving).toBe(false);
    });
  });

  describe('fetchChapters', () => {
    it('成功获取章节列表', async () => {
      const mockChapters = [
        { id: 1, title: '第一章' },
        { id: 2, title: '第二章' },
      ];
      api.get.mockResolvedValue({ data: { items: mockChapters } });

      const store = useChapterStore();
      await store.fetchChapters(1);

      expect(api.get).toHaveBeenCalledWith('/workspace/books/1/chapters');
      expect(store.chapters).toEqual(mockChapters);
      expect(store.loading).toBe(false);
    });

    it('API 返回无 items 时设为空数组', async () => {
      api.get.mockResolvedValue({ data: {} });

      const store = useChapterStore();
      await store.fetchChapters(1);

      expect(store.chapters).toEqual([]);
    });

    it('请求失败时 loading 仍恢复为 false', async () => {
      api.get.mockRejectedValue(new Error('Network Error'));

      const store = useChapterStore();
      await expect(store.fetchChapters(1)).rejects.toThrow();

      expect(store.loading).toBe(false);
    });
  });

  describe('fetchChapter', () => {
    it('成功获取单个章节', async () => {
      const mockChapter = { id: 1, title: '第一章', content: '内容' };
      api.get.mockResolvedValue({ data: mockChapter });

      const store = useChapterStore();
      const result = await store.fetchChapter(1);

      expect(api.get).toHaveBeenCalledWith('/workspace/chapters/1');
      expect(store.currentChapter).toEqual(mockChapter);
      expect(result).toEqual(mockChapter);
    });
  });

  describe('createChapter', () => {
    it('在书籍下创建章节（无 volumeId）', async () => {
      const newChapter = { id: 1, title: '新章节' };
      api.post.mockResolvedValue({ data: { item: newChapter } });

      const store = useChapterStore();
      const result = await store.createChapter(1, '新章节');

      expect(api.post).toHaveBeenCalledWith('/workspace/books/1/chapters', {
        title: '新章节',
      });
      expect(store.chapters).toContainEqual(newChapter);
      expect(result).toEqual(newChapter);
    });

    it('在分卷下创建章节（有 volumeId）', async () => {
      const newChapter = { id: 2, title: '新章节' };
      api.post.mockResolvedValue({ data: { item: newChapter } });

      const store = useChapterStore();
      const result = await store.createChapter(1, '新章节', 10);

      expect(api.post).toHaveBeenCalledWith('/workspace/volumes/10/chapters', {
        title: '新章节',
      });
      expect(result).toEqual(newChapter);
    });

    it('API 返回无 item 时使用 data 本身', async () => {
      const newChapter = { id: 3, title: '新章节' };
      api.post.mockResolvedValue({ data: newChapter });

      const store = useChapterStore();
      const result = await store.createChapter(1, '新章节');

      expect(result).toEqual(newChapter);
      expect(store.chapters).toContainEqual(newChapter);
    });
  });

  describe('saveChapter', () => {
    it('成功保存章节', async () => {
      const savedChapter = { id: 1, title: '第一章', content: '保存的内容' };
      api.patch.mockResolvedValue({ data: { item: savedChapter } });

      const store = useChapterStore();
      const result = await store.saveChapter(1, { content: '保存的内容' });

      expect(api.patch).toHaveBeenCalledWith('/workspace/chapters/1', { content: '保存的内容' });
      expect(store.currentChapter).toEqual(savedChapter);
      expect(store.saving).toBe(false);
      expect(result).toEqual({ item: savedChapter });
    });

    it('保存失败时 saving 仍恢复为 false', async () => {
      api.patch.mockRejectedValue(new Error('Save failed'));

      const store = useChapterStore();
      await expect(store.saveChapter(1, { content: '内容' })).rejects.toThrow();

      expect(store.saving).toBe(false);
    });
  });

  describe('deleteChapter', () => {
    it('成功删除章节', async () => {
      api.delete.mockResolvedValue({ data: {} });

      const store = useChapterStore();
      store.chapters = [{ id: 1, title: '第一章' }, { id: 2, title: '第二章' }];

      await store.deleteChapter(1);

      expect(api.delete).toHaveBeenCalledWith('/workspace/chapters/1');
      expect(store.chapters).toEqual([{ id: 2, title: '第二章' }]);
    });
  });
});
