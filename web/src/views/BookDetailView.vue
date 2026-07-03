<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { ArrowLeft, Collection, Reading, Refresh, Star, TrendCharts } from '@element-plus/icons-vue';
import { addBookshelfItem, fetchBookshelfStatus, removeBookshelfItem } from '../api';
import { useBookstore } from '../stores/bookstore';
import { useAuth } from '../stores/auth';

const props = defineProps<{ bookId: string }>();
const router = useRouter();
const store = useBookstore();
const auth = useAuth();
const shelfLoading = ref(false);
const inShelf = ref(false);
const numericBookId = computed(() => Number(props.bookId));
const firstChapter = computed(() => store.chapters[0]);
const latestChapter = computed(() => store.chapters[store.chapters.length - 1]);
const volumeCount = computed(() => new Set(store.chapters.map((chapter) => chapter.volume_title || '正文')).size);
const relatedBooks = computed(() =>
  store.books
    .filter((book) => book.id !== numericBookId.value)
    .slice(0, 6),
);
const detailTags = computed(() => {
  const category = store.currentBook?.category || '本地上传';
  const subTags = (store.currentBook?.sub_tags || '')
    .split(',')
    .map((t: string) => t.trim())
    .filter(Boolean);
  return [category, ...subTags];
});

async function load() {
  try {
    await store.loadBook(numericBookId.value);
    if (store.books.length === 0) {
      await store.loadBooks({ category: 'all' });
    }
    await loadShelfStatus();
  } catch (error) {
    ElMessage.error('无法读取书籍详情');
  }
}

async function loadShelfStatus() {
  if (!auth.token || !Number.isFinite(numericBookId.value)) {
    inShelf.value = false;
    return;
  }
  try {
    const status = await fetchBookshelfStatus(numericBookId.value, auth.token);
    inShelf.value = status.in_shelf;
  } catch {
    inShelf.value = false;
  }
}

function startReading() {
  if (!firstChapter.value) return;
  router.push(`/books/${numericBookId.value}/chapters/${firstChapter.value.id}`);
}

async function toggleShelf() {
  if (!auth.token) {
    auth.openLogin();
    return;
  }
  shelfLoading.value = true;
  try {
    if (inShelf.value) {
      await removeBookshelfItem(numericBookId.value, auth.token);
      inShelf.value = false;
      ElMessage.success('已移出书箱');
    } else {
      await addBookshelfItem(numericBookId.value, auth.token);
      inShelf.value = true;
      ElMessage.success('已加入书箱');
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '书箱操作失败');
  } finally {
    shelfLoading.value = false;
  }
}

function formatCount(value: number) {
  if (value >= 10000) return `${(value / 10000).toFixed(1)} 万`;
  return String(value);
}

function firstChar(value: string) {
  return value.slice(0, 1) || '书';
}

onMounted(() => {
  void load();
});
watch(() => props.bookId, load);
watch(() => auth.token, loadShelfStatus);
</script>

