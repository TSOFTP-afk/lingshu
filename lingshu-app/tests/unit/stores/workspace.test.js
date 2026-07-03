import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useWorkspaceStore } from '../../../src/stores/workspace';

describe('useWorkspaceStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  describe('初始状态', () => {
    it('初始状态正确', () => {
      const store = useWorkspaceStore();
      expect(store.editorMode).toBe('idle');
      expect(store.drawerSelectionKind).toBe('none');
      expect(store.activeOutlineData).toEqual({});
      expect(store.activeOutlineSchema).toEqual([]);
      expect(store.libraryPanelWidth).toBe(260);
      expect(store.drawerPanelWidth).toBe(360);
      expect(store.isSavingChapterOrder).toBe(false);
    });
  });

  describe('setter actions', () => {
    it('setEditorMode 更新 editorMode', () => {
      const store = useWorkspaceStore();
      store.setEditorMode('outline');
      expect(store.editorMode).toBe('outline');
    });

    it('setDrawerSelectionKind 更新 drawerSelectionKind', () => {
      const store = useWorkspaceStore();
      store.setDrawerSelectionKind('book');
      expect(store.drawerSelectionKind).toBe('book');
    });

    it('setOutlineData 更新 activeOutlineData（深度相等）', () => {
      const store = useWorkspaceStore();
      store.setOutlineData({ a: 1 });
      expect(store.activeOutlineData).toStrictEqual({ a: 1 });
    });

    it('setOutlineSchema 更新 activeOutlineSchema（深度相等）', () => {
      const store = useWorkspaceStore();
      store.setOutlineSchema([{ x: 1 }]);
      expect(store.activeOutlineSchema).toStrictEqual([{ x: 1 }]);
    });

    it('setLibraryPanelWidth 更新 libraryPanelWidth', () => {
      const store = useWorkspaceStore();
      store.setLibraryPanelWidth(300);
      expect(store.libraryPanelWidth).toBe(300);
    });

    it('setDrawerPanelWidth 更新 drawerPanelWidth', () => {
      const store = useWorkspaceStore();
      store.setDrawerPanelWidth(400);
      expect(store.drawerPanelWidth).toBe(400);
    });

    it('setSavingChapterOrder 更新 isSavingChapterOrder', () => {
      const store = useWorkspaceStore();
      store.setSavingChapterOrder(true);
      expect(store.isSavingChapterOrder).toBe(true);
    });
  });

  describe('resetWorkspace', () => {
    it('重置编辑状态但保留面板宽度偏好', () => {
      const store = useWorkspaceStore();
      store.setEditorMode('outline');
      store.setDrawerSelectionKind('book');
      store.setOutlineData({ a: 1 });
      store.setOutlineSchema([{ x: 1 }]);
      store.setLibraryPanelWidth(300);
      store.setDrawerPanelWidth(400);
      store.setSavingChapterOrder(true);

      store.resetWorkspace();

      expect(store.editorMode).toBe('idle');
      expect(store.drawerSelectionKind).toBe('none');
      expect(store.activeOutlineData).toStrictEqual({});
      expect(store.activeOutlineSchema).toStrictEqual([]);
      // 面板宽度属于用户布局偏好，应保留
      expect(store.libraryPanelWidth).toBe(300);
      expect(store.drawerPanelWidth).toBe(400);
      // isSavingChapterOrder 不在 reset 范围内（瞬时态），保留当前值
      expect(store.isSavingChapterOrder).toBe(true);
    });

    it('resetWorkspace 仅清理编辑相关状态，不影响面板宽度默认值', () => {
      const store = useWorkspaceStore();
      store.setEditorMode('outline');
      store.setDrawerSelectionKind('chapter');

      store.resetWorkspace();

      expect(store.editorMode).toBe('idle');
      expect(store.drawerSelectionKind).toBe('none');
      // 未设置过面板宽度，应保持初始默认值
      expect(store.libraryPanelWidth).toBe(260);
      expect(store.drawerPanelWidth).toBe(360);
    });
  });
});
