<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import axios from 'axios';
import { ElMessage, ElMessageBox } from 'element-plus';
import { ArrowLeft, Delete, Download, EditPen, Plus, Search, Tickets, Upload } from '@element-plus/icons-vue';
import { useAuth } from '../stores/auth';

const props = defineProps<{ bookId: string }>();
const router = useRouter();
const auth = useAuth();

interface AuthorBook {
  id: number;
  title: string;
  updated_at: string;
}

interface AuthorChapter {
  id: number;
  book_id: number;
  volume_title: string;
  title: string;
  outline: string;
  summary_text: string;
  sort_order: number;
  word_count: number;
  status: 'draft' | 'published' | 'reviewing' | 'returned' | 'rejected' | string;
  published_at: string;
  updated_at: string;
}

interface AuthorChapterDetail extends AuthorChapter {
  book_title: string;
  content: string;
}

const pageSize = 20;
const loading = ref(true);
const creatingNext = ref(false);
const exportingId = ref<number | null>(null);
const publishingId = ref<number | null>(null);
const currentBook = ref<AuthorBook | null>(null);
const chapters = ref<AuthorChapter[]>([]);
const sortDirection = ref<'asc' | 'desc'>('asc');
const displayMode = ref<'page' | 'volume'>('page');
const searchKeyword = ref('');
const searchScope = ref<'title' | 'content'>('title');
const contentSearchMatches = ref<Set<number> | null>(null);
const contentSearchLoading = ref(false);
const currentPage = ref(1);
const chapterContentCache = new Map<number, string>();
let contentSearchRequestId = 0;

const bookIdNumber = computed(() => Number(props.bookId));
const bookTitle = computed(() => currentBook.value?.title || `作品 ${props.bookId}`);
const sortedChapters = computed(() => {
  const direction = sortDirection.value === 'asc' ? 1 : -1;
  return [...chapters.value].sort((a, b) => {
    const orderDiff = (Number(a.sort_order || 0) - Number(b.sort_order || 0)) * direction;
    if (orderDiff !== 0) return orderDiff;
    return (Number(a.id) - Number(b.id)) * direction;
  });
});
const volumeTitle = computed(() => sortedChapters.value[0]?.volume_title || '正文');
const displayModeLabel = computed(() => (displayMode.value === 'page' ? '分页' : '按卷'));
const sortDirectionLabel = computed(() => (sortDirection.value === 'asc' ? '正序' : '倒序'));
const searchScopeLabel = computed(() => (searchScope.value === 'title' ? '章节名' : '正文'));
const normalizedSearch = computed(() => searchKeyword.value.trim().toLowerCase());
const filteredChapters = computed(() => {
  const keyword = normalizedSearch.value;
  if (!keyword) return sortedChapters.value;
  if (searchScope.value === 'title') {
    return sortedChapters.value.filter((chapter) => chapter.title.toLowerCase().includes(keyword));
  }
  if (!contentSearchMatches.value) return [];
  return sortedChapters.value.filter((chapter) => contentSearchMatches.value?.has(chapter.id));
});
const volumeGroups = computed(() => {
  const groups: Array<{ title: string; chapters: AuthorChapter[] }> = [];
  const groupMap = new Map<string, AuthorChapter[]>();
  for (const chapter of filteredChapters.value) {
    const title = chapter.volume_title || '正文';
    if (!groupMap.has(title)) {
      groupMap.set(title, []);
      groups.push({ title, chapters: groupMap.get(title)! });
    }
    groupMap.get(title)!.push(chapter);
  }
  return groups;
});
const pageCount = computed(() => Math.max(1, Math.ceil(filteredChapters.value.length / pageSize)));
const pagedChapters = computed(() => {
  const start = (currentPage.value - 1) * pageSize;
  return filteredChapters.value.slice(start, start + pageSize);
});

function authHeaders() {
  return { Authorization: `Bearer ${auth.token}` };
}

function formatDate(value: string): string {
  if (!value) return '未发布';
  return value.replace('T', ' ').slice(0, 16);
}

function formatPublishDate(chapter: AuthorChapter): string {
  if (chapter.status === 'published') return formatDate(chapter.published_at);
  if (chapter.status === 'reviewing') return '审核中';
  return '未发布';
}

