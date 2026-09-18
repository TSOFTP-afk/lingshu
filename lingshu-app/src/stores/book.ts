/**
 * 书籍 Store — 工作台书籍 + 分卷 + 章节管理
 *
 * 对应 Qt 模块: app_tree.py (树视图管理) + app_editor.py (章节编辑状态)
 */
import { defineStore } from 'pinia';
import { ref, computed, reactive } from 'vue';
import api from '../utils/api';

const MAX_OPEN_CHAPTER_TABS = 20;

export type TabKind = 'book' | 'volume' | 'chapter';
export type AiProbabilityLevel = 'none' | 'low' | 'medium' | 'high' | string;

export interface Chapter {
  id: number;
  title: string;
  ai_probability?: number;
  ai_probability_level?: string;
  [key: string]: unknown;
}

export interface Volume {
  id: number;
  title: string;
  chapters?: Chapter[];
  [key: string]: unknown;
}

export interface Book {
  id: number;
  title: string;
  volumes?: Volume[];
  outline_text?: string;
  [key: string]: unknown;
}

export interface ChapterTab {
  key: string;
  kind: TabKind;
  id: number | null;
  title: string;
  dirty: boolean;
  loaded: boolean;
  loading: boolean;
  content: string | null;
  savedContent: string | null;
  error: string | null;
  ai_probability?: number;
  ai_probability_level?: string;
  meta: Record<string, unknown>;
}

export interface TabMeta {
  bookId?: number;
  [key: string]: unknown;
}

