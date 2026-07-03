<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  Collection,
  Delete,
  Plus,
  Reading,
  Refresh,
  Search,
  View,
} from '@element-plus/icons-vue';
import { createBookshelfShelf, fetchBookshelf, fetchBookshelfShelves, removeBookshelfItem } from '../api';
import { useAuth } from '../stores/auth';
import type { BookshelfItem, BookshelfShelf } from '../types';

const auth = useAuth();
const router = useRouter();

const loading = ref(false);
const removingId = ref<number | null>(null);
const keyword = ref('');
const sortMode = ref<'recent' | 'progress'>('recent');
const items = ref<BookshelfItem[]>([]);
const shelves = ref<BookshelfShelf[]>([]);
const selectedShelfId = ref<number | null>(null);

const filteredItems = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  const source = text
    ? items.value.filter((item) =>
        [item.title, item.summary, item.category, item.sub_tags]
          .some((value) => String(value || '').toLowerCase().includes(text)),
      )
    : [...items.value];
  return source.sort((a, b) => {
    if (sortMode.value === 'progress') {
      return Number(b.progress_percent || 0) - Number(a.progress_percent || 0);
    }
    return String(b.shelf_updated_at || '').localeCompare(String(a.shelf_updated_at || ''));
  });
});

const sortLabel = computed(() => (sortMode.value === 'recent' ? '最近阅读' : '阅读进度'));
const selectedShelf = computed(() =>
  shelves.value.find((item) => item.id === selectedShelfId.value) || shelves.value[0] || null,
);

function authToken() {
  return auth.token;
}

function firstChar(value: string): string {
  return value.trim().slice(0, 1) || '书';
}

function formatDate(value: string): string {
  if (!value) return '暂无记录';
  return value.replace('T', ' ').slice(0, 16);
}

function tagList(item: BookshelfItem): string[] {
  const tags = new Set<string>();
  if (item.category && item.category !== '本地上传') tags.add(item.category);
  for (const tag of String(item.sub_tags || '').split(',')) {
    const clean = tag.trim();
    if (clean) tags.add(clean);
  }
  return [...tags].slice(0, 3);
}

async function loadBookshelf() {
  if (!authToken()) {
    items.value = [];
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    items.value = await fetchBookshelf(authToken(), selectedShelfId.value);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '无法读取书箱');
  } finally {
    loading.value = false;
  }
}

async function loadShelves() {
  if (!authToken()) {
    shelves.value = [];
    selectedShelfId.value = null;
    return;
  }
  shelves.value = await fetchBookshelfShelves(authToken());
  if (!selectedShelfId.value || !shelves.value.some((item) => item.id === selectedShelfId.value)) {
    selectedShelfId.value = shelves.value[0]?.id || null;
  }
}

async function loadAll() {
  if (!authToken()) {
    items.value = [];
    shelves.value = [];
    selectedShelfId.value = null;
    return;
  }
  loading.value = true;
  try {
    await loadShelves();
    items.value = await fetchBookshelf(authToken(), selectedShelfId.value);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '无法读取书箱');
  } finally {
    loading.value = false;
  }
}

function toggleSortMode() {
  sortMode.value = sortMode.value === 'recent' ? 'progress' : 'recent';
}

async function handleShelfCommand(command: string) {
  if (command === 'add') {
    await createShelf();
    return;
  }
  const id = Number(command.replace('shelf:', ''));
  if (!Number.isFinite(id) || id === selectedShelfId.value) return;
  selectedShelfId.value = id;
  await loadBookshelf();
}

async function createShelf() {
  try {
    const { value } = await ElMessageBox.prompt('给新书箱取一个名字', '添加新书箱', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：追更中',
      inputPattern: /\S+/,
      inputErrorMessage: '请填写书箱名称',
    });
    const shelf = await createBookshelfShelf(String(value || '').trim(), authToken());
    shelves.value = [shelf, ...shelves.value.filter((item) => item.id !== shelf.id)];
    selectedShelfId.value = shelf.id;
    items.value = [];
    ElMessage.success('书箱已创建');
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return;
    ElMessage.error(e?.response?.data?.detail || '创建书箱失败');
  }
}

function continueReading(item: BookshelfItem) {
  const chapterId = item.last_chapter_id || item.first_chapter_id;
  if (!chapterId) return;
  router.push(`/books/${item.id}/chapters/${chapterId}`);
}