function safeFileName(value: string): string {
  return (value || '章节').replace(/[\\/:*?"<>|]/g, '_').slice(0, 80);
}

function chapterStatusLabel(status: string): string {
  if (status === 'published') return '已发布';
  if (status === 'reviewing') return '审核中';
  if (status === 'returned' || status === 'rejected') return '已退回';
  return '未发布';
}

function statusClass(status: string): string {
  if (status === 'published') return 'published';
  if (status === 'reviewing') return 'reviewing';
  if (status === 'returned' || status === 'rejected') return 'returned';
  return 'draft';
}

function publishButtonText(chapter: AuthorChapter): string {
  if (chapter.status === 'published') return '已发布';
  if (chapter.status === 'reviewing') return '审核中';
  return '发布';
}

function canPublishChapter(chapter: AuthorChapter): boolean {
  return chapter.status !== 'published' && chapter.status !== 'reviewing';
}

function toggleDisplayMode() {
  displayMode.value = displayMode.value === 'page' ? 'volume' : 'page';
  currentPage.value = 1;
}

function toggleSortDirection() {
  sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc';
  currentPage.value = 1;
}

function toggleSearchScope() {
  searchScope.value = searchScope.value === 'title' ? 'content' : 'title';
  currentPage.value = 1;
}

async function runContentSearch() {
  const keyword = normalizedSearch.value;
  const requestId = ++contentSearchRequestId;
  if (searchScope.value !== 'content' || !keyword) {
    contentSearchMatches.value = null;
    contentSearchLoading.value = false;
    return;
  }

  contentSearchLoading.value = true;
  try {
    const matches = new Set<number>();
    await Promise.all(chapters.value.map(async (chapter) => {
      let content = chapterContentCache.get(chapter.id);
      if (content === undefined) {
        const res = await axios.get(`/api/author/books/${bookIdNumber.value}/chapters/${chapter.id}`, {
          headers: authHeaders(),
        });
        content = String((res.data as AuthorChapterDetail).content || '');
        chapterContentCache.set(chapter.id, content);
      }
      if (content.toLowerCase().includes(keyword)) {
        matches.add(chapter.id);
      }
    }));
    if (requestId === contentSearchRequestId) {
      contentSearchMatches.value = matches;
    }
  } catch (e: any) {
    if (requestId === contentSearchRequestId) {
      contentSearchMatches.value = new Set();
      ElMessage.error(e?.response?.data?.detail || '正文搜索失败');
    }
  } finally {
    if (requestId === contentSearchRequestId) {
      contentSearchLoading.value = false;
    }
  }
}

async function loadBooks() {
  const res = await axios.get('/api/author/books', { headers: authHeaders() });
  const items = (res.data.items || []) as AuthorBook[];
  currentBook.value = items.find((item) => item.id === bookIdNumber.value) || null;
  if (!currentBook.value) {
    throw new Error('作品不存在');
  }
}

async function loadChapters() {
  const res = await axios.get(`/api/author/books/${bookIdNumber.value}/chapters`, {
    headers: authHeaders(),
  });
  chapters.value = res.data.items || [];
  chapterContentCache.clear();
  contentSearchMatches.value = null;
  void runContentSearch();
  if (currentPage.value > pageCount.value) {
    currentPage.value = pageCount.value;
  }
}

async function load() {
  if (!auth.token) {
    auth.openLogin();
    loading.value = false;
    return;
  }
  if (!Number.isFinite(bookIdNumber.value) || bookIdNumber.value <= 0) {
    await router.replace('/profile');
    return;
  }

  loading.value = true;
  try {
    await Promise.all([loadBooks(), loadChapters()]);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '无法读取章节列表');
    await router.replace('/profile');
  } finally {
    loading.value = false;
  }
}

async function createNextChapter() {
  if (!auth.token) {
    auth.openLogin();
    return;
  }
  creatingNext.value = true;
  try {
    const res = await axios.post(`/api/author/books/${bookIdNumber.value}/chapters/next`, {}, {
      headers: authHeaders(),
    });
    const item = res.data.item as AuthorChapterDetail;
    ElMessage.success('已创建下一章草稿');
    await router.push(`/profile/books/${bookIdNumber.value}/chapters/${item.id}/edit`);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建章节失败');
  } finally {
    creatingNext.value = false;
  }
}

async function exportChapter(chapter: AuthorChapter) {
  exportingId.value = chapter.id;
  try {
    const res = await axios.get(`/api/author/books/${bookIdNumber.value}/chapters/${chapter.id}`, {
      headers: authHeaders(),
    });
    const detail = res.data as AuthorChapterDetail;
    const text = [
      detail.book_title || bookTitle.value,
      detail.volume_title || '正文',
      detail.title,
      '',
      detail.content || '',
    ].join('\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${safeFileName(bookTitle.value)}-${safeFileName(detail.title)}.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '导出失败');
  } finally {
    exportingId.value = null;
  }
}

async function publishChapter(chapter: AuthorChapter) {
  if (!canPublishChapter(chapter)) return;
  publishingId.value = chapter.id;
  try {
    const res = await axios.post(
      `/api/author/books/${bookIdNumber.value}/chapters/${chapter.id}/publish`,
      {},
      { headers: authHeaders() },
    );
    const item = res.data.item as AuthorChapter;
    chapters.value = chapters.value.map((current) => (current.id === item.id ? { ...current, ...item } : current));
    ElMessage.success('章节已发布');
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '发布失败');
  } finally {
    publishingId.value = null;
  }
}

function editChapter(chapter: AuthorChapter) {
  router.push(`/profile/books/${bookIdNumber.value}/chapters/${chapter.id}/edit`);
}

async function deleteChapter(chapter: AuthorChapter) {
  try {
    await ElMessageBox.confirm(`确认删除《${chapter.title}》？`, '删除章节', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    });
  } catch {
    return;
  }

  try {
    await axios.delete(`/api/author/books/${bookIdNumber.value}/chapters/${chapter.id}`, {
      headers: authHeaders(),
    });
    ElMessage.success('章节已删除');
    await loadChapters();
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败');
  }
}

