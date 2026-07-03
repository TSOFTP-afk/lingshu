<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { ArrowLeft, Moon, Sunny } from '@element-plus/icons-vue';
import { updateBookshelfProgress } from '../api';
import { useBookstore } from '../stores/bookstore';
import { useAuth } from '../stores/auth';

const props = defineProps<{ bookId: string; chapterId: string }>();
const router = useRouter();
const store = useBookstore();
const auth = useAuth();
const fontSize = ref(18);
const warmMode = ref(false);
const paragraphs = computed(() => {
  const content = store.currentChapter?.content || '';
  return content.split(/\n{2,}/).map((item) => item.trim()).filter(Boolean);
});

async function load() {
  try {
    await store.loadChapter(Number(props.chapterId));
    await updateProgressIfInShelf();
  } catch (error) {
    ElMessage.error('无法读取章节正文');
  }
}

async function updateProgressIfInShelf() {
  if (!auth.token) return;
  try {
    await updateBookshelfProgress(Number(props.bookId), Number(props.chapterId), auth.token);
  } catch {
    // 不在书箱时后端会返回 404，这里保持阅读体验安静。
  }
}

function goChapter(chapterId: number | null) {
  if (!chapterId) return;
  router.push(`/books/${props.bookId}/chapters/${chapterId}`);
}

onMounted(load);
watch(() => props.chapterId, load);
</script>

<template>
  <section v-loading="store.loading" class="reader-page" :class="{ warm: warmMode }">
    <div class="reader-toolbar">
      <el-button :icon="ArrowLeft" text @click="router.push(`/books/${props.bookId}`)">返回目录</el-button>
      <div class="reader-tools">
        <el-button-group>
          <el-button :disabled="fontSize <= 16" @click="fontSize -= 1">A-</el-button>
          <el-button :disabled="fontSize >= 24" @click="fontSize += 1">A+</el-button>
        </el-button-group>
        <el-button :icon="warmMode ? Sunny : Moon" @click="warmMode = !warmMode">{{ warmMode ? '浅色' : '护眼' }}</el-button>
      </div>
    </div>

    <article v-if="store.currentChapter" class="reader-content" :style="{ fontSize: `${fontSize}px` }">
      <p class="eyebrow">{{ store.currentChapter.book_title }}</p>
      <h1>{{ store.currentChapter.title }}</h1>
      <div class="reader-meta">
        <span>{{ store.currentChapter.volume_title }}</span>
        <span>{{ store.currentChapter.word_count }} 字</span>
      </div>
      <p v-for="(paragraph, index) in paragraphs" :key="index">{{ paragraph }}</p>
    </article>

    <div v-if="store.currentChapter" class="reader-nav">
      <el-button :disabled="!store.currentChapter.previous_chapter_id" @click="goChapter(store.currentChapter.previous_chapter_id)">
        上一章
      </el-button>
      <el-button type="primary" :disabled="!store.currentChapter.next_chapter_id" @click="goChapter(store.currentChapter.next_chapter_id)">
        下一章
      </el-button>
    </div>
  </section>
</template>
