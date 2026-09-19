<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  ArrowLeft,
  Collection,
  DataAnalysis,
  Document,
  DocumentAdd,
  DocumentChecked,
  EditPen,
  Grid,
  Tickets,
  UserFilled,
} from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import axios from 'axios';
import { useAuth } from '../stores/auth';
import { ALL_SUB_TAGS } from '../constants/profileTags';

const auth = useAuth();
const route = useRoute();
const router = useRouter();

interface ProfileBook {
  id: number;
  title: string;
  summary: string;
  category: string;
  sub_tags: string;
  cover_url: string;
  chapter_count: number;
  word_count: number;
  latest_chapter_title: string | null;
  updated_at: string;
}

const books = ref<ProfileBook[]>([]);
const loading = ref(true);
const showCreateDialog = ref(false);
const creatingBook = ref(false);
const continuingWrite = ref(false);
const savingSummary = ref(false);
const summaryDraft = ref('');
const newBookForm = ref({
  title: '',
  sub_tags: '',
  summary: '',
});

// ---------- 作品标签编辑 ----------
const showTagDialog = ref(false);
const editingTags = ref<string[]>([]);
const tagSearchKeyword = ref('');

const availableTags = computed(() => {
  const kw = tagSearchKeyword.value.trim().toLowerCase();
  if (!kw) return ALL_SUB_TAGS;
  return ALL_SUB_TAGS.filter((t) => t.toLowerCase().includes(kw));
});

function toggleTag(tag: string) {
  const idx = editingTags.value.indexOf(tag);
  if (idx >= 0) {
    editingTags.value.splice(idx, 1);
  } else {
    editingTags.value.push(tag);
  }
}

function openTagDialog() {
  if (!selectedBook.value) return;
  editingTags.value = (selectedBook.value.sub_tags || '')
    .split(',')
    .map((t: string) => t.trim())
    .filter(Boolean);
  tagSearchKeyword.value = '';
  showTagDialog.value = true;
}

async function saveTags() {
  if (!selectedBook.value || !auth.token) return;
  try {
    const subTags = editingTags.value.join(',');
    const res = await axios.patch(`/api/author/books/${selectedBook.value.id}`, {
      sub_tags: subTags,
    }, { headers: authHeaders() });
    const item = res.data.item as ProfileBook;
    books.value = books.value.map((book) => (book.id === item.id ? { ...book, ...item } : book));
    showTagDialog.value = false;
    ElMessage.success('标签已更新');
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '标签更新失败');
  }
}

const selectedBookId = computed(() => {
  const raw = route.params.bookId;
  const value = Array.isArray(raw) ? raw[0] : raw;
  const id = Number(value);
  return Number.isFinite(id) && id > 0 ? id : null;
});
const isDetailMode = computed(() => selectedBookId.value !== null);
const selectedBook = computed(() =>
  books.value.find((book) => book.id === selectedBookId.value) || null,
);
const totalChapters = computed(() =>
  books.value.reduce((sum, book) => sum + Number(book.chapter_count || 0), 0),
);
const totalWords = computed(() =>
  books.value.reduce((sum, book) => sum + Number(book.word_count || 0), 0),
);
const hasSummaryChanges = computed(() =>
  Boolean(selectedBook.value) && summaryDraft.value !== (selectedBook.value?.summary || ''),
);

function formatWords(value: number): string {
  const n = Number(value || 0);
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return n.toLocaleString('zh-CN');
}

function firstChar(value: string): string {
  return value.trim().slice(0, 1) || '书';
}

function formatDate(value: string): string {
  if (!value) return '刚刚';
  return value.slice(0, 10);
}

function bookTags(book: ProfileBook): string[] {
  const tags = new Set<string>();
  const category = (book.category || '').trim();
  if (category && category !== '本地上传') tags.add(category);

  for (const tag of (book.sub_tags || '').split(',')) {
    const normalized = tag.trim();
    if (normalized) tags.add(normalized);
  }

  return tags.size > 0 ? [...tags] : ['自选'];
}

function openBook(bookId: number) {
  router.push(`/profile/books/${bookId}`);
}

function backToGallery() {
  router.push('/profile');
}

function openChapterManager(bookId: number) {
  router.push(`/profile/books/${bookId}/chapters`);
}

function authHeaders() {
  return { Authorization: `Bearer ${auth.token}` };
}

function openCreateBookDialog() {
  newBookForm.value = {
    title: '',
    sub_tags: '',
    summary: '',
  };
  showCreateDialog.value = true;
}

