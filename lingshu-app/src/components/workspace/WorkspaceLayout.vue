<template>
  <div class="workspace-container">
    <Splitpanes
      class="default-theme"
      @resized="onResized"
    >
      <!-- 左侧：作品轨道 -->
      <Pane
        :size="leftSize"
        :min-size="18"
        :max-size="35"
      >
        <LibraryPanel
          ref="libraryPanelRef"
          :books="bookStore.books"
          :current-book-id="bookStore.currentBookId"
          :loading="bookStore.loading"
          @select="onTreeNodeSelect"
          @create="openBookEntry('create')"
          @import="openBookEntry('import')"
          @create-volume="onCreateVolume"
          @create-chapter="onCreateChapter"
          @delete="onDeleteItem"
          @rename="onRenameItem"
        />
      </Pane>

      <!-- 中间：编辑区 -->
      <Pane
        :size="centerSize"
        :min-size="30"
      >
        <div class="center-panel">
          <template v-if="!bookStore.currentBook">
            <WelcomePanel
              :book-count="bookStore.books.length"
              :chapter-count="totalChapterCount"
              :total-word-count="totalWordCount"
              @create="openBookEntry('create')"
              @import="openBookEntry('import')"
              @reference="onReferenceClick"
            />
          </template>

          <template v-else>
            <!-- 章节标签栏 -->
            <ChapterTabBar
              v-if="bookStore.activeTabCount > 0"
              :tabs="bookStore.activeTabList"
              :active-key="bookStore.activeTabKey"
              @activate="onActivateTab"
              @close="onCloseTab"
            />

            <!-- 编辑区内容 -->
            <div class="editor-area">
              <!-- 书籍大纲编辑器 -->
              <OutlineEditor
                v-if="activeLayerKind === 'book' && bookStore.currentBook"
                :outline="bookStore.currentBook.outline_text || ''"
                :outline-data="workspaceStore.activeOutlineData"
                :outline-schema="workspaceStore.activeOutlineSchema"
                :label="`《${bookStore.currentBook.title || '未命名'}》- 大纲`"
                @update:outline-data="onOutlineDataChange"
                @change="onOutlineChanged"
              />

              <!-- 卷级工作区 -->
              <VolumeWorkspace
                v-else-if="activeLayerKind === 'volume' && activeVolume"
                :volume="activeVolume"
                :chapters="activeVolumeChapters"
                :book-id="bookStore.currentBookId"
                :book-title="bookStore.currentBook?.title || ''"
                :is-virtual="Boolean(activeVolume.is_virtual)"
                :saving="workspaceStore.isSavingChapterOrder"
                @create-chapter="onCreateChapter"
                @open-chapter="openChapterFromVolume"
                @reorder="onVolumeChapterReorder"
              />

              <!-- 章节内容编辑器（展示态） -->
              <template v-else-if="activeLayerKind === 'chapter' && activeChapterContent !== null">
                <FloatingChapterToolbar />
                <ContentEditor
                  :key="bookStore.activeChapterId"
                  ref="contentEditorRef"
                  :chapter-id="bookStore.activeChapterId"
                  :content="activeChapterContent"
                  :title="activeChapterTitle"
                  :dirty="activeChapterDirty"
                  :show-actionbar="false"
                  :readonly="true"
                  :ai-probability="activeChapterAiProbability"
                  :ai-probability-level="activeChapterAiProbabilityLevel"
                  @update:content="onActiveChapterContentInput"
                  @change="onChapterContentChange"
                  @save="onSaveChapter"
                  @revert="onRevertChapter"
                  @detect-ai="onDetectAiProbability"
                  @edit="openChapterEditDialog"
                />
              </template>

              <!-- 空书籍状态 -->
              <EditorPlaceholder
                v-else-if="activeLayerKind === 'idle'"
                :book-id="bookStore.currentBookId"
                :book-title="bookStore.currentBook?.title || ''"
                @create-chapter="onCreateChapter"
                @open-outline="openCurrentBookTab"
                @import="openBookEntry('import')"
              />
            </div>
          </template>
        </div>
      </Pane>

      <!-- 右侧：9 Tab 抽屉 -->
      <Pane
        :size="rightSize"
        :min-size="20"
        :max-size="40"
      >
        <DrawerPanel :selection-kind="workspaceStore.drawerSelectionKind" />
      </Pane>
    </Splitpanes>

    <!-- 新建 / 导入作品 -->
    <BookEntryDialog
      v-model="showBookEntry"
      :initial-mode="bookEntryMode"
      :current-book-id="bookStore.currentBookId"
      :current-book-title="bookStore.currentBook?.title || ''"
      @created="onBookCreated"
      @imported="onFileImported"
    />

    <!-- 全屏编辑对话框 -->
    <ChapterEditDialog
      v-model="showChapterEditDialog"
      :chapter-id="bookStore.activeChapterId"
      :content="activeChapterContent"
      :title="activeChapterTitle"
      :dirty="activeChapterDirty"
      :ai-probability="activeChapterAiProbability"
      :ai-probability-level="activeChapterAiProbabilityLevel"
      @update:content="onActiveChapterContentInput"
      @change="onChapterContentChange"
      @save="onSaveChapter"
      @revert="onRevertChapter"
      @detect-ai="onDetectAiProbability"
    />
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue';
import { Splitpanes, Pane } from 'splitpanes';
import { useRoute, useRouter } from 'vue-router';
import { useEventBus } from '../../composables/useEventBus';
import { useBookStore } from '../../stores/book';
import { useWorkspaceStore } from '../../stores/workspace';
import { useAuthStore } from '../../stores/auth';
import LibraryPanel from './LibraryPanel.vue';
import ChapterTabBar from './ChapterTabBar.vue';
import ContentEditor from './ContentEditor.vue';
import FloatingChapterToolbar from './FloatingChapterToolbar.vue';
import OutlineEditor from './OutlineEditor.vue';
import WelcomePanel from './WelcomePanel.vue';
import VolumeWorkspace from './VolumeWorkspace.vue';
import EditorPlaceholder from './EditorPlaceholder.vue';
import DrawerPanel from '../drawer/DrawerPanel.vue';
import BookEntryDialog from '../dialogs/BookEntryDialog.vue';
import ChapterEditDialog from './ChapterEditDialog.vue';
import api from '../../utils/api';
import { ElMessage, ElMessageBox } from 'element-plus';

