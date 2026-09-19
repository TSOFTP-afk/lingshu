<template>
  <footer class="status-bar">
    <div class="status-left">
      <span class="status-dot" />
      <span class="status-text">就绪</span>
    </div>
    <div class="status-right">
      <span class="status-item">字数: {{ wordCount }}</span>
      <span class="status-divider" />
      <span class="status-item">AI: {{ aiProbability === 0 ? '-' : aiProbability + '%' }}</span>
      <span class="status-divider" />
      <span class="status-item">总计: {{ totalWordCount }}</span>
    </div>
  </footer>
</template>

<script setup>
import { computed } from 'vue';
import { useChapterStore } from '../../stores/chapter';

const chapterStore = useChapterStore();

const wordCount = computed(() => {
  const content = chapterStore.currentChapter?.content || '';
  return content.replace(/\s/g, '').length;
});

const aiProbability = computed(() => chapterStore.currentChapter?.ai_probability || 0);
// 全书字数：章节列表接口每项自带 word_count（后端 LENGTH(content)），直接合计
const totalWordCount = computed(
  () => chapterStore.chapters.reduce((sum, c) => sum + (Number(c.word_count) || 0), 0)
);
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--statusbar-height);
  padding: 0 14px;
  background: linear-gradient(180deg, var(--bg-tertiary), var(--bg-secondary));
  border-top: 1px solid var(--border-color);
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  flex-shrink: 0;
}

.status-left,
.status-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 0 3px rgba(61, 155, 93, 0.12);
}

.status-item {
  white-space: nowrap;
}

.status-divider {
  width: 1px;
  height: 12px;
  background: var(--border-color);
}
</style>
