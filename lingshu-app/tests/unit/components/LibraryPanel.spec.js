import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import LibraryPanel from '../../../src/components/workspace/LibraryPanel.vue';

const sampleBooks = [
  {
    id: 1,
    title: '灵枢指南',
    cloud_book_id: null,
    word_count: 5000,
    volumes: [
      {
        id: 10,
        title: '第一卷',
        is_virtual: false,
        chapters: [
          { id: 100, title: '第一章', word_count: 2000, chapter_type: '正文' },
          { id: 101, title: '番外篇', word_count: 1000, chapter_type: '番外' },
        ],
      },
      {
        id: null,
        title: '正文',
        is_virtual: true,
        chapters: [],
      },
    ],
  },
  {
    id: 2,
    title: '第二本书',
    cloud_book_id: 99,
    word_count: 3000,
    volumes: [
      {
        id: 20,
        title: '正文',
        is_virtual: true,
        chapters: [
          { id: 200, title: '开篇', word_count: 3000, chapter_type: '正文' },
        ],
      },
    ],
  },
];

function createWrapper(props = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(LibraryPanel, {
    props: {
      books: sampleBooks,
      currentBookId: null,
      loading: false,
      ...props,
    },
    global: {
      plugins: [pinia, ElementPlus],
    },
  });
}