const bookStore = useBookStore();
const workspaceStore = useWorkspaceStore();
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const { on, off, emit } = useEventBus();

// 面板宽度
const initialPaneSizes = readPaneSettings();
const leftSize = ref(initialPaneSizes.left);
const centerSize = ref(initialPaneSizes.center);
const rightSize = ref(initialPaneSizes.right);

const showBookEntry = ref(false);
const showChapterEditDialog = ref(false);
const bookEntryMode = ref('create');

const activeLayerKind = computed(() => bookStore.activeTab?.kind || 'idle');
const activeChapterTab = computed(() => bookStore.activeChapterId ? bookStore.getChapterTab(bookStore.activeChapterId) : null);
const activeChapterContent = computed(() => activeChapterTab.value?.content ?? null);
const activeChapterTitle = computed(() => {
  return activeChapterTab.value?.title || '';
});
const activeChapterDirty = computed(() => {
  return activeChapterTab.value?.dirty || false;
});
const activeChapterAiProbability = computed(() => Number(activeChapterTab.value?.ai_probability || 0));
const activeChapterAiProbabilityLevel = computed(() => activeChapterTab.value?.ai_probability_level || 'none');
const hasActiveChapterContent = computed(() => Boolean((activeChapterContent.value || '').trim()));
const activeVolume = computed(() => {
  const tab = bookStore.activeTab;
  if (tab?.kind !== 'volume' || !bookStore.currentBook?.volumes) return null;
  return (bookStore.currentBook.volumes || []).find(volume =>
    volume.id === tab.id || (tab.id == null && volume.is_virtual)
  ) || null;
});
const activeVolumeChapters = computed(() => activeVolume.value?.chapters || []);

const libraryPanelRef = ref(null);
const contentEditorRef = ref(null);

