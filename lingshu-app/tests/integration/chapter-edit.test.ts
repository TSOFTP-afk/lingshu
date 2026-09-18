/**
 * 集成测试 — 章节编辑完整流程
 *
 * 测试链路：打开章节标签 → 加载内容 → 编辑 → 标记脏数据 → 恢复 → 保存
 * 使用真实 Pinia store（book + workspace），仅 mock API 层
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useBookStore } from '../../src/stores/book';
import { useWorkspaceStore } from '../../src/stores/workspace';

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

describe('章节编辑流程集成测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('完整章节编辑流程', () => {
    it('打开章节 → 加载内容 → 编辑 → 标记脏 → 保存 → 清除脏标记', () => {
      const bookStore = useBookStore();

      // 1. 打开章节标签
      const tab = bookStore.openChapterTab(42, '测试章节');
      expect(tab).not.toBeNull();
      expect(tab?.loaded).toBe(false); // chapter 类型初始未加载
      expect(tab?.dirty).toBe(false);
      expect(tab?.content).toBeNull();

      // 2. 模拟加载内容
      const originalContent = '这是章节的原始内容。';
      bookStore.setTabContent(42, originalContent);

      const loadedTab = bookStore.getChapterTab(42);
      expect(loadedTab?.loaded).toBe(true);
      expect(loadedTab?.content).toBe(originalContent);
      expect(loadedTab?.savedContent).toBe(originalContent);
      expect(loadedTab?.dirty).toBe(false);

      // 3. 模拟用户编辑
      const editedContent = '这是修改后的内容。';
      bookStore.updateTabContent(42, editedContent);

      expect(bookStore.getChapterTab(42)?.content).toBe(editedContent);

      // 4. 标记为脏（用户修改未保存）
      bookStore.markTabDirty(42);
      expect(bookStore.getChapterTab(42)?.dirty).toBe(true);

      // 5. 保存成功后清除脏标记
      bookStore.markTabClean(42, editedContent);
      expect(bookStore.getChapterTab(42)?.dirty).toBe(false);
      expect(bookStore.getChapterTab(42)?.savedContent).toBe(editedContent);
    });

    it('恢复到上次保存的内容', () => {
      const bookStore = useBookStore();

      // 打开章节并设置初始内容
      bookStore.openChapterTab(10, '章节');
      bookStore.setTabContent(10, '原始内容');

      // 用户编辑
      bookStore.updateTabContent(10, '修改后的内容');
      bookStore.markTabDirty(10);
      expect(bookStore.getChapterTab(10)?.dirty).toBe(true);

      // 恢复
      bookStore.revertTabContent(10);

      expect(bookStore.getChapterTab(10)?.content).toBe('原始内容');
      expect(bookStore.getChapterTab(10)?.dirty).toBe(false);
      expect(bookStore.getChapterTab(10)?.loaded).toBe(true);
    });
  });

  describe('加载状态管理', () => {
    it('setTabLoading 设置加载中状态并清除错误', () => {
      const bookStore = useBookStore();
      bookStore.openChapterTab(1, '章节');

      // 先设置错误
      bookStore.setTabError(1, 'load_failed');
      expect(bookStore.getChapterTab(1)?.error).toBe('load_failed');

      // 设置加载中应清除错误
      bookStore.setTabLoading(1, true);
      expect(bookStore.getChapterTab(1)?.loading).toBe(true);
      expect(bookStore.getChapterTab(1)?.error).toBeNull();
    });

    it('setTabError 设置错误并停止加载', () => {
      const bookStore = useBookStore();
      bookStore.openChapterTab(1, '章节');

      bookStore.setTabLoading(1, true);
      bookStore.setTabError(1, 'network_error');

      expect(bookStore.getChapterTab(1)?.loading).toBe(false);
      expect(bookStore.getChapterTab(1)?.error).toBe('network_error');
    });

    it('setTabContent 清除加载和错误状态', () => {
      const bookStore = useBookStore();
      bookStore.openChapterTab(1, '章节');

      bookStore.setTabLoading(1, true);
      bookStore.setTabError(1, 'error');

      bookStore.setTabContent(1, '新内容');

      const tab = bookStore.getChapterTab(1);
      expect(tab?.loaded).toBe(true);
      expect(tab?.loading).toBe(false);
      expect(tab?.error).toBeNull();
      expect(tab?.content).toBe('新内容');
    });
  });

  describe('AI 概率更新', () => {
    it('updateTabAiProbability 更新标签和书籍树中的章节', async () => {
      const bookStore = useBookStore();

      // 设置当前书籍，包含章节
      api.get.mockResolvedValue({
        data: {
          id: 1,
          title: '测试书',
          volumes: [
            { id: 10, title: '第一卷', chapters: [{ id: 50, title: '测试章节' }] },
          ],
        },
      });
      await bookStore.fetchBook(1, { force: true });

      // 打开章节标签
      bookStore.openChapterTab(50, '测试章节');

      // 更新 AI 概率
      bookStore.updateTabAiProbability(50, 85, 'high');

      // 验证标签更新
      const tab = bookStore.getChapterTab(50);
      expect(tab?.ai_probability).toBe(85);
      expect(tab?.ai_probability_level).toBe('high');

      // 验证书籍树中的章节也更新
      const volume = bookStore.currentBook?.volumes?.[0];
      const chapter = volume?.chapters?.[0];
      expect(chapter?.ai_probability).toBe(85);
      expect(chapter?.ai_probability_level).toBe('high');
    });

    it('AI 概率值被限制在 0-100 范围', () => {
      const bookStore = useBookStore();
      bookStore.openChapterTab(1, '章节');

      bookStore.updateTabAiProbability(1, 150, 'high');
      expect(bookStore.getChapterTab(1)?.ai_probability).toBe(100);

      bookStore.updateTabAiProbability(1, -20, 'none');
      expect(bookStore.getChapterTab(1)?.ai_probability).toBe(0);
    });
  });

  describe('工作台 UI 状态联动', () => {
    it('切换编辑器模式', () => {
      const workspaceStore = useWorkspaceStore();

      expect(workspaceStore.editorMode).toBe('idle');
      workspaceStore.setEditorMode('outline');
      expect(workspaceStore.editorMode).toBe('outline');

      workspaceStore.setEditorMode('idle');
      expect(workspaceStore.editorMode).toBe('idle');
    });

    it('切换抽屉选中类型', () => {
      const workspaceStore = useWorkspaceStore();

      expect(workspaceStore.drawerSelectionKind).toBe('none');
      workspaceStore.setDrawerSelectionKind('chapter');
      expect(workspaceStore.drawerSelectionKind).toBe('chapter');
    });

    it('重置工作台 UI 状态', () => {
      const workspaceStore = useWorkspaceStore();

      workspaceStore.setEditorMode('outline');
      workspaceStore.setDrawerSelectionKind('book');
      workspaceStore.setOutlineData({ key: 'value' });
      workspaceStore.setOutlineSchema([{ field: 'test' }]);

      workspaceStore.resetWorkspace();

      expect(workspaceStore.editorMode).toBe('idle');
      expect(workspaceStore.drawerSelectionKind).toBe('none');
      expect(workspaceStore.activeOutlineData).toEqual({});
      expect(workspaceStore.activeOutlineSchema).toEqual([]);
    });
  });
});