onMounted(load);
watch(() => props.bookId, () => {
  currentPage.value = 1;
  void load();
});
watch([filteredChapters, currentPage], () => {
  if (currentPage.value > pageCount.value) {
    currentPage.value = pageCount.value;
  }
});
watch([normalizedSearch, searchScope], () => {
  currentPage.value = 1;
  void runContentSearch();
});
</script>

<template>
  <section v-loading="loading" class="chapter-manage-page">
    <header class="chapter-header">
      <div class="chapter-header-main">
        <el-button :icon="ArrowLeft" text @click="router.push(`/profile/books/${props.bookId}`)">
          返回作品
        </el-button>
        <div class="chapter-title-block">
          <span class="chapter-kicker">章节管理</span>
          <h1>
            {{ bookTitle }}
            <small>/ {{ volumeTitle }}</small>
          </h1>
        </div>
      </div>

      <div class="chapter-header-actions">
        <el-button type="primary" :icon="Plus" :loading="creatingNext" @click="createNextChapter">
          新建下一章
        </el-button>
      </div>
    </header>

    <section class="chapter-list-panel">
      <div class="chapter-list-summary">
        <div class="chapter-summary-left">
          <el-icon><Tickets /></el-icon>
          <span>共 {{ filteredChapters.length }} 章</span>
          <el-button class="summary-toggle" size="small" plain @click="toggleDisplayMode">
            {{ displayModeLabel }}
          </el-button>
        </div>
        <div class="chapter-list-controls">
          <div class="chapter-search">
            <el-input
              v-model="searchKeyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜索章节"
            />
            <el-button
              class="summary-toggle search-scope-toggle"
              plain
              :loading="contentSearchLoading"
              @click="toggleSearchScope"
            >
              {{ searchScopeLabel }}
            </el-button>
          </div>
          <el-button class="summary-toggle" plain @click="toggleSortDirection">
            {{ sortDirectionLabel }}
          </el-button>
        </div>
      </div>

      <el-empty v-if="!loading && chapters.length === 0" description="暂无章节">
        <el-button type="primary" :icon="Plus" :loading="creatingNext" @click="createNextChapter">
          新建第一章
        </el-button>
      </el-empty>

      <template v-else>
        <el-empty
          v-if="filteredChapters.length === 0"
          :description="contentSearchLoading ? '正在搜索正文' : '没有匹配章节'"
        />

        <template v-else-if="displayMode === 'page'">
          <div class="chapter-list-head" aria-hidden="true">
            <span>序号</span>
            <span>章节名</span>
            <span>状态</span>
            <span>发布时间</span>
            <span>操作</span>
          </div>

          <div class="chapter-list">
            <article v-for="chapter in pagedChapters" :key="chapter.id" class="chapter-row">
              <span class="chapter-index">#{{ chapter.sort_order || chapter.id }}</span>
              <strong>{{ chapter.title }}</strong>
              <span class="chapter-status" :class="statusClass(chapter.status)">
                {{ chapterStatusLabel(chapter.status) }}
              </span>
              <span class="chapter-time">{{ formatPublishDate(chapter) }}</span>
              <div class="chapter-row-actions">
                <el-button
                  class="publish-action"
                  :class="{ publishable: canPublishChapter(chapter) }"
                  text
                  type="primary"
                  :icon="Upload"
                  :disabled="!canPublishChapter(chapter)"
                  :loading="publishingId === chapter.id"
                  @click="publishChapter(chapter)"
                >
                  {{ publishButtonText(chapter) }}
                </el-button>
                <el-button
                  text
                  :icon="Download"
                  :loading="exportingId === chapter.id"
                  @click="exportChapter(chapter)"
                >
                  导出
                </el-button>
                <el-button text :icon="EditPen" @click="editChapter(chapter)">编辑</el-button>
                <el-button text type="danger" :icon="Delete" @click="deleteChapter(chapter)">删除</el-button>
              </div>
            </article>
          </div>

          <div v-if="filteredChapters.length > pageSize" class="chapter-pagination">
            <el-pagination
              v-model:current-page="currentPage"
              background
              layout="prev, pager, next"
              :page-size="pageSize"
              :total="filteredChapters.length"
            />
          </div>
        </template>

        <div v-else class="volume-list">
          <section v-for="group in volumeGroups" :key="group.title" class="volume-section">
            <div class="volume-heading">
              <strong>{{ group.title }}</strong>
              <span>{{ group.chapters.length }} 章</span>
            </div>
            <div class="chapter-list-head" aria-hidden="true">
              <span>序号</span>
              <span>章节名</span>
              <span>状态</span>
              <span>发布时间</span>
              <span>操作</span>
            </div>
            <div class="chapter-list">
              <article v-for="chapter in group.chapters" :key="chapter.id" class="chapter-row">
                <span class="chapter-index">#{{ chapter.sort_order || chapter.id }}</span>
                <strong>{{ chapter.title }}</strong>
                <span class="chapter-status" :class="statusClass(chapter.status)">
                  {{ chapterStatusLabel(chapter.status) }}
                </span>
                <span class="chapter-time">{{ formatPublishDate(chapter) }}</span>
                <div class="chapter-row-actions">
                  <el-button
                    class="publish-action"
                    :class="{ publishable: canPublishChapter(chapter) }"
                    text
                    type="primary"
                    :icon="Upload"
                    :disabled="!canPublishChapter(chapter)"
                    :loading="publishingId === chapter.id"
                    @click="publishChapter(chapter)"
                  >
                    {{ publishButtonText(chapter) }}
                  </el-button>
                  <el-button
                    text
                    :icon="Download"
                    :loading="exportingId === chapter.id"
                    @click="exportChapter(chapter)"
                  >
                    导出
                  </el-button>
                  <el-button text :icon="EditPen" @click="editChapter(chapter)">编辑</el-button>
                  <el-button text type="danger" :icon="Delete" @click="deleteChapter(chapter)">删除</el-button>
                </div>
              </article>
            </div>
          </section>
        </div>
      </template>
    </section>
  </section>