const totalChapterCount = computed(() =>
  bookStore.books.reduce((sum, book) =>
    sum + (book.volumes || []).reduce((volumeSum, volume) =>
      volumeSum + (volume.chapters || []).length, 0), 0),
);

const totalWordCount = computed(() =>
  bookStore.books.reduce((sum, book) => sum + (Number(book.word_count) || 0), 0),
);

onMounted(() => {
  loadWorkspaceBooksForCurrentUser();
  on('lingshu:save', onGlobalSave);
  on('lingshu:import', onGlobalImport);
  on('lingshu:open-chapter-search-result', onOpenChapterSearchResult);
  on('lingshu:view-settings-updated', onViewSettingsUpdated);
  on('lingshu:detect-ai-probability', onDetectAiProbability);
  on('lingshu:chapter-toolbar-action', onChapterToolbarAction);
  publishChapterToolbarState();
});

onUnmounted(() => {
  off('lingshu:save', onGlobalSave);
  off('lingshu:import', onGlobalImport);
  off('lingshu:open-chapter-search-result', onOpenChapterSearchResult);
  off('lingshu:view-settings-updated', onViewSettingsUpdated);
  off('lingshu:detect-ai-probability', onDetectAiProbability);
  off('lingshu:chapter-toolbar-action', onChapterToolbarAction);
  emit('lingshu:chapter-toolbar-state', { visible: false });
  for (const chapterId of chapterSaveTimers.keys()) {
    clearChapterSaveTimer(chapterId);
  }
});

watch(
  [() => workspaceStore.editorMode, hasActiveChapterContent, activeChapterDirty, activeChapterTitle, () => bookStore.activeChapterId],
  publishChapterToolbarState,
  { immediate: true },
);

watch(
  () => authStore.isLoggedIn,
  (isLoggedIn) => {
    if (isLoggedIn) {
      loadWorkspaceBooksForCurrentUser();
    } else {
      clearWorkspaceView();
    }
  },
);

async function loadWorkspaceBooksForCurrentUser() {
  const user = await authStore.init();
  if (!authStore.isLoggedIn || !user) {
    clearWorkspaceView();
    return;
  }
  try {
    await bookStore.fetchBooks();
  } catch (e) {
    if (e?.response?.status !== 401) ElMessage.error('加载作品失败');
  }
}

function clearWorkspaceView() {
  bookStore.resetWorkspaceState();
  workspaceStore.resetWorkspace();
}

// ========== 树节点事件 ==========

async function onTreeNodeSelect({ kind, id, bookId }) {
  workspaceStore.setDrawerSelectionKind(kind);
  try {
    if (kind === 'book') {
      await router.push(`/workspace/books/${id}`);
    } else if (kind === 'volume') {
      if (id === null || id === undefined) {
        await router.push({ path: `/workspace/books/${bookId}`, query: { volume: 'unassigned' } });
      } else {
        await router.push(`/workspace/books/${bookId}/volumes/${id}`);
      }
    } else if (kind === 'chapter') {
      await router.push({ path: `/workspace/books/${bookId}`, query: { chapter: String(id) } });
    }
  } catch {
    workspaceStore.setDrawerSelectionKind('none');
    ElMessage.error('切换失败，请重试');
  }
}

watch(
  [
    () => route.params.bookId,
    () => route.params.volumeId,
    () => route.query.chapter,
    () => route.query.volume,
  ],
  async () => {
    const bookId = route.params.bookId;
    const volumeId = route.params.volumeId;
    const chapterIdFromQuery = route.query.chapter;
    const volumeFromQuery = route.query.volume;
    if (!bookId) return;
    try {
      await bookStore.fetchBook(bookId);
      if (chapterIdFromQuery) {
        const tab = bookStore.openChapterTab(chapterIdFromQuery, '加载中...', { bookId: Number(bookId) });
        if (!tab) {
          ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
          return;
        }
        await ensureChapterLoaded(chapterIdFromQuery);
      } else if (volumeId || volumeFromQuery === 'unassigned') {
        const resolvedVolumeId = volumeFromQuery === 'unassigned' ? null : volumeId;
        const volume = (bookStore.currentBook?.volumes || []).find(v =>
          Number(v.id) === Number(resolvedVolumeId) || (resolvedVolumeId === null && v.is_virtual),
        );
        const tab = bookStore.openLayerTab('volume', resolvedVolumeId, volume?.title || '正文', {
          bookId: Number(bookId),
          isVirtual: Boolean(volume?.is_virtual),
        });
        if (!tab) {
          ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
          return;
        }
        workspaceStore.setEditorMode('volume');
      } else {
        const tab = bookStore.openLayerTab('book', Number(bookId), bookStore.currentBook?.title || '未命名');
        if (!tab) {
          ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
          return;
        }
        await loadOutline(Number(bookId));
        workspaceStore.setEditorMode('outline');
      }
    } catch {
      ElMessage.error('加载失败，请重试');
    }
  },
  { immediate: true },
);