export const useBookStore = defineStore('book', () => {
  const books = ref<Book[]>([]);
  const currentBook = ref<Book | null>(null);
  const loading = ref<boolean>(false);

  const openTabs = reactive<Record<string, ChapterTab>>({});
  const tabOrder = ref<string[]>([]);
  const activeTabKey = ref<string | null>(null);

  const currentBookId = computed<number | null>(() => currentBook.value?.id ?? null);
  const activeTab = computed<ChapterTab | null>(() =>
    activeTabKey.value ? (openTabs[activeTabKey.value] || null) : null
  );
  const activeChapterId = computed<number | null>(() =>
    activeTab.value?.kind === 'chapter' ? activeTab.value.id : null
  );
  const activeTabCount = computed<number>(() => tabOrder.value.length);
  const maxOpenChapterTabs = MAX_OPEN_CHAPTER_TABS;

  async function fetchBooks(): Promise<void> {
    loading.value = true;
    try {
      const { data } = await api.get('/workspace/books');
      books.value = data.items || [];
    } finally {
      loading.value = false;
    }
  }

  function upsertBookInList(book: Book): void {
    if (!book?.id) return;
    const index = books.value.findIndex(item => item.id === book.id);
    if (index >= 0) {
      books.value[index] = book;
    } else {
      books.value = [book, ...books.value];
    }
  }

  async function createBook(title: string): Promise<Book> {
    const { data } = await api.post('/workspace/books', { title });
    await fetchBooks();
    currentBook.value = data.item;
    return data.item;
  }

  async function fetchBook(bookId: number, { force }: { force?: boolean } = {}): Promise<Book> {
    if (!force && currentBook.value && Number(currentBook.value.id) === Number(bookId)) {
      return currentBook.value;
    }
    const { data } = await api.get(`/workspace/books/${bookId}`);
    currentBook.value = data;
    upsertBookInList(data);
    updateOpenTabTitlesFromBook(data);
    return data;
  }

  async function renameBook(bookId: number, title: string): Promise<void> {
    await api.patch(`/workspace/books/${bookId}`, { title });
    if (currentBook.value?.id === bookId) currentBook.value.title = title;
    const book = books.value.find(b => b.id === bookId);
    if (book) book.title = title;
    updateLayerTabTitle(makeLayerTabKey('book', bookId), title);
  }

  async function deleteBook(bookId: number): Promise<void> {
    await api.delete(`/workspace/books/${bookId}`);
    books.value = books.value.filter(b => b.id !== bookId);
    if (currentBook.value?.id === bookId) currentBook.value = null;
  }

  function resetWorkspaceState(): void {
    books.value = [];
    currentBook.value = null;
    loading.value = false;
    tabOrder.value = [];
    activeTabKey.value = null;
    Object.keys(openTabs).forEach((key) => {
      delete openTabs[key];
    });
  }

  async function createVolume(bookId: number, title: string): Promise<unknown> {
    const { data } = await api.post(`/workspace/books/${bookId}/volumes`, { title });
    await fetchBook(bookId, { force: true });
    return data.item;
  }

  async function deleteVolume(volumeId: number): Promise<void> {
    await api.delete(`/workspace/volumes/${volumeId}`);
  }

  function makeLayerTabKey(kind: TabKind, id: number | null, meta: TabMeta = {}): string {
    if (kind === 'volume' && (id === null || id === undefined)) {
      return `volume:unassigned:${meta.bookId ?? 'unknown'}`;
    }
    return `${kind}:${id}`;
  }

  function openLayerTab(
    kind: TabKind,
    id: number | null,
    title: string,
    meta: TabMeta = {}
  ): ChapterTab | null {
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
    const tab: ChapterTab = {
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

  function activateLayerTab(key: string): ChapterTab | null {
    if (!openTabs[key]) return null;
    activeTabKey.value = key;
    return openTabs[key];
  }

  function closeLayerTab(key: string): void {
    const tab = openTabs[key];
    if (!tab) return;
    delete openTabs[key];
    tabOrder.value = tabOrder.value.filter(tabKey => tabKey !== key);
    if (activeTabKey.value === key) {
      activeTabKey.value = tabOrder.value[tabOrder.value.length - 1] || null;
    }
  }

  function updateLayerTabTitle(key: string, title: string): void {
    if (openTabs[key]) openTabs[key].title = title;
  }

  function openChapterTab(chapterId: number, title: string, meta: TabMeta = {}): ChapterTab | null {
    return openLayerTab('chapter', chapterId, title, meta);
  }

  function closeChapterTab(chapterId: number): void {
    closeLayerTab(makeLayerTabKey('chapter', chapterId));
  }

  function getChapterTab(chapterId: number): ChapterTab | null {
    return openTabs[makeLayerTabKey('chapter', chapterId)] || null;
  }

  function markTabDirty(chapterId: number, isDirty: boolean = true): void {
    const tab = getChapterTab(chapterId);
    if (tab) tab.dirty = isDirty;
  }

  function markTabClean(chapterId: number, savedContent?: string): void {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.dirty = false;
      tab.savedContent = savedContent === undefined ? tab.content : savedContent;
    }
  }

  function updateTabTitle(chapterId: number, title: string): void {
    const tab = getChapterTab(chapterId);
    if (tab) tab.title = title;
  }

  function setTabLoading(chapterId: number, isLoading: boolean = true): void {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.loading = isLoading;
      tab.error = null;
    }
  }

  function setTabContent(
    chapterId: number,
    content: string,
    { dirty = false, savedContent = content }: { dirty?: boolean; savedContent?: string } = {}
  ): void {
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

  function updateTabAiProbability(
    chapterId: number,
    probability: number = 0,
    level: AiProbabilityLevel = 'none'
  ): void {
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

  function updateTabContent(chapterId: number, content: string): void {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.content = content;
      tab.loaded = true;
    }
  }

  function revertTabContent(chapterId: number): void {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.content = tab.savedContent ?? '';
      tab.dirty = false;
      tab.loaded = true;
    }
  }

  function setTabError(chapterId: number, error: string): void {
    const tab = getChapterTab(chapterId);
    if (tab) {
      tab.loading = false;
      tab.error = error || 'load_failed';
    }
  }

  function updateOpenTabTitlesFromBook(book: Book): void {
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

  function updateChapterInBookTree(chapterId: number, updater: (chapter: Chapter) => void): void {
    if (!currentBook.value?.volumes) return;
    for (const volume of currentBook.value.volumes) {
      const chapter = (volume.chapters || []).find(item => Number(item.id) === Number(chapterId));
      if (chapter) {
        updater(chapter);
        return;
      }
    }
  }

  const activeTabList = computed<ChapterTab[]>(() =>
    tabOrder.value.map(key => openTabs[key]).filter(Boolean)
  );

  async function fetchOutline(bookId: number): Promise<unknown> {
    const { data } = await api.get(`/workspace/books/${bookId}/outline`);
    return data;
  }

  async function saveOutline(bookId: number, outlineText: string): Promise<void> {
    await api.put(`/workspace/books/${bookId}/outline`, { outline_text: outlineText });
  }

  function setOutlineText(text: string): void {
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