describe('LibraryPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('renders without errors', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.library-panel').exists()).toBe(true);
  });

  it('displays panel header', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.panel-header').exists()).toBe(true);
  });

  it('shows book count in heading', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.panel-count').text()).toContain('2 本');
  });

  it('shows volume count in heading', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.panel-count').text()).toContain('卷');
  });

  it('shows chapter count in heading', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.panel-count').text()).toContain('章');
  });

  it('renders tree when books are present', () => {
    const wrapper = createWrapper();
    expect(wrapper.findComponent({ name: 'ElTree' }).exists()).toBe(true);
  });

  it('shows empty state when no books', () => {
    const wrapper = createWrapper({ books: [] });
    expect(wrapper.findComponent({ name: 'ElEmpty' }).exists()).toBe(true);
  });

  it('renders header action buttons', () => {
    const wrapper = createWrapper();
    const buttons = wrapper.findAll('.header-action');
    expect(buttons.length).toBe(4);
  });

  it('disables volume/chapter buttons when no currentBookId', () => {
    const wrapper = createWrapper({ currentBookId: null });
    const buttons = wrapper.findAll('.header-action');
    // Last two buttons (new volume, new chapter) should be disabled
    expect(buttons[2].attributes('disabled')).toBeDefined();
    expect(buttons[3].attributes('disabled')).toBeDefined();
  });

  it('enables volume/chapter buttons when currentBookId is set', () => {
    const wrapper = createWrapper({ currentBookId: 1 });
    const buttons = wrapper.findAll('.header-action');
    expect(buttons[2].attributes('disabled')).toBeUndefined();
    expect(buttons[3].attributes('disabled')).toBeUndefined();
  });

  it('emits create event when new book button is clicked', async () => {
    const wrapper = createWrapper();
    const buttons = wrapper.findAll('.header-action');
    await buttons[0].trigger('click');
    expect(wrapper.emitted('create')).toBeTruthy();
  });

  it('emits import event when import button is clicked', async () => {
    const wrapper = createWrapper();
    const buttons = wrapper.findAll('.header-action');
    await buttons[1].trigger('click');
    expect(wrapper.emitted('import')).toBeTruthy();
  });

  it('computes treeData from books prop', () => {
    const wrapper = createWrapper();
    const treeData = wrapper.vm.treeData;
    expect(treeData.length).toBe(2);
    expect(treeData[0].kind).toBe('book');
    expect(treeData[0].title).toBe('灵枢指南');
    expect(treeData[0].children.length).toBe(2);
  });

  it('emits select event on node click', async () => {
    const wrapper = createWrapper();
    wrapper.vm.onNodeClick({
      kind: 'book',
      bookId: 1,
      title: '灵枢指南',
      nodeKey: 'book-1',
    });
    expect(wrapper.emitted('select')).toBeTruthy();
    expect(wrapper.emitted('select')[0][0]).toEqual({
      kind: 'book',
      id: 1,
      title: '灵枢指南',
    });
  });

  it('emits select with chapter data on chapter node click', () => {
    const wrapper = createWrapper();
    wrapper.vm.onNodeClick({
      kind: 'chapter',
      chapterId: 100,
      bookId: 1,
      title: '第一章',
      nodeKey: 'chapter-100',
    });
    expect(wrapper.emitted('select')[0][0]).toEqual({
      kind: 'chapter',
      id: 100,
      bookId: 1,
      title: '第一章',
    });
  });

  it('shows context menu on right-click', async () => {
    const wrapper = createWrapper();
    wrapper.vm.onContextMenu({ clientX: 100, clientY: 200 }, {
      kind: 'book',
      nodeKey: 'book-1',
      bookId: 1,
    });
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.contextMenu.visible).toBe(true);
    expect(wrapper.find('.context-menu').exists()).toBe(true);
  });

  it('hides context menu when hideContextMenu is called', async () => {
    const wrapper = createWrapper();
    wrapper.vm.onContextMenu({ clientX: 100, clientY: 200 }, {
      kind: 'book',
      nodeKey: 'book-1',
      bookId: 1,
    });
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.contextMenu.visible).toBe(true);

    wrapper.vm.hideContextMenu();
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.contextMenu.visible).toBe(false);
  });

  it('exposes jumpToChapter and jumpToBook methods', () => {
    const wrapper = createWrapper();
    expect(typeof wrapper.vm.jumpToChapter).toBe('function');
    expect(typeof wrapper.vm.jumpToBook).toBe('function');
  });

  it('computes volumeCount correctly', () => {
    const wrapper = createWrapper();
    // Only non-virtual volumes count: volume id=10 (not virtual) + volume id=20 (virtual) = 1
    expect(wrapper.vm.volumeCount).toBe(1);
  });

  it('computes chapterCount correctly', () => {
    const wrapper = createWrapper();
    // 2 chapters in book 1 + 1 chapter in book 2 = 3
    expect(wrapper.vm.chapterCount).toBe(3);
  });

  it('handles context menu actions for book nodes', async () => {
    const wrapper = createWrapper();
    wrapper.vm.onContextMenu({ clientX: 100, clientY: 200 }, {
      kind: 'book',
      nodeKey: 'book-1',
      bookId: 1,
    });
    await wrapper.vm.$nextTick();

    wrapper.vm.handleContextAction('new-volume');
    expect(wrapper.emitted('create-volume')).toBeTruthy();
    expect(wrapper.emitted('create-volume')[0][0]).toBe(1);
  });

  it('handles context menu delete action', async () => {
    const wrapper = createWrapper();
    wrapper.vm.onContextMenu({ clientX: 100, clientY: 200 }, {
      kind: 'book',
      nodeKey: 'book-1',
      bookId: 1,
    });
    await wrapper.vm.$nextTick();

    wrapper.vm.handleContextAction('delete');
    expect(wrapper.emitted('delete')).toBeTruthy();
    expect(wrapper.emitted('delete')[0][0]).toEqual({ kind: 'book', id: 1, bookId: 1 });
  });

  it('handles context menu rename action', async () => {
    const wrapper = createWrapper();
    wrapper.vm.onContextMenu({ clientX: 100, clientY: 200 }, {
      kind: 'chapter',
      nodeKey: 'chapter-100',
      chapterId: 100,
      bookId: 1,
    });
    await wrapper.vm.$nextTick();

    wrapper.vm.handleContextAction('rename');
    expect(wrapper.emitted('rename')).toBeTruthy();
    expect(wrapper.emitted('rename')[0][0]).toEqual({ kind: 'chapter', id: 100 });
  });
});
