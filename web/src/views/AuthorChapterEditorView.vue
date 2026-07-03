<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import axios from 'axios';
import { ElMessage } from 'element-plus';
import { ArrowLeft, DocumentChecked, RefreshLeft } from '@element-plus/icons-vue';
import { useAuth } from '../stores/auth';

const props = defineProps<{ bookId: string; chapterId: string }>();
const router = useRouter();
const auth = useAuth();

interface AuthorChapterDetail {
  id: number;
  book_id: number;
  book_title: string;
  volume_title: string;
  title: string;
  content: string;
  sort_order: number;
  word_count: number;
  published_at: string;
  updated_at: string;
}

const loading = ref(true);
const saving = ref(false);
const chapter = ref<AuthorChapterDetail | null>(null);
const form = ref({
  title: '',
  volume_title: '正文',
  content: '',
});

const bookIdNumber = computed(() => Number(props.bookId));
const chapterIdNumber = computed(() => Number(props.chapterId));
const wordCount = computed(() => form.value.content.length);
const bookTitle = computed(() => chapter.value?.book_title || `作品 ${props.bookId}`);
const updatedAt = computed(() => formatDate(chapter.value?.updated_at || chapter.value?.published_at || ''));

function authHeaders() {
  return { Authorization: `Bearer ${auth.token}` };
}

function formatDate(value: string): string {
  if (!value) return '未保存';
  return value.replace('T', ' ').slice(0, 16);
}

function backToManage() {
  router.push(`/profile/books/${props.bookId}/chapters`);
}

function applyChapter(data: AuthorChapterDetail) {
  chapter.value = data;
  form.value = {
    title: data.title || '',
    volume_title: data.volume_title || '正文',
    content: data.content || '',
  };
}

async function loadChapter() {
  if (!auth.token) {
    auth.openLogin();
    loading.value = false;
    return;
  }
  if (
    !Number.isFinite(bookIdNumber.value)
    || !Number.isFinite(chapterIdNumber.value)
    || bookIdNumber.value <= 0
    || chapterIdNumber.value <= 0
  ) {
    await router.replace('/profile');
    return;
  }

  loading.value = true;
  try {
    const res = await axios.get(
      `/api/author/books/${bookIdNumber.value}/chapters/${chapterIdNumber.value}`,
      { headers: authHeaders() },
    );
    applyChapter(res.data as AuthorChapterDetail);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '无法读取章节');
    await router.replace(`/profile/books/${props.bookId}/chapters`);
  } finally {
    loading.value = false;
  }
}

async function saveChapter() {
  const title = form.value.title.trim();
  if (!title) {
    ElMessage.warning('请填写章节名');
    return;
  }
  if (!auth.token) {
    auth.openLogin();
    return;
  }

  saving.value = true;
  try {
    const res = await axios.patch(
      `/api/author/books/${bookIdNumber.value}/chapters/${chapterIdNumber.value}`,
      {
        title,
        volume_title: form.value.volume_title.trim() || '正文',
        content: form.value.content,
      },
      { headers: authHeaders() },
    );
    applyChapter(res.data.item as AuthorChapterDetail);
    ElMessage.success('章节已保存');
    await router.push(`/profile/books/${props.bookId}/chapters`);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败');
  } finally {
    saving.value = false;
  }
}

onMounted(loadChapter);
watch(() => [props.bookId, props.chapterId], () => {
  void loadChapter();
});
</script>

