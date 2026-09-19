import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import DrawerPanel from '../../../src/components/drawer/DrawerPanel.vue';

// Stub all tab child components
const tabStubs = {
  OverviewTab: { template: '<div class="stub-overview-tab">Overview</div>' },
  ShortcutsTab: { template: '<div class="stub-shortcuts-tab">Shortcuts</div>' },
  CharactersTab: { template: '<div class="stub-characters-tab">Characters</div>' },
  WorldTab: { template: '<div class="stub-world-tab">World</div>' },
  SkillsTab: { template: '<div class="stub-skills-tab">Skills</div>' },
  AnalysisTab: { template: '<div class="stub-analysis-tab">Analysis</div>' },
  ReviewTab: { template: '<div class="stub-review-tab">Review</div>' },
  TasksTab: { template: '<div class="stub-tasks-tab">Tasks</div>' },
};

function createWrapper(props = {}) {
  return mount(DrawerPanel, {
    props: {
      selectionKind: 'none',
      ...props,
    },
    global: {
      plugins: [createPinia(), ElementPlus],
      stubs: tabStubs,
    },
  });
}

describe('DrawerPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('renders without errors', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.drawer-panel').exists()).toBe(true);
  });

  it('displays drawer title', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.drawer-title').text()).toBe('工具箱');
  });

  it('renders tab panes', () => {
    const wrapper = createWrapper();
    const tabPanes = wrapper.findAllComponents({ name: 'ElTabPane' });
    expect(tabPanes.length).toBeGreaterThanOrEqual(7);
  });

  it('defaults to overview tab', () => {
    const wrapper = createWrapper();
    expect(wrapper.vm.activeTab).toBe('overview');
  });

  it('shows shortcuts tab when selectionKind is book', async () => {
    // shortcuts 独立 tab 已随阶段重构移除；现行为是 selectionKind 变化时自动切换标签页
    const wrapper = createWrapper({ selectionKind: 'book' });
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.activeTab).toBe('overview');
  });

  it('switches to analysis tab when selectionKind changes to chapter', async () => {
    // watch 无 immediate：初始 prop 不触发，仅在 selectionKind 运行时变化时切换
    const wrapper = createWrapper();
    await wrapper.setProps({ selectionKind: 'chapter' });
    expect(wrapper.vm.activeTab).toBe('analysis');
  });

  it('switches tab via onOpenDrawerTab handler', async () => {
    const wrapper = createWrapper();
    // 事件契约已演进为 event bus payload { name }（不再走 document CustomEvent 的 detail 包裹）
    wrapper.vm.onOpenDrawerTab({ name: 'characters' });
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.activeTab).toBe('characters');
  });

  it('ignores invalid tab name from event', async () => {
    const wrapper = createWrapper();
    wrapper.vm.activeTab = 'overview';
    wrapper.vm.onOpenDrawerTab({ detail: { name: 'invalid-tab' } });
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.activeTab).toBe('overview');
  });

  it('cleans up event listener on unmount', () => {
    const wrapper = createWrapper();
    wrapper.unmount();
    // Should not throw - event listener was removed
    const event = new CustomEvent('lingshu:drawer-tab', { detail: { name: 'characters' } });
    expect(() => document.dispatchEvent(event)).not.toThrow();
  });
});
