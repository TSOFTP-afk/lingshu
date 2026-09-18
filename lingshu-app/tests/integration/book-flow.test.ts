/**
 * 集成测试 — 书籍管理完整流程
 *
 * 测试链路：获取书籍列表 → 创建新书 → 打开书籍 → 重命名 → 删除
 * 使用真实 Pinia store（book），仅 mock API 层
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useBookStore } from '../../src/stores/book';

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

import api from '../../src/utils/api';

describe('书籍管理流程集成测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('完整书籍生命周期', () => {
    it('获取列表 → 创建 → 打开 → 重命名 → 删除', async () => {
      // 1. 初始获取书籍列表
      const initialBooks = {
        items: [
          { id: 1, title: '第一本书', volumes: [] },
          { id: 2, title: '第二本书', volumes: [] },
        ],
      };
      api.get.mockResolvedValue({ data: initialBooks });

      const bookStore = useBookStore();
      await bookStore.fetchBooks();

      expect(api.get).toHaveBeenCalledWith('/workspace/books');
      expect(bookStore.books).toHaveLength(2);
      expect(bookStore.books[0].title).toBe('第一本书');

      // 2. 创建新书
      const newBook = { id: 3, title: '新书', volumes: [] };
      api.post.mockResolvedValue({ data: { item: newBook } });
      // fetchBooks 会在 createBook 中被再次调用
      api.get.mockResolvedValue({ data: { items: [...initialBooks.items, newBook] } });

      const created = await bookStore.createBook('新书');

      expect(api.post).toHaveBeenCalledWith('/workspace/books', { title: '新书' });
      expect(created).toEqual(newBook);
      expect(bookStore.currentBook).toEqual(newBook);
      expect(bookStore.books).toHaveLength(3);

      // 3. 打开书籍（fetchBook）
      const fullBookData = {
        id: 3,
        title: '新书',
        volumes: [
          { id: 10, title: '第一卷', chapters: [{ id: 100, title: '第一章' }] },
        ],
      };
      api.get.mockResolvedValue({ data: fullBookData });

      const fetched = await bookStore.fetchBook(3, { force: true });

      expect(fetched.id).toBe(3);
      expect(bookStore.currentBook?.id).toBe(3);
      expect(bookStore.currentBook?.volumes).toHaveLength(1);
      expect(bookStore.currentBook?.volumes?.[0].chapters).toHaveLength(1);

      // 4. 重命名书籍
      api.patch.mockResolvedValue({ data: {} });
      await bookStore.renameBook(3, '改名的书');

      expect(api.patch).toHaveBeenCalledWith('/workspace/books/3', { title: '改名的书' });
      expect(bookStore.currentBook?.title).toBe('改名的书');

      // 5. 删除书籍
      api.delete.mockResolvedValue({ data: {} });
      await bookStore.deleteBook(3);

      expect(api.delete).toHaveBeenCalledWith('/workspace/books/3');
      expect(bookStore.books.find(b => b.id === 3)).toBeUndefined();
      expect(bookStore.currentBook).toBeNull();
    });
  });

  describe('分卷管理', () => {
    it('创建分卷后刷新书籍数据', async () => {
      const bookStore = useBookStore();

      // 设置当前书籍
      api.get.mockResolvedValue({
        data: { id: 5, title: '测试书', volumes: [] },
      });
      await bookStore.fetchBook(5, { force: true });

      // 创建分卷
      api.post.mockResolvedValue({ data: { item: { id: 50, title: '新分卷' } } });
      api.get.mockResolvedValue({
        data: {
          id: 5,
          title: '测试书',
          volumes: [{ id: 50, title: '新分卷', chapters: [] }],
        },
      });

      await bookStore.createVolume(5, '新分卷');

      expect(api.post).toHaveBeenCalledWith('/workspace/books/5/volumes', { title: '新分卷' });
      expect(bookStore.currentBook?.volumes).toHaveLength(1);
      expect(bookStore.currentBook?.volumes?.[0].title).toBe('新分卷');
    });
  });

  describe('标签页管理', () => {
    it('打开章节标签 → 切换 → 关闭', () => {
      const bookStore = useBookStore();

      // 打开第一个章节标签
      const tab1 = bookStore.openChapterTab(100, '第一章');
      expect(tab1).not.toBeNull();
      expect(tab1?.kind).toBe('chapter');
      expect(tab1?.title).toBe('第一章');
      expect(bookStore.activeTabKey).toBe('chapter:100');
      expect(bookStore.activeTabCount).toBe(1);

      // 打开第二个章节标签
      const tab2 = bookStore.openChapterTab(200, '第二章');
      expect(tab2).not.toBeNull();
      expect(bookStore.activeTabKey).toBe('chapter:200');
      expect(bookStore.activeTabCount).toBe(2);

      // 切回第一个
      bookStore.activateLayerTab('chapter:100');
      expect(bookStore.activeTabKey).toBe('chapter:100');

      // 关闭第二个
      bookStore.closeChapterTab(200);
      expect(bookStore.activeTabCount).toBe(1);
      expect(bookStore.getChapterTab(200)).toBeNull();

      // 关闭最后一个标签后 activeTabKey 自动切换
      bookStore.closeChapterTab(100);
      expect(bookStore.activeTabCount).toBe(0);
    });

    it('标签页数量上限保护', () => {
      const bookStore = useBookStore();

      // 打开 20 个标签（上限）
      for (let i = 1; i <= 20; i++) {
        const tab = bookStore.openChapterTab(i, `章节${i}`);
        expect(tab).not.toBeNull();
      }
      expect(bookStore.activeTabCount).toBe(20);

      // 打开第 21 个标签，应该自动关闭一个非脏标签
      const tab21 = bookStore.openChapterTab(21, '章节21');
      expect(tab21).not.toBeNull();
      expect(bookStore.activeTabCount).toBe(20);
    });
  });

  describe('重置工作台状态', () => {
    it('resetWorkspaceState 清除所有状态', async () => {
      const bookStore = useBookStore();

      // 填充一些状态
      api.get.mockResolvedValue({ data: { items: [{ id: 1, title: '书' }] } });
      await bookStore.fetchBooks();
      bookStore.openChapterTab(1, '章节');

      expect(bookStore.books).toHaveLength(1);
      expect(bookStore.activeTabCount).toBe(1);

      // 重置
      bookStore.resetWorkspaceState();

      expect(bookStore.books).toHaveLength(0);
      expect(bookStore.currentBook).toBeNull();
      expect(bookStore.loading).toBe(false);
      expect(bookStore.activeTabCount).toBe(0);
      expect(bookStore.activeTabKey).toBeNull();
    });
  });
});