<template>
  <section v-loading="store.loading" class="detail-page platform-detail">
    <div class="detail-breadcrumb">
      <el-button :icon="ArrowLeft" text @click="router.push('/')">灵爻首页</el-button>
      <span>/</span>
      <span>{{ store.currentBook?.category || '作品详情' }}</span>
      <span>/</span>
      <strong>{{ store.currentBook?.title || '加载中' }}</strong>
    </div>

    <div v-if="store.currentBook" class="detail-layout">
      <div class="detail-main-column">
        <section class="detail-hero">
          <div class="book-cover detail-book-cover cyan">
            <img v-if="store.currentBook.cover_url" :src="store.currentBook.cover_url" :alt="store.currentBook.title" />
            <span v-else>{{ firstChar(store.currentBook.title) }}</span>
            <strong>{{ store.currentBook.title }}</strong>
            <em>{{ store.currentBook.category || '书城' }}</em>
          </div>
          <div class="detail-main">
            <p class="eyebrow">{{ store.currentBook.category || '本地上传' }} · 免费阅读 · 连载</p>
            <h1>{{ store.currentBook.title }}</h1>
            <div class="detail-tags">
              <span v-for="tag in detailTags" :key="tag">{{ tag }}</span>
            </div>
            <p class="summary">{{ store.currentBook.summary }}</p>
            <div class="detail-stat-grid">
              <div>
                <strong>{{ formatCount(store.currentBook.word_count) }}</strong>
                <span>总字数</span>
              </div>
              <div>
                <strong>{{ store.currentBook.chapter_count }}</strong>
                <span>章节数</span>
              </div>
              <div>
                <strong>{{ volumeCount }}</strong>
                <span>分卷</span>
              </div>
              <div>
                <strong>9.6</strong>
                <span>演示热度</span>
              </div>
            </div>
            <div class="action-row">
              <el-button type="primary" :icon="Reading" :disabled="!firstChapter" @click="startReading">开始阅读</el-button>
              <el-button :icon="Collection" :loading="shelfLoading" @click="toggleShelf">
                {{ inShelf ? '移出书箱' : '加入书箱' }}
              </el-button>
              <el-button :icon="Refresh" @click="load">刷新目录</el-button>
            </div>
          </div>
        </section>

        <section class="chapter-section">
          <div class="section-heading">
            <div>
              <h2>作品目录</h2>
              <p>按桌面端上传顺序展示，重复上传会更新原章节。</p>
            </div>
            <span>{{ store.chapters.length }} 章</span>
          </div>
          <div class="chapter-list">
            <RouterLink
              v-for="chapter in store.chapters"
              :key="chapter.id"
              class="chapter-row"
              :to="`/books/${numericBookId}/chapters/${chapter.id}`"
            >
              <span class="chapter-order">{{ chapter.sort_order || '-' }}</span>
              <span class="chapter-title">{{ chapter.title }}</span>
              <span class="chapter-volume">{{ chapter.volume_title }}</span>
              <span class="chapter-words">{{ formatCount(chapter.word_count) }} 字</span>
            </RouterLink>
            <el-empty v-if="!store.loading && store.chapters.length === 0" description="暂无章节" />
          </div>
        </section>
      </div>

      <aside class="detail-side-column">
        <section class="detail-side-card">
          <div class="panel-heading">
            <h2>最新更新</h2>
            <TrendCharts />
          </div>
          <RouterLink
            v-if="latestChapter"
            class="latest-chapter-card"
            :to="`/books/${numericBookId}/chapters/${latestChapter.id}`"
          >
            <strong>{{ latestChapter.title }}</strong>
            <span>{{ latestChapter.volume_title }} · {{ formatCount(latestChapter.word_count) }} 字</span>
          </RouterLink>
          <el-empty v-else description="暂无更新" />
        </section>

        <section class="detail-side-card">
          <div class="panel-heading">
            <h2>作品数据</h2>
            <Star />
          </div>
          <div class="work-data-list">
            <p><span>发布来源</span><strong>灵枢工具</strong></p>
            <p><span>阅读权益</span><strong>全部免费</strong></p>
            <p><span>最近章节</span><strong>{{ store.currentBook.latest_chapter_title || '暂无' }}</strong></p>
          </div>
        </section>

        <section class="detail-side-card">
          <div class="panel-heading">
            <h2>同站推荐</h2>
            <span>书库</span>
          </div>
          <div class="detail-rank-list">
            <RouterLink v-for="book in relatedBooks" :key="book.id" :to="`/books/${book.id}`">
              <span>{{ book.title }}</span>
              <small>{{ book.category || '本地作品' }}</small>
            </RouterLink>
            <p v-if="relatedBooks.length === 0" class="empty-hint">暂无更多本地作品</p>
          </div>
        </section>
      </aside>
    </div>
  </section>
</template>