</template>

<style scoped>
.chapter-manage-page {
  width: min(100% - 32px, 1180px);
  margin: 0 auto;
  padding: 32px 0 72px;
}

.chapter-header,
.chapter-list-panel {
  border: 1px solid rgba(184, 202, 216, 0.76);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 10px 28px rgba(26, 45, 61, 0.07);
}

.chapter-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
  padding: 20px 22px;
}

.chapter-header-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 14px;
}

.chapter-title-block {
  min-width: 0;
}

.chapter-kicker {
  color: #2F86B6;
  font-size: 12px;
  font-weight: 850;
}

.chapter-title-block h1 {
  margin: 5px 0 0;
  color: #12283A;
  font-size: 28px;
  font-weight: 900;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.chapter-title-block small {
  color: #5E7487;
  font-size: 18px;
  font-weight: 800;
}

.chapter-header-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.chapter-list-panel {
  padding: 18px;
}

.chapter-list-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  color: #5E7487;
  font-size: 13px;
  font-weight: 800;
}

.chapter-summary-left,
.chapter-list-controls {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.chapter-list-controls {
  justify-content: flex-end;
}

.chapter-search {
  display: grid;
  grid-template-columns: minmax(180px, 260px) auto;
  gap: 8px;
  align-items: center;
}

.chapter-search :deep(.el-input__wrapper) {
  border-radius: 6px;
}

.summary-toggle {
  min-width: 62px;
  font-weight: 850;
}

.search-scope-toggle {
  min-width: 76px;
}

.chapter-list-summary .el-icon {
  color: #2F86B6;
  font-size: 18px;
}

.volume-list {
  display: grid;
  gap: 16px;
}

.volume-section {
  overflow: hidden;
  border: 1px solid rgba(184, 202, 216, 0.58);
  border-radius: 8px;
  background: rgba(248, 251, 253, 0.58);
}

.volume-heading {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 14px;
  color: #5E7487;
  background: rgba(47, 134, 182, 0.08);
  font-size: 13px;
  font-weight: 850;
}

.volume-heading strong {
  color: #12283A;
  font-size: 15px;
  font-weight: 900;
}

.chapter-list-head,
.chapter-row {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr) 96px 142px 380px;
  gap: 12px;
  align-items: center;
}

