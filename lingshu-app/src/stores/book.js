/**
 * 书籍 Store — 工作台书籍 + 分卷 + 章节管理
 *
 * 对应 Qt 模块: app_tree.py (树视图管理) + app_editor.py (章节编辑状态)
 */
import { defineStore } from 'pinia';
import { ref, computed, reactive } from 'vue';
import api from '../utils/api';

const MAX_OPEN_CHAPTER_TABS = 20;

export const useBookStore = defineStore('book', () => {
  const books = ref([]);
  const currentBook = ref(null);
  const loading = ref(false);

  // 通用层级标签管理：book / volume / chapter
  const openTabs = reactive({});
  const tabOrder = ref([]);
  const activeTabKey = ref(null);

  const currentBookId = computed(() => currentBook.value?.id ?? null);
  const activeTab = computed(() => openTabs[activeTabKey.value] || null);
  const activeChapterId = computed(() => activeTab.value?.kind === 'chapter' ? activeTab.value.id : null);
  const activeTabCount = computed(() => tabOrder.value.length);
  const maxOpenChapterTabs = MAX_OPEN_CHAPTER_TABS;

  // ========== 书籍 ==========

  async function fetchBooks() {
    loading.value = true;
    try {
      const { data } = await api.get('/workspace/books');
      books.value = data.items || [];
    } finally {
      loading.value = false;
    }
  }

  function upsertBookInList(book) {
    if (!book?.id) return;
    const index = books.value.findIndex(item => item.id === book.id);
    if (index >= 0) {
      books.value[index] = book;
    } else {
      books.value = [book, ...books.value];
    }
  }

  async function createBook(title) {
    const { data } = await api.post('/workspace/books', { title });
    await fetchBooks();
    currentBook.value = data.item;
    return data.item;
  }

  async function fetchBook(bookId, { force } = {}) {
    if (!force && currentBook.value && Number(currentBook.value.id) === Number(bookId)) {
      return currentBook.value;
    }
    const { data } = await api.get(`/workspace/books/${bookId}`);
    currentBook.value = data;
    upsertBookInList(data);
    updateOpenTabTitlesFromBook(data);
    return data;
  }

  async function renameBook(bookId, title) {
    await api.patch(`/workspace/books/${bookId}`, { title });
    if (currentBook.value?.id === bookId) currentBook.value.title = title;
    const book = books.value.find(b => b.id === bookId);
    if (book) book.title = title;
    updateLayerTabTitle(makeLayerTabKey('book', bookId), title);
  }

  async function deleteBook(bookId) {
    await api.delete(`/workspace/books/${bookId}`);
    books.value = books.value.filter(b => b.id !== bookId);
    if (currentBook.value?.id === bookId) currentBook.value = null;
  }

  function resetWorkspaceState() {
    books.value = [];
    currentBook.value = null;
    loading.value = false;
    tabOrder.value = [];
    activeTabKey.value = null;
    Object.keys(openTabs).forEach((key) => {
      delete openTabs[key];
    });
  }

  // ========== 分卷 ==========

  async function createVolume(bookId, title) {
    const { data } = await api.post(`/workspace/books/${bookId}/volumes`, { title });
    await fetchBook(bookId, { force: true });
    return data.item;
  }

  async function deleteVolume(volumeId) {
    await api.delete(`/workspace/volumes/${volumeId}`);
  }

  // ========== 通用层级标签管理 ==========

  function makeLayerTabKey(kind, id, meta = {}) {
    if (kind === 'volume' && (id === null || id === undefined)) {
      return `volume:unassigned:${meta.bookId ?? 'unknown'}`;
    }
    return `${kind}:${id}`;
  }

  function openLayerTab(kind, id, title, meta = {}) {
    const key = makeLayerTabKey(kind, id, meta);
    const existing = openTabs[key];
    if (existing) {
      activeTabKey.value = key;
      return existing;
    }
    if (tabOrder.value.length >= MAX_OPEN_CHAPTER_TABS) {
      const disposableKey = tabOrder.value.find(tabKey => !openTabs[tabKey]?.dirty && tabKey !== activeTabKey.value)
        || tabOrder.value.find(tabKey => !openTabs[tabKey]?.dirty);
      if (!disposableKey) return null;
      closeLayerTab(disposableKey);
    }
    const tab = {
      key,
      kind,
      id,
      title,
      dirty: false,
      loaded: kind !== 'chapter',
      loading: false,
      content: null,
      savedContent: null,
      error: null,
      meta: { ...meta },
    };
    openTabs[key] = tab;
    tabOrder.value.push(key);
    activeTabKey.value = key;
    return tab;
  }

  function activateLayerTab(key) {
    if (!openTabs[key]) return null;
    activeTabKey.value = key;
    return openTabs[key];
  }

  function closeLayerTab(key) {
    const tab = openTabs[key];
    if (!tab) return;
    delete openTabs[key];
    tabOrder.value = tabOrder.value.filter(tabKey => tabKey !== key);
    if (activeTabKey.value === key) {
      activeTabKey.value = tabOrder.value[tabOrder.value.length - 1] || null;
    }
  }

  function updateLayerTabTitle(key, title) {
    if (openTabs[key]) openTabs[key].title = title;
  }

  function openChapterTab(chapterId, title, meta = {}) {
    return openLayerTab('chapter', chapterId, title, meta);
  }

  function closeChapterTab(chapterId) {
    closeLayerTab(makeLayerTabKey('chapter', chapterId));
  }

  function getChapterTab(chapterId) {
    return openTabs[makeLayerTabKey('chapter', chapterId)] || null;
  }

  function markTabDirty(chapterId, isDirty = true) {
    const tab = getChapterTab(chapterId);
    if (tab) tab.dirty = isDirty;
  }

  function markTabClean(chapterId, savedContent = undefined) {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.dirty = false;
      tab.savedContent = savedContent === undefined ? tab.content : savedContent;
    }
  }

  function updateTabTitle(chapterId, title) {
    const tab = getChapterTab(chapterId);
    if (tab) tab.title = title;
  }

  function setTabLoading(chapterId, isLoading = true) {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.loading = isLoading;
      tab.error = null;
    }
  }

  function setTabContent(chapterId, content, { dirty = false, savedContent = content } = {}) {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.content = content;
      tab.savedContent = savedContent;
      tab.loaded = true;
      tab.loading = false;
      tab.error = null;
      tab.dirty = dirty;
    }
  }

  function updateTabAiProbability(chapterId, probability = 0, level = 'none') {
    const safeProbability = Math.max(0, Math.min(100, Number(probability) || 0));
    const safeLevel = String(level || 'none');
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.ai_probability = safeProbability;
      tab.ai_probability_level = safeLevel;
    }
    updateChapterInBookTree(chapterId, (chapter) => {
      chapter.ai_probability = safeProbability;
      chapter.ai_probability_level = safeLevel;
    });
  }

  function updateTabContent(chapterId, content) {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.content = content;
      tab.loaded = true;
    }
  }

  function revertTabContent(chapterId) {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.content = tab.savedContent ?? '';
      tab.dirty = false;
      tab.loaded = true;
    }
  }

  function setTabError(chapterId, error) {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.loading = false;
      tab.error = error || 'load_failed';
    }
  }

  function updateOpenTabTitlesFromBook(book) {
    if (!book?.id) return;
    updateLayerTabTitle(makeLayerTabKey('book', book.id), book.title || '未命名');
    for (const volume of book.volumes || []) {
      updateLayerTabTitle(
        makeLayerTabKey('volume', volume.id, { bookId: book.id }),
        volume.title || '正文',
      );
      for (const chapter of volume.chapters || []) {
        updateTabTitle(chapter.id, chapter.title || `章节 #${chapter.id}`);
      }
    }
  }

  function updateChapterInBookTree(chapterId, updater) {
    if (!currentBook.value?.volumes) return;
    for (const volume of currentBook.value.volumes) {
      const chapter = (volume.chapters || []).find(item => Number(item.id) === Number(chapterId));
      if (chapter) {
        updater(chapter);
        return;
      }
    }
  }

  const activeTabList = computed(() =>
    tabOrder.value.map(key => openTabs[key]).filter(Boolean)
  );

  // ========== 大纲 ==========

  async function fetchOutline(bookId) {
    const { data } = await api.get(`/workspace/books/${bookId}/outline`);
    return data;
  }

  async function saveOutline(bookId, outlineText) {
    await api.put(`/workspace/books/${bookId}/outline`, { outline_text: outlineText });
  }

  function setOutlineText(text) {
    if (currentBook.value) {
      currentBook.value.outline_text = text || '';
    }
  }

  return {
    books, currentBook, currentBookId, loading, maxOpenChapterTabs,
    openTabs, tabOrder, activeTabKey, activeTab, activeChapterId, activeTabCount, activeTabList,
    fetchBooks, createBook, fetchBook, renameBook, deleteBook, resetWorkspaceState,
    createVolume, deleteVolume,
    makeLayerTabKey, openLayerTab, activateLayerTab, closeLayerTab, updateLayerTabTitle,
    openChapterTab, closeChapterTab, getChapterTab, markTabDirty, markTabClean, updateTabTitle,
    setTabLoading, setTabContent, updateTabContent, updateTabAiProbability, revertTabContent, setTabError,
    fetchOutline, saveOutline, setOutlineText,
  };
}, {
  persist: {
    key: 'lingshu_book_state',
    storage: localStorage,
    paths: ['openTabs', 'tabOrder', 'activeTabKey'],
  },
});