async function removeItem(item: BookshelfItem) {
  try {
    await ElMessageBox.confirm(`确认将《${item.title}》移出书箱？`, '移出书箱', {
      type: 'warning',
      confirmButtonText: '移出',
      cancelButtonText: '取消',
    });
  } catch {
    return;
  }

  removingId.value = item.id;
  try {
    await removeBookshelfItem(item.id, authToken());
    items.value = items.value.filter((current) => current.id !== item.id);
    shelves.value = shelves.value.map((shelf) =>
      shelf.id === selectedShelfId.value
        ? { ...shelf, book_count: Math.max(0, Number(shelf.book_count || 0) - 1) }
        : shelf,
    );
    ElMessage.success('已移出书箱');
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移出失败');
  } finally {
    removingId.value = null;
  }
}

onMounted(() => {
  void loadAll();
});
watch(() => auth.token, loadAll);
</script>

<template>
  <section class="bookshelf-page">
    <div v-if="!auth.user" class="bookshelf-login">
      <el-empty description="登录后即可同步你的书箱">
        <el-button type="primary" :icon="Collection" @click="auth.openLogin()">去登录</el-button>
      </el-empty>
    </div>

    <template v-else>
      <header class="bookshelf-header">
        <div>
          <div class="bookshelf-title-row">
            <h1>{{ selectedShelf?.name || '檀墨书箱' }}</h1>
            <el-dropdown trigger="click" @command="handleShelfCommand">
              <button type="button" class="shelf-switch" aria-label="切换书箱">
                <span class="v-mark" />
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="shelf in shelves"
                    :key="shelf.id"
                    :command="`shelf:${shelf.id}`"
                  >
                    {{ shelf.name }} · {{ shelf.book_count }} 本
                  </el-dropdown-item>
                  <el-dropdown-item divided command="add">
                    <el-icon><Plus /></el-icon>
                    添加新书箱
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <p class="bookshelf-count">{{ filteredItems.length }} 本书</p>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
      </header>

      <section class="bookshelf-panel">
        <div class="bookshelf-toolbar">
          <div class="bookshelf-search">
            <el-input
              v-model="keyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜索书名、简介、标签"
            />
          </div>
          <el-button class="sort-toggle" plain @click="toggleSortMode">{{ sortLabel }}</el-button>
        </div>

        <el-empty v-if="!loading && items.length === 0" description="书箱还是空的">
          <el-button type="primary" @click="router.push('/bookstore')">去书库看看</el-button>
        </el-empty>

        <el-empty
          v-else-if="!loading && filteredItems.length === 0"
          description="没有匹配的书籍"
        />

        <div v-else v-loading="loading" class="bookshelf-list">
          <article v-for="item in filteredItems" :key="item.id" class="bookshelf-item">
            <button type="button" class="shelf-cover" @click="router.push(`/books/${item.id}`)">
              <img v-if="item.cover_url" :src="item.cover_url" :alt="item.title" />
              <span v-else>{{ firstChar(item.title) }}</span>
            </button>

            <div class="shelf-main">
              <div class="shelf-title-row">
                <div>
                  <h2>{{ item.title }}</h2>
                  <p>{{ item.summary || '暂无简介' }}</p>
                </div>
                <span class="shelf-progress">{{ item.progress_percent }}%</span>
              </div>

              <div class="shelf-tags" v-if="tagList(item).length">
                <span v-for="tag in tagList(item)" :key="tag">{{ tag }}</span>
              </div>

              <div class="shelf-meta">
                <span>最新：{{ item.latest_chapter_title || '暂无章节' }}</span>
                <span>上次：{{ item.last_chapter_title || '尚未阅读' }}</span>
                <span>更新：{{ formatDate(item.latest_chapter_updated_at || item.updated_at) }}</span>
              </div>

              <el-progress
                :percentage="item.progress_percent"
                :show-text="false"
                :stroke-width="8"
              />

              <div class="shelf-actions">
                <el-button
                  type="primary"
                  :icon="Reading"
                  :disabled="!item.last_chapter_id && !item.first_chapter_id"
                  @click="continueReading(item)"
                >
                  {{ item.last_chapter_id || item.first_chapter_id ? '继续阅读' : '暂无可读章节' }}
                </el-button>
                <el-button :icon="View" @click="router.push(`/books/${item.id}`)">详情</el-button>
                <el-button
                  type="danger"
                  plain
                  :icon="Delete"
                  :loading="removingId === item.id"
                  @click="removeItem(item)"
                >
                  移出
                </el-button>
              </div>
            </div>
          </article>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.bookshelf-page {
  width: min(100% - 32px, 1180px);
  margin: 0 auto;
  padding: 32px 0 72px;
}