async function ensureChapterLoaded(chapterId, { force = false } = {}) {
  const tab = bookStore.getChapterTab(chapterId);
  if (!tab) return null;
  workspaceStore.setEditorMode('chapter');
  workspaceStore.setDrawerSelectionKind('chapter');
  if (tab.loaded && !force) return tab;
  if (tab.loading) return tab;
  bookStore.setTabLoading(chapterId, true);
  try {
    const { data } = await api.get(`/workspace/chapters/${chapterId}`);
    const rawContent = data.content || '';
    const normalizedContent = normalizeParagraphSpacing(rawContent);
    bookStore.updateTabTitle(chapterId, data.title || `章节 #${chapterId}`);
    bookStore.setTabContent(chapterId, normalizedContent, {
      dirty: normalizedContent !== rawContent,
      savedContent: rawContent,
    });
    bookStore.updateTabAiProbability(
      chapterId,
      data.ai_probability || 0,
      data.ai_probability_level || 'none',
    );
    if (normalizedContent !== rawContent) scheduleChapterSave(chapterId, 600);
    return bookStore.getChapterTab(chapterId);
  } catch (e) {
    bookStore.setTabError(chapterId, e?.message || 'load_failed');
    ElMessage.error('加载章节失败');
    return null;
  }
}

async function onActivateTab(tabKey) {
  const tab = bookStore.activateLayerTab(tabKey);
  if (!tab) return;
  workspaceStore.setDrawerSelectionKind(tab.kind);
  if (tab.kind === 'book') {
    await bookStore.fetchBook(tab.id);
    await loadOutline(tab.id);
    workspaceStore.setEditorMode('outline');
  } else if (tab.kind === 'volume') {
    const targetBookId = tab.meta?.bookId || bookStore.currentBookId;
    if (targetBookId && Number(bookStore.currentBookId) !== Number(targetBookId)) {
      await bookStore.fetchBook(targetBookId);
    }
    workspaceStore.setEditorMode('volume');
  } else if (tab.kind === 'chapter') {
    if (tab.meta?.bookId && Number(bookStore.currentBookId) !== Number(tab.meta.bookId)) {
      await bookStore.fetchBook(tab.meta.bookId);
    }
    await ensureChapterLoaded(tab.id);
  }
}

async function onCloseTab(tabKey) {
  const closing = bookStore.openTabs[tabKey];
  if (closing?.kind === 'chapter') clearChapterSaveTimer(closing.id);
  bookStore.closeLayerTab(tabKey);
  await activateCurrentTabAfterClose();
}

async function activateCurrentTabAfterClose() {
  const tab = bookStore.activeTab;
  if (!tab) {
    workspaceStore.setEditorMode('idle');
    workspaceStore.setDrawerSelectionKind(bookStore.currentBook ? 'book' : 'none');
    return;
  }
  await onActivateTab(tab.key);
}