.chapter-list-head {
  min-height: 36px;
  padding: 0 14px;
  border-bottom: 1px solid rgba(184, 202, 216, 0.6);
  color: #6E8395;
  font-size: 12px;
  font-weight: 900;
}

.chapter-list {
  display: grid;
}

.chapter-row {
  min-height: 62px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(184, 202, 216, 0.42);
}

.chapter-row:last-child {
  border-bottom: 0;
}

.chapter-row strong {
  min-width: 0;
  overflow: hidden;
  color: #12283A;
  font-size: 15px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-index {
  color: #2F86B6;
  font-weight: 900;
}

.chapter-status {
  display: inline-flex;
  width: fit-content;
  min-height: 24px;
  align-items: center;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.chapter-status.draft {
  color: #6E8395;
  background: rgba(110, 131, 149, 0.13);
}

.chapter-status.published {
  color: #1F7A55;
  background: rgba(84, 214, 148, 0.17);
}

.chapter-status.reviewing {
  color: #9A6A00;
  background: rgba(245, 188, 83, 0.2);
}

.chapter-status.returned {
  color: #B42318;
  background: rgba(244, 63, 94, 0.13);
}

.chapter-time {
  color: #6E8395;
  font-size: 13px;
}

.chapter-row-actions {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px 8px;
}

.chapter-row-actions :deep(.el-button) {
  min-width: 0;
  margin-left: 0;
  padding: 0 4px;
}

.chapter-row-actions :deep(.publish-action.publishable) {
  min-width: 58px;
  height: 28px;
  padding: 0 10px;
  border-radius: 6px;
  color: #FFFFFF;
  background: #1A8FC4;
}

.chapter-row-actions :deep(.publish-action.publishable:hover),
.chapter-row-actions :deep(.publish-action.publishable:focus-visible) {
  color: #FFFFFF;
  background: #167EAD;
}

.chapter-row-actions :deep(.publish-action.is-disabled) {
  color: #8AA2B6;
}

.chapter-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 18px;
}

@media (max-width: 860px) {
  .chapter-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .chapter-header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .chapter-list-summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .chapter-list-controls {
    width: 100%;
    justify-content: flex-start;
  }

  .chapter-search {
    width: 100%;
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .chapter-list-head {
    display: none;
  }

  .chapter-list {
    gap: 10px;
  }

  .chapter-row {
    grid-template-columns: 72px minmax(0, 1fr);
    gap: 8px 12px;
    min-height: 0;
    border: 1px solid rgba(184, 202, 216, 0.58);
    border-radius: 8px;
    background: rgba(248, 251, 253, 0.7);
  }

  .chapter-time {
    grid-column: 2;
  }

  .chapter-row strong {
    grid-column: 1 / -1;
  }

  .chapter-row-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}

@media (max-width: 560px) {
  .chapter-manage-page {
    width: min(100% - 24px, 1180px);
    padding-top: 24px;
  }

  .chapter-header,
  .chapter-list-panel {
    padding: 16px;
  }

  .chapter-header-main {
    align-items: flex-start;
    flex-direction: column;
  }

  .chapter-title-block h1 {
    font-size: 24px;
  }

  .chapter-title-block small {
    font-size: 16px;
  }

  .chapter-header-actions {
    flex-direction: column;
  }

  .chapter-header-actions :deep(.el-button-group),
  .chapter-header-actions :deep(.el-button) {
    width: 100%;
  }

  .chapter-list-controls {
    flex-direction: column;
  }

  .chapter-list-controls > .summary-toggle,
  .chapter-search {
    width: 100%;
  }

  .chapter-search {
    grid-template-columns: minmax(0, 1fr);
  }

  .search-scope-toggle {
    width: 100%;
  }

  .chapter-row {
    grid-template-columns: 1fr;
    padding: 14px;
  }

  .chapter-time,
  .chapter-row-actions {
    grid-column: auto;
  }

  .chapter-row strong {
    white-space: normal;
    line-height: 1.45;
  }

  .chapter-status,
  .chapter-time {
    justify-self: start;
  }

  .chapter-row-actions {
    display: grid;
    width: 100%;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .chapter-row-actions :deep(.el-button) {
    width: 100%;
    justify-content: center;
    padding: 0 8px;
  }

  .chapter-row-actions :deep(.publish-action.publishable) {
    min-width: 0;
  }

  .chapter-pagination {
    justify-content: center;
    overflow-x: auto;
  }
}
</style>
