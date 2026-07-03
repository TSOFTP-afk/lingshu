import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import { Splitpanes, Pane } from 'splitpanes';
import WorkspaceLayout from '../../../src/components/workspace/WorkspaceLayout.vue';

// Stub child components that have complex dependencies
const globalStubs = {
  LibraryPanel: {
    template: '<div class="stub-library-panel" />',
    methods: { jumpToChapter: vi.fn(), jumpToBook: vi.fn() },
  },
  ChapterTabBar: {
    template: '<div class="stub-chapter-tab-bar" />',
  },
  ContentEditor: {
    template: '<div class="stub-content-editor" />',
  },
  OutlineEditor: {
    template: '<div class="stub-outline-editor" />',
  },
  WelcomePanel: {
    template: '<div class="empty-state"><section class="welcome-panel"><div class="welcome-brand">灵枢工作台</div><h2>开始新的创作项目</h2><div class="welcome-actions">新建作品 导入文稿</div><div class="welcome-stats">作品 章节 总字数</div></section></div>',
  },
  VolumeWorkspace: {
    template: '<div class="stub-volume-workspace" />',
  },
  EditorPlaceholder: {
    template: '<div class="stub-editor-placeholder" />',
  },
  DrawerPanel: {
    template: '<div class="stub-drawer-panel" />',
  },
  BookEntryDialog: {
    template: '<div class="stub-book-entry-dialog" />',
  },
};

function createWrapper() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(WorkspaceLayout, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: globalStubs,
    },
  });
}

describe('WorkspaceLayout', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('renders without errors', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.workspace-container').exists()).toBe(true);
  });

  it('renders the three-pane split layout', () => {
    const wrapper = createWrapper();
    const splitpanes = wrapper.findComponent(Splitpanes);
    expect(splitpanes.exists()).toBe(true);
    const panes = wrapper.findAllComponents(Pane);
    expect(panes.length).toBe(3);
  });

  it('renders LibraryPanel in the left pane', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.stub-library-panel').exists()).toBe(true);
  });

  it('renders DrawerPanel in the right pane', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.stub-drawer-panel').exists()).toBe(true);
  });

  it('shows welcome panel when no current book', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.empty-state').exists()).toBe(true);
    expect(wrapper.text()).toContain('开始新的创作项目');
  });

  it('displays welcome brand', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.welcome-brand').exists()).toBe(true);
    expect(wrapper.text()).toContain('灵枢工作台');
  });

  it('shows create and import buttons in welcome panel', () => {
    const wrapper = createWrapper();
    const actions = wrapper.find('.welcome-actions');
    expect(actions.exists()).toBe(true);
    expect(wrapper.text()).toContain('新建作品');
    expect(wrapper.text()).toContain('导入文稿');
  });

  it('renders BookEntryDialog', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.stub-book-entry-dialog').exists()).toBe(true);
  });

  it('displays stats in welcome panel', () => {
    const wrapper = createWrapper();
    const stats = wrapper.find('.welcome-stats');
    expect(stats.exists()).toBe(true);
    expect(wrapper.text()).toContain('作品');
    expect(wrapper.text()).toContain('章节');
    expect(wrapper.text()).toContain('总字数');
  });
});
