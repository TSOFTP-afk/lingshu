/**
 * 工作台 Store — 工作台 UI 状态收口
 *
 * 收纳 WorkspaceLayout 中的编辑器模式、抽屉选中类型、大纲数据/Schema、
 * 面板宽度等 UI 状态，避免组件本地 ref 散落。
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useWorkspaceStore = defineStore('workspace', () => {
  const editorMode = ref('idle'); // 'idle' | 'outline'
  const drawerSelectionKind = ref('none'); // 'none' | 'book' | 'volume' | 'chapter'
  const activeOutlineData = ref({});
  const activeOutlineSchema = ref([]);
  const libraryPanelWidth = ref(260);
  const drawerPanelWidth = ref(360);
  const isSavingChapterOrder = ref(false);

  function setEditorMode(mode) {
    editorMode.value = mode;
  }

  function setDrawerSelectionKind(kind) {
    drawerSelectionKind.value = kind;
  }

  function setOutlineData(data) {
    activeOutlineData.value = data;
  }

  function setOutlineSchema(schema) {
    activeOutlineSchema.value = schema;
  }

  function setLibraryPanelWidth(width) {
    libraryPanelWidth.value = width;
  }

  function setDrawerPanelWidth(width) {
    drawerPanelWidth.value = width;
  }

  function setSavingChapterOrder(val) {
    isSavingChapterOrder.value = val;
  }

  function resetWorkspace() {
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
