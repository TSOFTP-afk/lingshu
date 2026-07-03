import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import ChapterTabBar from '../../../src/components/workspace/ChapterTabBar.vue';

const sampleTabs = [
  { key: 'book:1', kind: 'book', title: '我的作品', dirty: false },
  { key: 'chapter:1', kind: 'chapter', title: '第一章', dirty: false },
  { key: 'chapter:2', kind: 'chapter', title: '第二章', dirty: true },
];

function createWrapper(props = {}) {
  return mount(ChapterTabBar, {
    props: {
      tabs: sampleTabs,
      activeKey: 'chapter:1',
      ...props,
    },
  });
}

describe('ChapterTabBar', () => {
  it('renders without errors', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.chapter-tab-bar').exists()).toBe(true);
  });

  it('renders all tabs', () => {
    const wrapper = createWrapper();
    const tabItems = wrapper.findAll('.tab-item');
    expect(tabItems.length).toBe(3);
  });

  it('marks active tab with active class', () => {
    const wrapper = createWrapper({ activeKey: 'chapter:1' });
    const activeTab = wrapper.find('.tab-item--active');
    expect(activeTab.exists()).toBe(true);
    expect(activeTab.find('.tab-label').text()).toContain('第一章');
  });

  it('displays kind label for each tab type', () => {
    const wrapper = createWrapper();
    const tabItems = wrapper.findAll('.tab-item');
    // book tab should show '书'
    expect(tabItems[0].find('.tab-kind').text()).toBe('书');
    // chapter tabs should show '章'
    expect(tabItems[1].find('.tab-kind').text()).toBe('章');
  });

  it('shows dirty indicator for unsaved tabs', () => {
    const wrapper = createWrapper();
    const dirtyTab = wrapper.findAll('.tab-item')[2];
    expect(dirtyTab.classes()).toContain('tab-item--dirty');
    expect(dirtyTab.find('.tab-label').text()).toContain('●');
  });

  it('does not show dirty indicator for clean tabs', () => {
    const wrapper = createWrapper();
    const cleanTab = wrapper.findAll('.tab-item')[1];
    expect(cleanTab.classes()).not.toContain('tab-item--dirty');
    expect(cleanTab.find('.tab-label').text()).not.toContain('●');
  });

  it('renders close button on each tab', () => {
    const wrapper = createWrapper();
    const closeButtons = wrapper.findAll('.tab-close');
    expect(closeButtons.length).toBe(3);
  });

  it('emits close event when close button is clicked', async () => {
    const wrapper = createWrapper();
    const closeButton = wrapper.findAll('.tab-close')[1];
    await closeButton.trigger('click');
    expect(wrapper.emitted('close')).toBeTruthy();
    expect(wrapper.emitted('close')[0][0]).toBe('chapter:1');
  });

  it('emits activate event when tab is clicked (via pointer up)', async () => {
    const wrapper = createWrapper();
    // Simulate the pointer interaction by setting internal state directly
    // since trigger('pointerdown') with button property fails in jsdom
    wrapper.vm.pressedTabKey = 'book:1';
    wrapper.vm.dragMoved = false;
    wrapper.vm.isDragging = true;
    // Simulate pointerup which should emit activate
    const tabList = wrapper.find('.tab-list');
    await tabList.trigger('pointerup', { pointerId: 1 });
    expect(wrapper.emitted('activate')).toBeTruthy();
    expect(wrapper.emitted('activate')[0][0]).toBe('book:1');
  });

  it('does not emit activate when dragging', async () => {
    const wrapper = createWrapper();
    const tabList = wrapper.find('.tab-list');
    wrapper.vm.pressedTabKey = 'book:1';
    wrapper.vm.dragMoved = true;
    await tabList.trigger('pointerup', { pointerId: 1 });
    expect(wrapper.emitted('activate')).toBeFalsy();
  });

  it('renders volume kind label correctly', () => {
    const volumeTabs = [
      { key: 'volume:1', kind: 'volume', title: '第一卷', dirty: false },
    ];
    const wrapper = createWrapper({ tabs: volumeTabs, activeKey: 'volume:1' });
    expect(wrapper.find('.tab-kind').text()).toBe('卷');
  });

  it('renders with empty tabs array', () => {
    const wrapper = createWrapper({ tabs: [], activeKey: null });
    expect(wrapper.find('.chapter-tab-bar').exists()).toBe(true);
    expect(wrapper.findAll('.tab-item').length).toBe(0);
  });
});