async function loadBooks() {
  if (!auth.token) {
    books.value = [];
    loading.value = false;
    return;
  }

  loading.value = true;
  try {
    const res = await axios.get('/api/author/books', {
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    books.value = res.data.items || [];
  } catch {
    books.value = [];
  } finally {
    loading.value = false;
  }
}

async function createBook() {
  const title = newBookForm.value.title.trim();
  if (!title) {
    ElMessage.warning('请填写作品名称');
    return;
  }
  if (!auth.token) {
    auth.openLogin();
    return;
  }

  creatingBook.value = true;
  try {
    const res = await axios.post('/api/author/books', {
      title,
      sub_tags: newBookForm.value.sub_tags,
      summary: newBookForm.value.summary,
    }, {
      headers: authHeaders(),
    });
    const item = res.data.item as ProfileBook;
    showCreateDialog.value = false;
    ElMessage.success('作品已创建');
    await loadBooks();
    openBook(item.id);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建作品失败');
  } finally {
    creatingBook.value = false;
  }
}

async function continueWriting() {
  if (!auth.token) {
    auth.openLogin();
    return;
  }
  if (books.value.length === 0) {
    openCreateBookDialog();
    return;
  }

  const target = books.value[0];
  continuingWrite.value = true;
  try {
    const res = await axios.post(`/api/author/books/${target.id}/chapters/next`, {}, {
      headers: authHeaders(),
    });
    const item = res.data.item as { id: number };
    ElMessage.success('已创建下一章草稿');
    await router.push(`/profile/books/${target.id}/chapters/${item.id}/edit`);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '继续码字失败');
  } finally {
    continuingWrite.value = false;
  }
}

async function saveSummary() {
  if (!selectedBook.value) return;
  if (!auth.token) {
    auth.openLogin();
    return;
  }

  savingSummary.value = true;
  try {
    const res = await axios.patch(`/api/author/books/${selectedBook.value.id}`, {
      summary: summaryDraft.value,
    }, {
      headers: authHeaders(),
    });
    const item = res.data.item as ProfileBook;
    books.value = books.value.map((book) => (book.id === item.id ? { ...book, ...item } : book));
    summaryDraft.value = item.summary || '';
    ElMessage.success('作品简介已保存');
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败');
  } finally {
    savingSummary.value = false;
  }
}

onMounted(() => {
  void loadBooks();
});

watch(() => auth.token, () => {
  void loadBooks();
});

watch(
  [loading, selectedBookId, selectedBook],
  () => {
    if (!loading.value && selectedBookId.value !== null && !selectedBook.value) {
      void router.replace('/profile');
    }
  },
  { immediate: true },
);

watch(selectedBook, (book) => {
  summaryDraft.value = book?.summary || '';
}, { immediate: true });
</script>

<template>
  <div class="profile-page" :class="{ 'profile-page-detail': isDetailMode }">
    <div v-if="!auth.user" class="profile-login-hint">
      <el-empty description="请先登录以查看个人主页">
        <el-button type="primary" @click="auth.openLogin()">登录账号</el-button>
      </el-empty>
    </div>

    <template v-else>
      <section class="profile-hero">
        <div class="profile-hero-main">
          <el-avatar class="profile-avatar" :size="84" :icon="UserFilled" />
          <div class="profile-title">
            <span class="profile-eyebrow">作者工作台</span>
            <h1>{{ auth.user.username }}</h1>
            <p>{{ auth.user.is_author ? '管理作品、维护简介和查看创作数据' : '当前账号暂未开通作者权限' }}</p>
          </div>
        </div>

        <div class="profile-hero-actions">
          <el-tag :type="auth.user.is_author ? 'success' : 'info'" size="large">
            {{ auth.user.is_author ? '作者' : '读者' }}
          </el-tag>
          <el-button
            v-if="auth.user.is_author"
            type="primary"
            :icon="EditPen"
            :loading="continuingWrite"
            @click="continueWriting"
          >
            继续码字
          </el-button>
        </div>
      </section>

      <section v-if="auth.user.is_author" class="profile-stats" aria-label="作者统计">
        <article class="profile-stat">
          <span>作品</span>
          <strong>{{ books.length }}</strong>
          <small>已发布作品数</small>
        </article>
        <article class="profile-stat">
          <span>章节</span>
          <strong>{{ totalChapters }}</strong>
          <small>累计章节</small>
        </article>
        <article class="profile-stat">
          <span>总字数</span>
          <strong>{{ formatWords(totalWords) }}</strong>
          <small>全站展示字数</small>
        </article>
      </section>

      <el-empty
        v-if="!auth.user.is_author"
        class="profile-empty"
        description="当前账号不是作者账号"
      />

      <section v-else-if="!isDetailMode" class="profile-works">
        <div class="section-toolbar">
          <div>
            <span class="section-kicker">Works</span>
            <h2>我的作品</h2>
          </div>
          <el-button :icon="DocumentAdd" @click="openCreateBookDialog">新建作品</el-button>
        </div>

        <div v-if="!loading && books.length === 0" class="empty-work-card">
          <div class="empty-icon">
            <el-icon><DocumentAdd /></el-icon>
          </div>
          <h3>还没有发布过作品</h3>
          <p>从一个书名和一句简介开始，先把作品档案建起来，后续再慢慢补章节和数据。</p>
          <el-button type="primary" size="large" :icon="DocumentAdd" @click="openCreateBookDialog">
            发布你的第一个作品
          </el-button>
        </div>

        <div v-loading="loading" class="profile-book-grid" :class="{ empty: books.length === 0 }">
          <button
            v-for="book in books"
            :key="book.id"
            type="button"
            class="work-card"
            @click="openBook(book.id)"
          >
            <span class="work-cover">
              <img v-if="book.cover_url" :src="book.cover_url" :alt="book.title" />
              <span v-else>{{ firstChar(book.title) }}</span>
            </span>
            <span class="work-card-body">
              <span class="work-card-top">
                <strong>{{ book.title }}</strong>
                <small>{{ formatDate(book.updated_at) }}</small>
              </span>
              <span class="work-tags">
                <em v-for="tag in bookTags(book).slice(0, 3)" :key="tag">{{ tag }}</em>
              </span>
              <span class="work-summary">{{ book.summary || '暂无简介，进入作品管理后补充。' }}</span>
              <span class="work-meta">
                <span>{{ book.chapter_count }} 章</span>
                <span>{{ formatWords(book.word_count) }} 字</span>
                <span>管理</span>
              </span>
            </span>
          </button>
        </div>
      </section>

      <section v-else-if="selectedBook" class="profile-manager">
        <aside class="work-sidebar" aria-label="作品列表">
          <button type="button" class="sidebar-back" @click="backToGallery">
            <el-icon><ArrowLeft /></el-icon>
            <span>全部作品</span>
          </button>

          <div class="sidebar-title">
            <span>作品列表</span>
            <button type="button" @click="openCreateBookDialog">
              <el-icon><DocumentAdd /></el-icon>
            </button>
          </div>

          <button
            v-for="book in books"
            :key="book.id"
            type="button"
            class="sidebar-book"
            :class="{ active: book.id === selectedBook.id }"
            @click="openBook(book.id)"
          >
            <span class="sidebar-cover">
              <img v-if="book.cover_url" :src="book.cover_url" :alt="book.title" />
              <span v-else>{{ firstChar(book.title) }}</span>
            </span>
            <span class="sidebar-book-main">
              <strong>{{ book.title }}</strong>
              <small>{{ book.chapter_count }}章 · {{ formatWords(book.word_count) }}字</small>
            </span>
          </button>
        </aside>

        <article class="manager-panel">
          <section class="manager-hero-card">
            <div class="manager-cover">
              <img v-if="selectedBook.cover_url" :src="selectedBook.cover_url" :alt="selectedBook.title" />
              <span v-else>{{ firstChar(selectedBook.title) }}</span>
            </div>

            <div class="manager-main">
              <div class="manager-status-row">
                <span class="status-pill">连载中</span>
                <span>更新于 {{ formatDate(selectedBook.updated_at) }}</span>
              </div>
              <h2>{{ selectedBook.title }}</h2>
              <div class="manager-tags">
                <span v-for="tag in bookTags(selectedBook)" :key="tag">{{ tag }}</span>
              </div>

              <div class="manager-actions" aria-label="作品操作">
                <button type="button" class="action-co-create">
                  <el-icon><Collection /></el-icon>
                  <span>共创乐园</span>
                </button>
                <button type="button" class="action-chapters" @click="openChapterManager(selectedBook.id)">
                  <el-icon><Tickets /></el-icon>
                  <span>章节管理</span>
                </button>
                <button type="button" class="action-data">
                  <el-icon><DataAnalysis /></el-icon>
                  <span>书籍数据</span>
                </button>
                <button
                  type="button"
                  class="action-save"
                  :disabled="savingSummary || !hasSummaryChanges"
                  @click="saveSummary"
                >
                  <el-icon><DocumentChecked /></el-icon>
                  <span>{{ savingSummary ? '保存中' : '保存' }}</span>
                </button>
              </div>
            </div>
          </section>

          <section class="summary-editor-card">
            <div class="editor-heading">
              <div>
                <span>作品简介</span>
                <p>用于书库展示和作者后台管理。修改后点击上方“保存”。</p>
              </div>
              <small v-if="hasSummaryChanges">有未保存修改</small>
            </div>
            <el-input
              id="profile-summary-input"
              v-model="summaryDraft"
              class="profile-summary-input"
              type="textarea"
              resize="none"
              maxlength="4000"
              show-word-limit
              placeholder="写下这本书的简介..."
            />
          </section>

          <section v-if="selectedBook" class="profile-tags-card">
            <div class="editor-heading">
              <div>
                <span>作品标签</span>
                <p>标签用于书库分类和读者发现。点击"编辑标签"进行修改。</p>
              </div>
              <el-button type="primary" size="small" :icon="EditPen" @click="openTagDialog">编辑标签</el-button>
            </div>
            <div class="detail-tags">
              <span v-for="tag in bookTags(selectedBook)" :key="tag">{{ tag }}</span>
            </div>
          </section>

          <section class="manager-data-grid">
            <article>
              <el-icon><Document /></el-icon>
              <span>章节</span>
              <strong>{{ selectedBook.chapter_count }}</strong>
            </article>
            <article>
              <el-icon><Grid /></el-icon>
              <span>字数</span>
              <strong>{{ formatWords(selectedBook.word_count) }}</strong>
            </article>
            <article>
              <el-icon><Tickets /></el-icon>
              <span>最新章节</span>
              <strong>{{ selectedBook.latest_chapter_title || '暂无章节' }}</strong>
            </article>
          </section>
        </article>
      </section>

      <el-dialog
        v-if="auth.user.is_author"
        v-model="showCreateDialog"
        class="profile-create-dialog"
        title="新建作品"
        width="620px"
        :close-on-click-modal="false"
      >
        <div class="create-dialog-layout">
          <div class="create-preview">
            <span>{{ firstChar(newBookForm.title || '新书') }}</span>
            <strong>{{ newBookForm.title || '新作品' }}</strong>
            <small>{{ newBookForm.sub_tags || '标签稍后可补充' }}</small>
          </div>

          <el-form label-position="top" class="profile-create-form">
            <el-form-item label="作品名称">
              <el-input
                v-model="newBookForm.title"
                maxlength="100"
                show-word-limit
                placeholder="输入你的新作品名称"
                @keyup.enter="createBook"
              />
            </el-form-item>
            <el-form-item label="书籍标签">
              <el-input
                v-model="newBookForm.sub_tags"
                placeholder="例如：玄幻, 升级, 群像"
              />
            </el-form-item>
            <el-form-item label="作品简介">
              <el-input
                v-model="newBookForm.summary"
                type="textarea"
                resize="none"
                maxlength="4000"
                placeholder="先写一个简短介绍，之后可以在详情页继续修改"
                class="profile-create-summary"
              />
            </el-form-item>
          </el-form>
        </div>
        <template #footer>
          <div class="profile-dialog-footer">
            <el-button @click="showCreateDialog = false">取消</el-button>
            <el-button type="primary" :loading="creatingBook" :icon="DocumentAdd" @click="createBook">
              创建作品
            </el-button>
          </div>
        </template>
      </el-dialog>

      <el-dialog
        v-model="showTagDialog"
        title="编辑作品标签"
        width="620px"
        :close-on-click-modal="false"
        class="profile-tag-dialog"
      >
        <!-- 已选标签 -->
        <div class="detail-tags" v-if="editingTags.length" style="margin-bottom: 16px">
          <span
            v-for="tag in editingTags"
            :key="tag"
            class="tag-removable"
            @click="toggleTag(tag)"
          >{{ tag }} ✕</span>
        </div>
        <p v-else class="tag-empty-hint">点击下方标签进行添加</p>

        <!-- 标签搜索 -->
        <el-input
          v-model="tagSearchKeyword"
          placeholder="搜索标签..."
          clearable
          style="margin-bottom: 12px"
        />

        <!-- 备选标签池 -->
        <div class="tag-pool">
          <span
            v-for="tag in availableTags.slice(0, 80)"
            :key="tag"
            class="tag-candidate"
            :class="{ active: editingTags.includes(tag) }"
            @click="toggleTag(tag)"
          >{{ tag }}</span>
        </div>

        <template #footer>
          <div class="profile-dialog-footer">
            <el-button @click="showTagDialog = false">取消</el-button>
            <el-button type="primary" @click="saveTags">保存标签</el-button>
          </div>
        </template>
      </el-dialog>
    </template>
  </div>
</template>
<style scoped src="../styles/profile-view.css"></style>
