import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import StatusBar from '../../../src/components/layout/StatusBar.vue';

function createWrapper() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(StatusBar, {
    global: {
      plugins: [pinia],
    },
  });
}

describe('StatusBar', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('renders without errors', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.status-bar').exists()).toBe(true);
  });

  it('displays ready status text', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.status-text').text()).toBe('就绪');
  });

  it('renders status dot indicator', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.status-dot').exists()).toBe(true);
  });

  it('displays word count', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.status-bar').text()).toContain('字数:');
  });

  it('displays AI probability section', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.status-bar').text()).toContain('AI:');
  });

  it('displays total word count', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.status-bar').text()).toContain('总计:');
  });

  it('shows dash for AI probability when 0', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.status-bar').text()).toContain('AI: -');
  });

  it('shows percentage for AI probability when non-zero', async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const wrapper = mount(StatusBar, {
      global: { plugins: [pinia] },
    });
    // Access the store and set AI probability
    const chapterStore = wrapper.vm.chapterStore;
    chapterStore.currentChapter = { content: 'test', ai_probability: 75 };
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.status-bar').text()).toContain('75%');
  });

  it('calculates word count from chapter content', async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const wrapper = mount(StatusBar, {
      global: { plugins: [pinia] },
    });
    const chapterStore = wrapper.vm.chapterStore;
    chapterStore.currentChapter = { content: '你好世界', ai_probability: 0 };
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.wordCount).toBe(4);
  });

  it('renders status dividers', () => {
    const wrapper = createWrapper();
    const dividers = wrapper.findAll('.status-divider');
    expect(dividers.length).toBe(2);
  });
});