<template>
  <section v-loading="loading" class="chapter-editor-page">
    <header class="editor-header">
      <div class="editor-header-main">
        <el-button :icon="ArrowLeft" text @click="backToManage">返回章节管理</el-button>
        <div class="editor-title-block">
          <span class="editor-kicker">章节编辑</span>
          <h1>
            {{ bookTitle }}
            <small>/ {{ form.volume_title || '正文' }}</small>
          </h1>
        </div>
      </div>

      <div class="editor-header-actions">
        <el-button :icon="RefreshLeft" @click="loadChapter">重置</el-button>
        <el-button type="primary" :icon="DocumentChecked" :loading="saving" @click="saveChapter">
          保存章节
        </el-button>
      </div>
    </header>

    <div class="editor-layout">
      <aside class="editor-meta-panel">
        <article>
          <span>章节序号</span>
          <strong>#{{ chapter?.sort_order || chapter?.id || '-' }}</strong>
        </article>
        <article>
          <span>正文字数</span>
          <strong>{{ wordCount.toLocaleString('zh-CN') }}</strong>
        </article>
        <article>
          <span>更新时间</span>
          <strong>{{ updatedAt }}</strong>
        </article>
      </aside>

      <article class="editor-panel">
        <el-form label-position="top" class="chapter-form">
          <div class="form-grid">
            <el-form-item label="章节名">
              <el-input
                v-model="form.title"
                maxlength="160"
                show-word-limit
                placeholder="输入章节名"
              />
            </el-form-item>
            <el-form-item label="卷名称">
              <el-input
                v-model="form.volume_title"
                maxlength="100"
                placeholder="正文"
              />
            </el-form-item>
          </div>

          <el-form-item label="正文">
            <el-input
              v-model="form.content"
              class="chapter-content-input"
              type="textarea"
              resize="none"
              placeholder="开始写这一章..."
            />
          </el-form-item>
        </el-form>
      </article>
    </div>
  </section>
</template>

<style scoped>
.chapter-editor-page {
  width: min(100% - 32px, 1180px);
  margin: 0 auto;
  padding: 32px 0 72px;
}

.editor-header,
.editor-meta-panel article,
.editor-panel {
  border: 1px solid rgba(184, 202, 216, 0.76);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 10px 28px rgba(26, 45, 61, 0.07);
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
  padding: 20px 22px;
}

.editor-header-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 14px;
}

.editor-title-block {
  min-width: 0;
}

.editor-kicker {
  color: #2F86B6;
  font-size: 12px;
  font-weight: 850;
}

.editor-title-block h1 {
  margin: 5px 0 0;
  color: #12283A;
  font-size: 28px;
  font-weight: 900;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.editor-title-block small {
  color: #5E7487;
  font-size: 18px;
  font-weight: 800;
}

.editor-header-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.editor-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.editor-meta-panel {
  position: sticky;
  top: 92px;
  display: grid;
  gap: 12px;
}

.editor-meta-panel article {
  display: grid;
  gap: 8px;
  padding: 16px;
}

.editor-meta-panel span {
  color: #6E8395;
  font-size: 13px;
  font-weight: 800;
}

.editor-meta-panel strong {
  color: #12283A;
  font-size: 20px;
  font-weight: 900;
  overflow-wrap: anywhere;
}

.editor-panel {
  min-width: 0;
  padding: 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(180px, 0.6fr);
  gap: 16px;
}

.chapter-form :deep(.el-form-item__label) {
  color: #12283A;
  font-weight: 850;
}

.chapter-content-input :deep(.el-textarea__inner) {
  min-height: 58vh !important;
  padding: 16px 18px;
  border: 1px solid rgba(184, 202, 216, 0.92);
  border-radius: 8px;
  color: #1A2D3D;
  background: rgba(248, 251, 253, 0.86);
  box-shadow: none;
  font-size: 16px;
  line-height: 1.9;
}

.chapter-content-input :deep(.el-textarea__inner:focus) {
  border-color: rgba(47, 134, 182, 0.58);
  box-shadow: 0 0 0 3px rgba(47, 134, 182, 0.12);
}

@media (max-width: 900px) {
  .editor-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .editor-header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .editor-layout {
    grid-template-columns: 1fr;
  }

  .editor-meta-panel {
    position: static;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .chapter-editor-page {
    width: min(100% - 24px, 1180px);
    padding-top: 24px;
  }

  .editor-header,
  .editor-panel {
    padding: 16px;
  }

  .editor-header-main {
    align-items: flex-start;
    flex-direction: column;
  }

  .editor-title-block h1 {
    font-size: 24px;
  }

  .editor-title-block small {
    font-size: 16px;
  }

  .editor-header-actions {
    flex-direction: column;
  }

  .editor-header-actions :deep(.el-button) {
    width: 100%;
  }

  .editor-meta-panel,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .chapter-content-input :deep(.el-textarea__inner) {
    min-height: 52vh !important;
    padding: 14px;
  }
}
</style>
