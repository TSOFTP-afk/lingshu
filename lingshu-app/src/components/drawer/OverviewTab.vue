<template>
  <div
    class="overview-tab"
    aria-label="作品概览"
  >
    <div class="ov-header">
      <h3>{{ bookTitle || '未选择书籍' }}</h3>
      <el-button
        size="small"
        text
        type="primary"
        :disabled="!bookId || !auth.isLoggedIn"
      >
        AI 总结全书
      </el-button>
    </div>

    <!-- Meta 统计 -->
    <el-descriptions
      v-if="bookId"
      :column="1"
      size="small"
      border
      style="margin-bottom: 12px"
    >
      <el-descriptions-item label="分卷">
        {{ stats.volumes }} 卷
      </el-descriptions-item>
      <el-descriptions-item label="章节">
        {{ stats.chapters }} 章
      </el-descriptions-item>
      <el-descriptions-item label="人物">
        {{ stats.characters }} 人
      </el-descriptions-item>
    </el-descriptions>

    <!-- 素材书上下文 -->
    <div
      v-if="referenceContext"
      class="ov-section"
    >
      <div class="ov-section-title">
        素材书上下文
      </div>
      <div class="ov-context">
        {{ referenceContext }}
      </div>
    </div>

    <div
      v-if="!bookId"
      class="ov-empty"
    >
      <p>请先在作品轨道中选择一本书</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue';
import { useBookStore } from '../../stores/book';
import { useAuthStore } from '../../stores/auth';
import api from '../../utils/api';

const bookStore = useBookStore();
const auth = useAuthStore();

const stats = ref({ volumes: 0, chapters: 0, characters: 0 });
const referenceContext = ref('');
const loading = ref(false);

const bookId = computed(() => bookStore.currentBookId);
const bookTitle = computed(() => bookStore.currentBook?.title || '');

async function refresh() {
  if (!bookId.value) {
    stats.value = { volumes: 0, chapters: 0, characters: 0 };
    referenceContext.value = '';
    return;
  }
  loading.value = true;
  try {
    const book = bookStore.currentBook;
    if (book) {
      stats.value = {
        volumes: (book.volumes || []).length,
        chapters: (book.volumes || []).reduce((s, v) => s + (v.chapters || []).length, 0),
        characters: 0,
      };
    }
    // 获取参考书上下文
    try {
      const { data: refs } = await api.get(`/workspace/books/${bookId.value}/references`);
      referenceContext.value = refs.context || '';
    } catch { /* refs not critical */ }
  } finally {
    loading.value = false;
  }
}

watch(bookId, refresh);
onMounted(refresh);
</script>

<style scoped>
.overview-tab { padding: 4px 0; }
.ov-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.ov-header h3 { font-size: 15px; margin: 0; }
.ov-section { margin-top: 12px; }
.ov-section-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; }
.ov-context { font-size: 12px; color: var(--text-regular); line-height: 1.6; white-space: pre-wrap; max-height: 200px; overflow-y: auto; padding: 8px; background: var(--bg-tertiary); border-radius: var(--radius-sm); }
.ov-empty { text-align: center; color: var(--text-placeholder); padding: 32px 0; }
</style>
