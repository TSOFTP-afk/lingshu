import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useBookStore } from '../../../src/stores/book';

vi.mock('../../../src/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    put: vi.fn(),
  },
  getAuthToken: vi.fn(() => ''),
  setAuthToken: vi.fn(),
  buildWsUrl: vi.fn(),
  sendWsAuth: vi.fn(),
}));

import api from '../../../src/utils/api';

describe('useBookStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 books 为空数组，currentBook 为 null', () => {
      const store = useBookStore();
      expect(store.books).toEqual([]);
      expect(store.currentBook).toBeNull();
      expect(store.currentBookId).toBeNull();
      expect(store.loading).toBe(false);
      expect(store.activeTabKey).toBeNull();
      expect(store.activeTab).toBeNull();
      expect(store.activeChapterId).toBeNull();
      expect(store.activeTabCount).toBe(0);
      expect(store.maxOpenChapterTabs).toBe(20);
    });
  });

  describe('fetchBooks', () => {
    it('成功获取书籍列表', async () => {
      const mockBooks = [
        { id: 1, title: '书1' },
        { id: 2, title: '书2' },
      ];
      api.get.mockResolvedValue({ data: { items: mockBooks } });

      const store = useBookStore();
      await store.fetchBooks();

      expect(api.get).toHaveBeenCalledWith('/workspace/books');
      expect(store.books).toEqual(mockBooks);
      expect(store.loading).toBe(false);
    });

    it('API 返回无 items 时设为空数组', async () => {
      api.get.mockResolvedValue({ data: {} });

      const store = useBookStore();
      await store.fetchBooks();

      expect(store.books).toEqual([]);
    });

    it('请求失败时 loading 仍恢复为 false', async () => {
      api.get.mockRejectedValue(new Error('Network Error'));

      const store = useBookStore();
      await expect(store.fetchBooks()).rejects.toThrow();

      expect(store.loading).toBe(false);
    });
  });

  describe('createBook', () => {
    it('成功创建书籍', async () => {
      const newBook = { id: 3, title: '新书' };
      api.post.mockResolvedValue({ data: { item: newBook } });
      api.get.mockResolvedValue({ data: { items: [newBook] } });

      const store = useBookStore();
      const result = await store.createBook('新书');

      expect(api.post).toHaveBeenCalledWith('/workspace/books', { title: '新书' });
      expect(store.currentBook).toEqual(newBook);
      expect(result).toEqual(newBook);
    });
  });

  describe('fetchBook', () => {
    it('成功获取单本书籍并更新列表', async () => {
      const bookData = { id: 1, title: '书1', volumes: [] };
      api.get.mockResolvedValue({ data: bookData });

      const store = useBookStore();
      const result = await store.fetchBook(1);

      expect(api.get).toHaveBeenCalledWith('/workspace/books/1');
      expect(store.currentBook).toEqual(bookData);
      expect(store.books).toContainEqual(bookData);
      expect(result).toEqual(bookData);
    });
  });

  describe('renameBook', () => {
    it('成功重命名书籍', async () => {
      api.patch.mockResolvedValue({ data: {} });

      const store = useBookStore();
      store.currentBook = { id: 1, title: '旧名' };
      store.books = [{ id: 1, title: '旧名' }];

      await store.renameBook(1, '新名');

      expect(api.patch).toHaveBeenCalledWith('/workspace/books/1', { title: '新名' });
      expect(store.currentBook.title).toBe('新名');
      expect(store.books[0].title).toBe('新名');
    });

    it('重命名非当前书籍时只更新列表', async () => {
      api.patch.mockResolvedValue({ data: {} });

      const store = useBookStore();
      store.currentBook = { id: 2, title: '其他书' };
      store.books = [{ id: 1, title: '旧名' }, { id: 2, title: '其他书' }];

      await store.renameBook(1, '新名');

      expect(store.currentBook.title).toBe('其他书');
      expect(store.books[0].title).toBe('新名');
    });
  });

  describe('deleteBook', () => {
    it('成功删除书籍', async () => {
      api.delete.mockResolvedValue({ data: {} });

      const store = useBookStore();
      store.books = [{ id: 1, title: '书1' }, { id: 2, title: '书2' }];
      store.currentBook = { id: 1, title: '书1' };

      await store.deleteBook(1);

      expect(api.delete).toHaveBeenCalledWith('/workspace/books/1');
      expect(store.books).toEqual([{ id: 2, title: '书2' }]);
      expect(store.currentBook).toBeNull();
    });

    it('删除非当前书籍时不清除 currentBook', async () => {
      api.delete.mockResolvedValue({ data: {} });

      const store = useBookStore();
      store.books = [{ id: 1, title: '书1' }, { id: 2, title: '书2' }];
      store.currentBook = { id: 2, title: '书2' };

      await store.deleteBook(1);

      expect(store.currentBook).toEqual({ id: 2, title: '书2' });
    });
  });

  describe('resetWorkspaceState', () => {
    it('重置所有工作台状态', () => {
      const store = useBookStore();
      store.books = [{ id: 1, title: '书1' }];
      store.currentBook = { id: 1, title: '书1' };
      store.loading = true;
      store.openLayerTab('chapter', 1, '章节1');

      store.resetWorkspaceState();

      expect(store.books).toEqual([]);
      expect(store.currentBook).toBeNull();
      expect(store.loading).toBe(false);
      expect(store.tabOrder).toEqual([]);
      expect(store.activeTabKey).toBeNull();
    });
  });

  describe('标签管理', () => {
    describe('makeLayerTabKey', () => {
      it('生成普通层级 key', () => {
        const store = useBookStore();
        expect(store.makeLayerTabKey('chapter', 1)).toBe('chapter:1');
        expect(store.makeLayerTabKey('book', 5)).toBe('book:5');
      });

      it('volume id 为 null 时生成 unassigned key', () => {
        const store = useBookStore();
        expect(store.makeLayerTabKey('volume', null, { bookId: 3 })).toBe('volume:unassigned:3');
      });

      it('volume id 为 undefined 时生成 unassigned key', () => {
        const store = useBookStore();
        expect(store.makeLayerTabKey('volume', undefined, { bookId: 3 })).toBe('volume:unassigned:3');
      });
    });

    describe('openLayerTab', () => {
      it('打开新标签', () => {
        const store = useBookStore();
        const tab = store.openLayerTab('chapter', 1, '章节1');

        expect(tab).toBeTruthy();
        expect(tab.key).toBe('chapter:1');
        expect(tab.kind).toBe('chapter');
        expect(tab.id).toBe(1);
        expect(tab.title).toBe('章节1');
        expect(tab.dirty).toBe(false);
        expect(tab.loaded).toBe(false); // chapter 类型 loaded 为 false
        expect(store.activeTabKey).toBe('chapter:1');
        expect(store.tabOrder).toContain('chapter:1');
      });

      it('打开已存在的标签时仅激活', () => {
        const store = useBookStore();
        const tab1 = store.openLayerTab('chapter', 1, '章节1');
        store.activeTabKey = 'other';

        const tab2 = store.openLayerTab('chapter', 1, '章节1');

        expect(tab2).toStrictEqual(tab1);
        expect(store.activeTabKey).toBe('chapter:1');
        expect(store.activeTabCount).toBe(1);
      });

      it('非 chapter 类型 loaded 为 true', () => {
        const store = useBookStore();
        const tab = store.openLayerTab('book', 1, '书1');

        expect(tab.loaded).toBe(true);
      });

      it('达到最大标签数时关闭非脏标签', () => {
        const store = useBookStore();

        // 打开 20 个标签
        for (let i = 1; i <= 20; i++) {
          store.openLayerTab('chapter', i, `章节${i}`);
        }
        expect(store.activeTabCount).toBe(20);

        // 打开第 21 个标签，应关闭一个非脏标签
        const tab = store.openLayerTab('chapter', 21, '章节21');
        expect(tab).toBeTruthy();
        expect(store.activeTabCount).toBe(20);
        expect(store.activeTabKey).toBe('chapter:21');
      });

      it('达到最大标签数且全部脏时返回 null', () => {
        const store = useBookStore();

        for (let i = 1; i <= 20; i++) {
          store.openLayerTab('chapter', i, `章节${i}`);
          store.markTabDirty(i);
        }

        const tab = store.openLayerTab('chapter', 21, '章节21');
        expect(tab).toBeNull();
      });
    });

    describe('activateLayerTab', () => {
      it('激活已存在的标签', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');
        store.openLayerTab('chapter', 2, '章节2');

        const tab = store.activateLayerTab('chapter:1');

        expect(store.activeTabKey).toBe('chapter:1');
        expect(tab.key).toBe('chapter:1');
      });

      it('激活不存在的标签返回 null', () => {
        const store = useBookStore();
        const result = store.activateLayerTab('chapter:999');
        expect(result).toBeNull();
      });
    });

    describe('closeLayerTab', () => {
      it('关闭标签并更新 tabOrder', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');
        store.openLayerTab('chapter', 2, '章节2');

        store.closeLayerTab('chapter:1');

        expect(store.activeTabCount).toBe(1);
        expect(store.openTabs['chapter:1']).toBeUndefined();
      });

      it('关闭当前激活标签时切换到上一个', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');
        store.openLayerTab('chapter', 2, '章节2');

        store.closeLayerTab('chapter:2');

        expect(store.activeTabKey).toBe('chapter:1');
      });

      it('关闭最后一个标签时 activeTabKey 为 null', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');

        store.closeLayerTab('chapter:1');

        expect(store.activeTabKey).toBeNull();
      });

      it('关闭不存在的标签无操作', () => {
        const store = useBookStore();
        store.closeLayerTab('chapter:999'); // 不应抛错
      });
    });

    describe('markTabDirty / markTabClean', () => {
      it('markTabDirty 标记标签为脏', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');

        store.markTabDirty(1);

        expect(store.getChapterTab(1).dirty).toBe(true);
      });

      it('markTabDirty 可传 false 取消脏标记', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');
        store.markTabDirty(1);

        store.markTabDirty(1, false);

        expect(store.getChapterTab(1).dirty).toBe(false);
      });

      it('markTabClean 清除脏标记并保存 savedContent', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');
        store.setTabContent(1, '内容');
        store.markTabDirty(1);

        store.markTabClean(1, '保存的内容');

        expect(store.getChapterTab(1).dirty).toBe(false);
        expect(store.getChapterTab(1).savedContent).toBe('保存的内容');
      });

      it('markTabClean 不传 savedContent 时使用当前 content', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');
        store.setTabContent(1, '当前内容');
        store.markTabDirty(1);

        store.markTabClean(1);

        expect(store.getChapterTab(1).dirty).toBe(false);
        expect(store.getChapterTab(1).savedContent).toBe('当前内容');
      });
    });

    describe('setTabContent', () => {
      it('设置标签内容', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');

        store.setTabContent(1, '章节内容');

        const tab = store.getChapterTab(1);
        expect(tab.content).toBe('章节内容');
        expect(tab.savedContent).toBe('章节内容');
        expect(tab.loaded).toBe(true);
        expect(tab.loading).toBe(false);
        expect(tab.error).toBeNull();
        expect(tab.dirty).toBe(false);
      });

      it('设置标签内容时可指定 dirty 和 savedContent', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');

        store.setTabContent(1, '新内容', { dirty: true, savedContent: '旧内容' });

        const tab = store.getChapterTab(1);
        expect(tab.content).toBe('新内容');
        expect(tab.savedContent).toBe('旧内容');
        expect(tab.dirty).toBe(true);
      });
    });

    describe('updateTabAiProbability', () => {
      it('更新标签 AI 概率', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');

        store.updateTabAiProbability(1, 75, 'high');

        const tab = store.getChapterTab(1);
        expect(tab.ai_probability).toBe(75);
        expect(tab.ai_probability_level).toBe('high');
      });

      it('概率值被限制在 0-100 范围', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');

        store.updateTabAiProbability(1, 150, 'high');
        expect(store.getChapterTab(1).ai_probability).toBe(100);

        store.updateTabAiProbability(1, -10, 'low');
        expect(store.getChapterTab(1).ai_probability).toBe(0);
      });

      it('无效概率值默认为 0', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');

        store.updateTabAiProbability(1, NaN, 'none');
        expect(store.getChapterTab(1).ai_probability).toBe(0);
      });
    });

    describe('openChapterTab / closeChapterTab / getChapterTab', () => {
      it('openChapterTab 是 openLayerTab 的快捷方式', () => {
        const store = useBookStore();
        const tab = store.openChapterTab(1, '章节1');

        expect(tab.key).toBe('chapter:1');
        expect(tab.kind).toBe('chapter');
      });

      it('closeChapterTab 关闭章节标签', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');

        store.closeChapterTab(1);

        expect(store.getChapterTab(1)).toBeNull();
      });

      it('getChapterTab 返回已打开的标签', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');

        const tab = store.getChapterTab(1);
        expect(tab).toBeTruthy();
        expect(tab.id).toBe(1);
      });

      it('getChapterTab 对不存在的标签返回 null', () => {
        const store = useBookStore();
        expect(store.getChapterTab(999)).toBeNull();
      });
    });

    describe('setTabLoading / setTabError / revertTabContent', () => {
      it('setTabLoading 设置加载状态', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');

        store.setTabLoading(1, true);

        expect(store.getChapterTab(1).loading).toBe(true);
        expect(store.getChapterTab(1).error).toBeNull();
      });

      it('setTabError 设置错误状态', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');

        store.setTabError(1, 'load_failed');

        expect(store.getChapterTab(1).loading).toBe(false);
        expect(store.getChapterTab(1).error).toBe('load_failed');
      });

      it('setTabError 无消息时默认为 load_failed', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');

        store.setTabError(1, '');

        expect(store.getChapterTab(1).error).toBe('load_failed');
      });

      it('revertTabContent 恢复到 savedContent', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');
        store.setTabContent(1, '原始内容');
        store.setTabContent(1, '修改内容', { dirty: true, savedContent: '原始内容' });

        store.revertTabContent(1);

        expect(store.getChapterTab(1).content).toBe('原始内容');
        expect(store.getChapterTab(1).dirty).toBe(false);
      });

      it('revertTabContent 无 savedContent 时使用空字符串', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');
        store.getChapterTab(1).content = '修改内容';
        store.getChapterTab(1).dirty = true;
        store.getChapterTab(1).savedContent = null;

        store.revertTabContent(1);

        expect(store.getChapterTab(1).content).toBe('');
        expect(store.getChapterTab(1).dirty).toBe(false);
      });
    });

    describe('updateTabTitle', () => {
      it('更新章节标签标题', () => {
        const store = useBookStore();
        store.openChapterTab(1, '旧标题');

        store.updateTabTitle(1, '新标题');

        expect(store.getChapterTab(1).title).toBe('新标题');
      });
    });

    describe('updateTabContent', () => {
      it('更新标签内容', () => {
        const store = useBookStore();
        store.openChapterTab(1, '章节1');

        store.updateTabContent(1, '更新内容');

        expect(store.getChapterTab(1).content).toBe('更新内容');
        expect(store.getChapterTab(1).loaded).toBe(true);
      });
    });

    describe('activeTabList', () => {
      it('返回按顺序排列的标签列表', () => {
        const store = useBookStore();
        store.openLayerTab('chapter', 1, '章节1');
        store.openLayerTab('chapter', 2, '章节2');

        expect(store.activeTabList).toHaveLength(2);
        expect(store.activeTabList[0].id).toBe(1);
        expect(store.activeTabList[1].id).toBe(2);
      });
    });
  });

  describe('分卷管理', () => {
    it('createVolume 创建分卷', async () => {
      const newVolume = { id: 1, title: '卷1' };
      api.post.mockResolvedValue({ data: { item: newVolume } });
      api.get.mockResolvedValue({ data: { id: 1, title: '书1', volumes: [newVolume] } });

      const store = useBookStore();
      const result = await store.createVolume(1, '卷1');

      expect(api.post).toHaveBeenCalledWith('/workspace/books/1/volumes', { title: '卷1' });
      expect(result).toEqual(newVolume);
    });

    it('deleteVolume 删除分卷', async () => {
      api.delete.mockResolvedValue({ data: {} });

      const store = useBookStore();
      await store.deleteVolume(1);

      expect(api.delete).toHaveBeenCalledWith('/workspace/volumes/1');
    });
  });

  describe('大纲', () => {
    it('fetchOutline 获取大纲', async () => {
      const outline = { outline_text: '大纲内容' };
      api.get.mockResolvedValue({ data: outline });

      const store = useBookStore();
      const result = await store.fetchOutline(1);

      expect(api.get).toHaveBeenCalledWith('/workspace/books/1/outline');
      expect(result).toEqual(outline);
    });

    it('saveOutline 保存大纲', async () => {
      api.put.mockResolvedValue({ data: {} });

      const store = useBookStore();
      await store.saveOutline(1, '新大纲');

      expect(api.put).toHaveBeenCalledWith('/workspace/books/1/outline', { outline_text: '新大纲' });
    });
  });
});