.bookshelf-login {
  padding-top: 80px;
}

.bookshelf-header,
.bookshelf-panel,
.bookshelf-item {
  border: 1px solid rgba(184, 202, 216, 0.76);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 10px 28px rgba(26, 45, 61, 0.07);
}

.bookshelf-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 16px;
  padding: 22px 24px;
}

.bookshelf-header h1 {
  margin: 0;
  color: #12283A;
  font-size: 24px;
  font-weight: 900;
  line-height: 1.2;
}

.bookshelf-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 6px;
}

.bookshelf-count {
  margin: 0;
  color: #5E7487;
  font-size: 14px;
  font-weight: 850;
  line-height: 1.45;
}

.shelf-switch {
  display: inline-grid;
  width: 16px;
  height: 18px;
  place-items: center;
  border: 0;
  color: #2F86B6;
  background: transparent;
  cursor: pointer;
  vertical-align: baseline;
}

.shelf-switch:hover,
.shelf-switch:focus-visible {
  color: #167EAD;
  outline: none;
}

.v-mark {
  display: block;
  width: 7px;
  height: 7px;
  border-right: 1.8px solid currentColor;
  border-bottom: 1.8px solid currentColor;
  transform: translateY(-3px) rotate(45deg);
}

.bookshelf-header p {
  margin: 0;
  color: #5E7487;
  font-size: 14px;
}

.bookshelf-panel {
  padding: 18px;
}

.bookshelf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.bookshelf-search {
  width: min(100%, 360px);
}

.sort-toggle {
  min-width: 104px;
  font-weight: 850;
}

.bookshelf-list {
  display: grid;
  gap: 12px;
}

.bookshelf-item {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 18px;
  padding: 14px;
}

.shelf-cover {
  display: grid;
  width: 112px;
  aspect-ratio: 3 / 4;
  place-items: center;
  overflow: hidden;
  border: 0;
  border-radius: 6px;
  background:
    linear-gradient(160deg, rgba(47, 134, 182, 0.18), rgba(119, 220, 204, 0.2)),
    #EAF4FA;
  cursor: pointer;
}

.shelf-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.shelf-cover span {
  color: #2F86B6;
  font-size: 42px;
  font-weight: 900;
}

.shelf-main {
  min-width: 0;
}

.shelf-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.shelf-title-row h2 {
  margin: 0 0 6px;
  color: #12283A;
  font-size: 20px;
  font-weight: 900;
}

.shelf-title-row p {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: #5E7487;
  font-size: 13px;
  line-height: 1.65;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.shelf-progress {
  display: inline-flex;
  min-width: 52px;
  min-height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  color: #1A6F99;
  background: rgba(47, 134, 182, 0.12);
  font-size: 13px;
  font-weight: 900;
}

.shelf-tags,
.shelf-meta,
.shelf-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.shelf-tags {
  margin-top: 10px;
}

.shelf-tags span {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  padding: 0 8px;
  border-radius: 999px;
  color: #1A6F99;
  background: rgba(47, 134, 182, 0.1);
  font-size: 12px;
  font-weight: 800;
}

.shelf-meta {
  margin: 12px 0;
  color: #6E8395;
  font-size: 12px;
  font-weight: 800;
}

.shelf-actions {
  margin-top: 14px;
}

@media (max-width: 760px) {
  .bookshelf-page {
    width: min(100% - 24px, 1180px);
    padding-top: 24px;
  }

  .bookshelf-header,
  .bookshelf-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .bookshelf-search,
  .sort-toggle {
    width: 100%;
  }

  .bookshelf-item {
    grid-template-columns: 84px minmax(0, 1fr);
    gap: 12px;
  }

  .shelf-cover {
    width: 84px;
  }

  .shelf-title-row {
    flex-direction: column;
  }
}

@media (max-width: 520px) {
  .bookshelf-header,
  .bookshelf-panel,
  .bookshelf-item {
    padding: 16px;
  }

  .bookshelf-header h1 {
    font-size: 22px;
  }

  .bookshelf-item {
    grid-template-columns: 1fr;
  }

  .shelf-cover {
    width: min(132px, 44vw);
    justify-self: start;
  }

  .shelf-meta {
    flex-direction: column;
    gap: 6px;
  }

  .shelf-actions {
    display: grid;
    grid-template-columns: 1fr;
  }

  .shelf-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
