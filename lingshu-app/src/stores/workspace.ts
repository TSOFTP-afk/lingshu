/**
 * 工作台 Store — 工作台 UI 状态收口
 *
 * 收纳 WorkspaceLayout 中的编辑器模式、抽屉选中类型、大纲数据/Schema、
 * 面板宽度等 UI 状态，避免组件本地 ref 散落。
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';

export type EditorMode = 'idle' | 'outline';
export type DrawerSelectionKind = 'none' | 'book' | 'volume' | 'chapter';

export interface OutlineSchemaItem {
  [key: string]: unknown;
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const editorMode = ref<EditorMode>('idle');
  const drawerSelectionKind = ref<DrawerSelectionKind>('none');
  const activeOutlineData = ref<Record<string, unknown>>({});
  const activeOutlineSchema = ref<OutlineSchemaItem[]>([]);
  const libraryPanelWidth = ref<number>(260);
  const drawerPanelWidth = ref<number>(360);
  const isSavingChapterOrder = ref<boolean>(false);

  function setEditorMode(mode: EditorMode): void {
    editorMode.value = mode;
  }

  function setDrawerSelectionKind(kind: DrawerSelectionKind): void {
    drawerSelectionKind.value = kind;
  }

  function setOutlineData(data: Record<string, unknown>): void {
    activeOutlineData.value = data;
  }

  function setOutlineSchema(schema: OutlineSchemaItem[]): void {
    activeOutlineSchema.value = schema;
  }

  function setLibraryPanelWidth(width: number): void {
    libraryPanelWidth.value = width;
  }

  function setDrawerPanelWidth(width: number): void {
    drawerPanelWidth.value = width;
  }

  function setSavingChapterOrder(val: boolean): void {
    isSavingChapterOrder.value = val;
  }

  function resetWorkspace(): void {
    editorMode.value = 'idle';
    drawerSelectionKind.value = 'none';
    activeOutlineData.value = {};
    activeOutlineSchema.value = [];
  }

  return {
    editorMode,
    drawerSelectionKind,
    activeOutlineData,
    activeOutlineSchema,
    libraryPanelWidth,
    drawerPanelWidth,
    isSavingChapterOrder,
    setEditorMode,
    setDrawerSelectionKind,
    setOutlineData,
    setOutlineSchema,
    setLibraryPanelWidth,
    setDrawerPanelWidth,
    setSavingChapterOrder,
    resetWorkspace,
  };
}, {
  persist: {
    key: 'lingshu_workspace_state',
    storage: localStorage,
    paths: ['editorMode'],
  },
});
