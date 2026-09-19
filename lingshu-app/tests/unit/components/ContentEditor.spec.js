import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import ContentEditor from '../../../src/components/workspace/ContentEditor.vue';

function createWrapper(props = {}) {
  return mount(ContentEditor, {
    props: {
      chapterId: 1,
      content: 'Hello world',
      title: '第一章',
      dirty: false,
      showActionbar: true,
      aiProbability: 0,
      aiProbabilityLevel: 'none',
      ...props,
    },
    global: {
      plugins: [createPinia(), ElementPlus],
    },
  });
}

describe('ContentEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('renders without errors', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.content-editor-wrapper').exists()).toBe(true);
  });

  it('displays chapter title', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.editor-title').text()).toBe('第一章');
  });

  it('shows "未命名章节" when no title is provided', () => {
    const wrapper = createWrapper({ title: '' });
    expect(wrapper.find('.editor-title').text()).toBe('未命名章节');
  });

  it('displays saved/dirty status tag', () => {
    const wrapper = createWrapper({ dirty: false });
    expect(wrapper.find('.editor-toolbar').text()).toContain('已保存');
  });

  it('displays unsaved tag when dirty', () => {
    const wrapper = createWrapper({ dirty: true });
    expect(wrapper.find('.editor-toolbar').text()).toContain('未保存');
  });

  it('renders textarea with content', () => {
    const wrapper = createWrapper();
    const textarea = wrapper.find('.content-textarea');
    expect(textarea.exists()).toBe(true);
    expect(textarea.element.value).toBe('Hello world');
  });

  it('displays word count', () => {
    const wrapper = createWrapper();
    const wordCount = wrapper.find('.word-count');
    expect(wordCount.exists()).toBe(true);
    // "Hello world" without spaces = 10 chars
    expect(wrapper.find('.editor-toolbar').text()).toContain('10');
  });

  it('emits update:content when textarea input changes', async () => {
    const wrapper = createWrapper();
    const textarea = wrapper.find('.content-textarea');
    await textarea.setValue('New content');
    expect(wrapper.emitted('update:content')).toBeTruthy();
    expect(wrapper.emitted('update:content')[0][0]).toBe('New content');
  });

  it('emits change event when content changes', async () => {
    const wrapper = createWrapper();
    const textarea = wrapper.find('.content-textarea');
    await textarea.setValue('New content');
    expect(wrapper.emitted('change')).toBeTruthy();
  });

  it('emits save event on Ctrl+S keydown', async () => {
    const wrapper = createWrapper();
    const textarea = wrapper.find('.content-textarea');
    await textarea.trigger('keydown', { key: 's', ctrlKey: true });
    expect(wrapper.emitted('save')).toBeTruthy();
  });

  it('renders action bar when showActionbar is true', () => {
    const wrapper = createWrapper({ showActionbar: true });
    expect(wrapper.find('.chapter-actionbar').exists()).toBe(true);
  });

  it('hides action bar when showActionbar is false', () => {
    const wrapper = createWrapper({ showActionbar: false });
    expect(wrapper.find('.chapter-actionbar').exists()).toBe(false);
  });

  it('displays AI probability text', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.ai-probability').text()).toContain('未进行AI检测');
  });

  it('displays AI probability percentage when provided', () => {
    const wrapper = createWrapper({ aiProbability: 45, aiProbabilityLevel: 'medium' });
    expect(wrapper.find('.ai-probability').text()).toContain('45%');
  });

  it('renders line markers for content', async () => {
    const wrapper = createWrapper({ content: 'Line 1\nLine 2' });
    // 行号层已演进为视觉行实现：镜像层在 nextTick 后测量软换行再渲染行号
    await vi.waitFor(() => {
      expect(wrapper.findAll('.line-marker-row').length).toBe(2);
    });
  });
});