async function onOpenChapterSearchResult(event) {
  const detail = event || {};
  const chapterId = Number(detail.chapterId);
  const bookId = Number(detail.bookId || bookStore.currentBookId);
  if (!chapterId) return;
  if (bookId && Number(bookStore.currentBookId) !== bookId) {
    await bookStore.fetchBook(bookId);
  }
  const tab = bookStore.getChapterTab(chapterId) || bookStore.openChapterTab(chapterId, '加载中...', { bookId });
  if (!tab) {
    ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个章节，请先保存或关闭一个标签`);
    return;
  }
  await ensureChapterLoaded(chapterId);
  await nextTick();
  libraryPanelRef.value?.jumpToChapter(chapterId);
  emit('lingshu:chapter-find', detail);
}

// ========== CRUD 事件 ==========

function openBookEntry(mode = 'create') {
  bookEntryMode.value = mode;
  showBookEntry.value = true;
}

async function openCurrentBookTab() {
  if (!bookStore.currentBookId) return;
  const tab = bookStore.openLayerTab('book', bookStore.currentBookId, bookStore.currentBook?.title || '未命名');
  if (!tab) {
    ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
    return;
  }
  await loadOutline(bookStore.currentBookId);
  workspaceStore.setEditorMode('outline');
  workspaceStore.setDrawerSelectionKind('book');
}

async function onBookCreated(book) {
  await bookStore.fetchBooks();
  if (book?.id) await bookStore.fetchBook(book.id);
  if (book?.id) {
    const tab = bookStore.openLayerTab('book', book.id, book.title || '未命名');
    if (!tab) {
      ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
      return;
    }
    await loadOutline(book.id);
  }
  workspaceStore.setEditorMode('outline');
  workspaceStore.setDrawerSelectionKind('book');
}

async function onCreateVolume(bookId) {
  try {
    const { value: title } = await ElMessageBox.prompt('分卷名称', '新建分卷', {
      confirmButtonText: '创建', inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
    });
    if (!title) return;
    const volume = await bookStore.createVolume(bookId, title);
    const tab = bookStore.openLayerTab('volume', volume.id, volume.title || title, { bookId });
    if (!tab) {
      ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
      return;
    }
    workspaceStore.setEditorMode('volume');
    workspaceStore.setDrawerSelectionKind('volume');
  } catch { /* cancelled */ }
}

async function onCreateChapter(target) {
  const isOptions = target && typeof target === 'object';
  const bookId = isOptions ? target.bookId : target;
  const volumeId = isOptions ? (target.volumeId ?? null) : null;
  if (!bookId) return;
  try {
    const { value: title } = await ElMessageBox.prompt('章节标题', '新建章节', {
      confirmButtonText: '创建', inputPattern: /\S+/,
      inputErrorMessage: '标题不能为空',
    });
    if (!title) return;
    const url = volumeId ? `/workspace/volumes/${volumeId}/chapters` : `/workspace/books/${bookId}/chapters`;
    const { data } = await api.post(url, { title });
    const ch = data.item;
    await bookStore.fetchBook(bookId, { force: true });
    const tab = bookStore.openChapterTab(ch.id, ch.title, { bookId });
    if (!tab) {
      ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个章节，请先保存或关闭一个标签`);
      return;
    }
    bookStore.setTabContent(ch.id, '', { dirty: false, savedContent: '' });
    workspaceStore.setEditorMode('chapter');
    workspaceStore.setDrawerSelectionKind('chapter');
  } catch { /* cancelled */ }
}

async function onVolumeChapterReorder(reorderedChapters) {
  if (!activeVolume.value || !bookStore.currentBookId) return;
  activeVolume.value.chapters = reorderedChapters;
  await saveActiveVolumeChapterOrder();
}

async function saveActiveVolumeChapterOrder() {
  if (!activeVolume.value || !bookStore.currentBookId) return;
  workspaceStore.setSavingChapterOrder(true);
  const targetVolumeId = activeVolume.value.is_virtual ? null : activeVolume.value.id;
  try {
    await Promise.all(activeVolumeChapters.value.map((chapter, index) =>
      api.patch(`/workspace/chapters/${chapter.id}/move`, {
        target_volume_id: targetVolumeId,
        sort_order: index + 1,
      }),
    ));
    await bookStore.fetchBook(bookStore.currentBookId);
    ElMessage.success('章节顺序已更新');
  } catch {
    await bookStore.fetchBook(bookStore.currentBookId);
    ElMessage.error('章节排序保存失败，已恢复服务器顺序');
  } finally {
    workspaceStore.setSavingChapterOrder(false);
  }
}

async function openChapterFromVolume(chapter) {
  if (!chapter?.id) return;
  const tab = bookStore.openChapterTab(chapter.id, chapter.title || `章节 #${chapter.id}`, { bookId: bookStore.currentBookId });
  if (!tab) {
    ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
    return;
  }
  await ensureChapterLoaded(chapter.id);
}

async function onDeleteItem({ kind, id, bookId }) {
  try {
    await ElMessageBox.confirm(
      kind === 'book' ? '删除后将移除该作品及全部章节，不可恢复。确定继续？'
        : `确定删除此${kind === 'volume' ? '分卷' : '章节'}？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    );
    if (kind === 'book') {
      await bookStore.deleteBook(id);
      bookStore.closeLayerTab(bookStore.makeLayerTabKey('book', id));
      workspaceStore.setDrawerSelectionKind('none');
    }
    else if (kind === 'volume') {
      await bookStore.deleteVolume(id);
      bookStore.closeLayerTab(bookStore.makeLayerTabKey('volume', id, { bookId }));
      if (bookId) await bookStore.fetchBook(bookId, { force: true });
      await activateCurrentTabAfterClose();
    } else {
      await api.delete(`/workspace/chapters/${id}`);
      clearChapterSaveTimer(id);
      bookStore.closeChapterTab(id);
      if (bookId) await bookStore.fetchBook(bookId, { force: true });
      await activateCurrentTabAfterClose();
    }
    ElMessage.success('已删除');
  } catch { /* cancelled */ }
}

async function onRenameItem({ kind, id }) {
  try {
    const { value: name } = await ElMessageBox.prompt('新名称', '重命名', {
      confirmButtonText: '确定', inputPattern: /\S+/,
    });
    if (!name) return;
    if (kind === 'book') await bookStore.renameBook(id, name);
    else if (kind === 'volume') {
      await api.patch(`/workspace/volumes/${id}`, { title: name });
      bookStore.updateLayerTabTitle(bookStore.makeLayerTabKey('volume', id, { bookId: bookStore.currentBookId }), name);
    } else {
      await api.patch(`/workspace/chapters/${id}`, { title: name });
      bookStore.updateTabTitle(id, name);
    }
    if (bookStore.currentBook?.id) await bookStore.fetchBook(bookStore.currentBookId);
    ElMessage.success('已重命名');
  } catch { /* cancelled */ }
}

// ========== 章节保存 ==========

const chapterSaveTimers = new Map();

function normalizeParagraphSpacing(value) {
  const lines = String(value || '').replace(/\r\n?/g, '\n').split('\n');
  const output = [];
  for (let index = 0; index < lines.length; index += 1) {
    output.push(lines[index]);
    if (index >= lines.length - 1) continue;
    if (!lines[index].trim()) continue;

    let nextTextLineIndex = index + 1;
    while (nextTextLineIndex < lines.length && !lines[nextTextLineIndex].trim()) {
      nextTextLineIndex += 1;
    }
    if (nextTextLineIndex < lines.length && lines[nextTextLineIndex].trim()) {
      output.push('');
      index = nextTextLineIndex - 1;
    }
  }
  return output.join('\n');
}

function clearChapterSaveTimer(chapterId) {
  const timer = chapterSaveTimers.get(chapterId);
  if (timer) clearTimeout(timer);
  chapterSaveTimers.delete(chapterId);
}

function scheduleChapterSave(chapterId, delay = 3000) {
  clearChapterSaveTimer(chapterId);
  chapterSaveTimers.set(chapterId, setTimeout(() => {
    chapterSaveTimers.delete(chapterId);
    onSaveChapter(chapterId, { silent: true });
  }, delay));
}

function onActiveChapterContentInput(value) {
  const chapterId = bookStore.activeChapterId;
  if (!chapterId) return;
  bookStore.updateTabContent(chapterId, value);
}

async function onSaveChapter(chapterId = bookStore.activeChapterId, { silent = false } = {}) {
  if (!chapterId) return;
  const tab = bookStore.getChapterTab(chapterId);
  if (!tab?.loaded) return;
  clearChapterSaveTimer(chapterId);
  const normalizedContent = normalizeParagraphSpacing(tab.content || '');
  if (normalizedContent !== tab.content) {
    bookStore.updateTabContent(chapterId, normalizedContent);
  }
  try {
    await api.patch(`/workspace/chapters/${chapterId}`, {
      content: normalizedContent,
    });
    bookStore.markTabClean(chapterId, normalizedContent);
    if (!silent) ElMessage.success('已保存');
  } catch {
    ElMessage.error('保存失败');
  }
}

async function onRevertChapter() {
  const chapterId = bookStore.activeChapterId;
  if (!chapterId) return;
  const tab = bookStore.getChapterTab(chapterId);
  if (!tab?.dirty) return;
  try {
    await ElMessageBox.confirm(
      '这会删除当前章节所有未保存变动，恢复到最后一次保存的正文。确定继续？',
      '回退未保存变动',
      { type: 'warning', confirmButtonText: '回退', cancelButtonText: '取消' },
    );
    clearChapterSaveTimer(chapterId);
    bookStore.revertTabContent(chapterId);
    ElMessage.success('已回退到最后一次保存');
  } catch { /* cancelled */ }
}

async function onDetectAiProbability() {
  if (!authStore.requireAiAccess()) return;
  const chapterId = bookStore.activeChapterId;
  if (!chapterId) return;
  const content = activeChapterContent.value || '';
  if (!content.trim()) {
    ElMessage.warning('当前章节没有正文');
    return;
  }
  try {
    emit('lingshu:ai-probability-started', { chapterId });
    const { data } = await api.post(`/workspace/chapters/${chapterId}/ai-probability`, { content });
    const probability = Number(data.probability || 0);
    const level = data.level || 'none';
    bookStore.updateTabAiProbability(chapterId, probability, level);
    ElMessage.success(`AI 率检测完成：${probability}%（${level}）`);
    emit('lingshu:drawer-tab', { name: 'analysis' });
    emit('lingshu:ai-probability-updated', { chapterId, probability, level, item: data.item || null });
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || 'AI 率检测失败');
    emit('lingshu:ai-probability-failed', { chapterId, message: e.response?.data?.detail || e.message || 'AI 率检测失败' });
  }
}

function invokeContentEditor(action) {
  const editor = contentEditorRef.value;
  const handler = editor?.[action];
  if (typeof handler === 'function') handler();
}

function publishChapterToolbarState() {
  emit('lingshu:chapter-toolbar-state', {
    visible: activeLayerKind.value === 'chapter' && Boolean(bookStore.activeChapterId),
    hasContent: hasActiveChapterContent.value,
    dirty: activeChapterDirty.value,
    title: activeChapterTitle.value,
  });
}

function onChapterToolbarAction(event) {
  const action = event?.action;
  if (activeLayerKind.value !== 'chapter') return;
  if (action === 'polish') invokeContentEditor('onPolish');
  else if (action === 'detect-ai') onDetectAiProbability();
  else if (action === 'save') onSaveChapter();
  else if (action === 'revert') onRevertChapter();
  else if (action === 'copy') invokeContentEditor('copyChapter');
  else if (action === 'correction') invokeContentEditor('openCorrection');
  else if (action === 'search') invokeContentEditor('openSearch');
  else if (action === 'edit') openChapterEditDialog();
}

function openChapterEditDialog() {
  if (activeLayerKind.value !== 'chapter' || !bookStore.activeChapterId) return;
  showChapterEditDialog.value = true;
}

function onChapterContentChange(value) {
  const chapterId = bookStore.activeChapterId;
  if (!chapterId) return;
  if (typeof value === 'string') bookStore.updateTabContent(chapterId, value);
  bookStore.markTabDirty(chapterId, true);
  scheduleChapterSave(chapterId);
}

async function onGlobalSave() {
  if (activeLayerKind.value === 'chapter') {
    await onSaveChapter();
    return;
  }
  if (activeLayerKind.value === 'book' && bookStore.currentBookId) {
    await saveOutlineNow();
    return;
  }
  ElMessage.info('暂无可保存内容');
}

// ========== 大纲编辑 ==========

let _outlineTimer = null;

async function loadOutline(bookId) {
  if (!bookId) return;
  try {
    const { data } = await api.get(`/workspace/books/${bookId}/outline`);
    workspaceStore.setOutlineData(data.outline_data || {});
    workspaceStore.setOutlineSchema(data.outline_schema || []);
    if (bookStore.currentBook && bookStore.currentBook.id === bookId) {
      bookStore.setOutlineText(data.outline_text || '');
    }
  } catch (e) {
    workspaceStore.setOutlineData({});
    workspaceStore.setOutlineSchema([]);
    if (e.response?.status === 401) {
      ElMessage.error('登录已过期，请重新登录');
    } else if (e.response?.status === 404) {
      ElMessage.warning('该书籍尚无大纲');
    } else {
      ElMessage.error('加载大纲失败，请检查网络后重试');
    }
  }
}

function onOutlineDataChange(value) {
  workspaceStore.setOutlineData(value || {});
}

function onOutlineChanged() {
  clearTimeout(_outlineTimer);
  _outlineTimer = setTimeout(saveOutlineNow, 5000);
}

async function saveOutlineNow() {
  if (!bookStore.currentBookId || !bookStore.currentBook) return;
  const { data } = await api.put(`/workspace/books/${bookStore.currentBookId}/outline`, {
    outline_data: workspaceStore.activeOutlineData || {},
  });
  bookStore.setOutlineText(data.outline_text || '');
  workspaceStore.setOutlineData(data.outline_data || workspaceStore.activeOutlineData || {});
  workspaceStore.setOutlineSchema(data.outline_schema || workspaceStore.activeOutlineSchema || []);
  ElMessage.success('大纲已保存');
}

// ========== 导入 ==========

async function onFileImported(result) {
  const bookId = Number(result?.book_id || result?.item?.id || 0);
  try {
    await bookStore.fetchBooks();
    if (!bookId) return;
    const book = await bookStore.fetchBook(bookId);
    const tab = bookStore.openLayerTab('book', bookId, book?.title || result?.item?.title || '未命名');
    if (!tab) {
      ElMessage.warning(`最多同时打开 ${bookStore.maxOpenChapterTabs} 个层级卡片，请先保存或关闭一个标签`);
      return;
    }
    await loadOutline(bookId);
    workspaceStore.setEditorMode('outline');
    workspaceStore.setDrawerSelectionKind('book');
    await nextTick();
    libraryPanelRef.value?.jumpToBook?.(bookId);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '导入成功，但刷新作品列表失败');
  }
}

function onGlobalImport() {
  openBookEntry('import');
}

function onReferenceClick() {
  emit('lingshu:reference');
}

// ========== 面板尺寸 ==========

function onResized(panes) {
  panes.forEach((p, i) => {
    if (i === 0) leftSize.value = p.size;
    if (i === 1) centerSize.value = p.size;
    if (i === 2) rightSize.value = p.size;
  });
  localStorage.setItem('lingshu_left_width', String(Math.round(leftSize.value)));
  localStorage.setItem('lingshu_right_width', String(Math.round(rightSize.value)));
}

function onViewSettingsUpdated(event) {
  const sizes = normalizePaneSettings(event?.leftWidth, event?.rightWidth);
  leftSize.value = sizes.left;
  centerSize.value = sizes.center;
  rightSize.value = sizes.right;
}

function readPaneSettings() {
  return normalizePaneSettings(
    Number.parseInt(localStorage.getItem('lingshu_left_width') || '22', 10),
    Number.parseInt(localStorage.getItem('lingshu_right_width') || '28', 10),
  );
}

function normalizePaneSettings(left, right) {
  let safeLeft = clamp(Number(left), 18, 35);
  let safeRight = clamp(Number(right), 20, 40);
  if (safeLeft + safeRight > 70) {
    safeRight = 70 - safeLeft;
  }
  return {
    left: safeLeft,
    center: Math.max(30, 100 - safeLeft - safeRight),
    right: safeRight,
  };
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}
</script>

<style scoped>
.workspace-container {
  height: 100%;
  overflow: hidden;
  background: var(--bg-secondary);
}

.center-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
}

.editor-area {
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
