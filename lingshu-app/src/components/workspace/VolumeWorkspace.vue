<template>
  <section class="volume-workspace">
    <header class="volume-header">
      <div>
        <span class="volume-eyebrow">卷级工作区</span>
        <h2>{{ volume.title || '正文' }}</h2>
        <p>所属作品：{{ bookTitle || '未命名作品' }}</p>
      </div>
      <el-button
        type="primary"
        @click="$emit('create-chapter', { bookId, volumeId: isVirtual ? null : volume.id })"
      >
        <el-icon><EditPen /></el-icon>
        <span>新建章节</span>
      </el-button>
    </header>
    <div class="volume-stats">
      <div>
        <strong>{{ chapters.length }}</strong>
        <span>章节数</span>
      </div>
      <div>
        <strong>{{ volumeWordCount }}</strong>
        <span>卷字数</span>
      </div>
    </div>
    <div
      class="volume-chapter-list"
      :class="{ 'volume-chapter-list--saving': saving }"
    >
      <div
        v-for="(chapter, index) in chapters"
        :key="chapter.id"
        class="volume-chapter-item"
        :class="{
          'volume-chapter-item--dragging': draggedChapterId === chapter.id,
          'volume-chapter-item--drop-before': dragOverChapterId === chapter.id && dragOverPlacement === 'before' && draggedChapterId !== chapter.id,
          'volume-chapter-item--drop-after': dragOverChapterId === chapter.id && dragOverPlacement === 'after' && draggedChapterId !== chapter.id,
        }"
        draggable="true"
        role="button"
        tabindex="0"
        @dragstart="onDragStart(chapter, index, $event)"
        @dragover.prevent="onDragOver(chapter, index, $event)"
        @drop.prevent="onDrop(chapter, index, $event)"
        @dragend="onDragEnd"
        @click="onChapterClick(chapter)"
        @keydown.enter.prevent="onChapterClick(chapter)"
      >
        <span
          class="volume-chapter-drag-handle"
          aria-hidden="true"
        >⋮⋮</span>
        <span class="volume-chapter-title">{{ chapter.title || `章节 #${chapter.id}` }}</span>
        <small>{{ chapter.word_count || 0 }} 字</small>
      </div>
      <el-empty
        v-if="chapters.length === 0"
        description="该卷暂无章节"
        :image-size="72"
      />
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue';
import { EditPen } from '@element-plus/icons-vue';

const props = defineProps({
  volume: { type: Object, required: true },
  chapters: { type: Array, default: () => [] },
  bookId: { type: Number, default: null },
  bookTitle: { type: String, default: '' },
  isVirtual: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
});

const emit = defineEmits(['create-chapter', 'open-chapter', 'reorder']);

const draggedChapterId = ref(null);
const draggedChapterIndex = ref(-1);
const dragOverChapterId = ref(null);
const dragOverPlacement = ref('before');
let suppressClickUntil = 0;

const volumeWordCount = computed(() =>
  props.chapters.reduce((sum, chapter) => sum + (Number(chapter.word_count) || 0), 0),
);

function onDragStart(chapter, index, event) {
  draggedChapterId.value = chapter.id;
  draggedChapterIndex.value = index;
  dragOverChapterId.value = chapter.id;
  suppressClickUntil = Date.now() + 300;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', String(chapter.id));
}

function onDragOver(chapter, index, event) {
  if (!draggedChapterId.value || draggedChapterId.value === chapter.id) return;
  dragOverChapterId.value = chapter.id;
  const rect = event.currentTarget.getBoundingClientRect();
  dragOverPlacement.value = event.clientY > rect.top + rect.height / 2 ? 'after' : 'before';
  event.dataTransfer.dropEffect = 'move';
}

function onDrop(chapter, dropIndex) {
  const fromIndex = draggedChapterIndex.value;
  const draggedId = draggedChapterId.value;
  const placement = dragOverPlacement.value;
  onDragEnd();
  suppressClickUntil = Date.now() + 300;
  if (!draggedId || fromIndex < 0) return;
  const chapters = [...props.chapters];
  const [moved] = chapters.splice(fromIndex, 1);
  if (!moved) return;
  let targetIndex = placement === 'after' ? dropIndex + 1 : dropIndex;
  if (fromIndex < targetIndex) targetIndex -= 1;
  if (fromIndex === targetIndex) return;
  chapters.splice(targetIndex, 0, moved);
  const reordered = chapters.map((item, index) => ({ ...item, sort_order: index + 1 }));
  emit('reorder', reordered);
}

function onDragEnd() {
  draggedChapterId.value = null;
  draggedChapterIndex.value = -1;
  dragOverChapterId.value = null;
  dragOverPlacement.value = 'before';
}

function onChapterClick(chapter) {
  if (Date.now() < suppressClickUntil) return;
  if (!chapter?.id) return;
  emit('open-chapter', chapter);
}
</script>

<style scoped>
.volume-workspace {
  height: 100%;
  overflow: auto;
  padding: 24px;
  background: var(--bg-primary);
}

.volume-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(15, 143, 134, 0.08), rgba(65, 105, 225, 0.06));
  box-shadow: var(--shadow-sm);
}

.volume-eyebrow {
  display: inline-flex;
  margin-bottom: 8px;
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
}

.volume-header h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 24px;
}

.volume-header p {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.volume-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 16px 0;
}

.volume-stats div {
  padding: 16px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}

.volume-stats strong,
.volume-stats span {
  display: block;
}

.volume-stats strong {
  color: var(--text-primary);
  font-size: 22px;
}

.volume-stats span {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 12px;
}

.volume-chapter-list {
  display: grid;
  gap: 10px;
}

.volume-chapter-list--saving {
  opacity: 0.72;
  pointer-events: none;
}

.volume-chapter-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  color: var(--text-primary);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  cursor: grab;
  text-align: left;
  user-select: none;
  transition: background var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast), opacity var(--transition-fast), transform var(--transition-fast);
}

.volume-chapter-item:hover {
  border-color: color-mix(in srgb, var(--color-primary) 36%, var(--border-color));
  background: var(--bg-hover);
  transform: translateY(-1px);
}

.volume-chapter-item:active {
  cursor: grabbing;
}

.volume-chapter-item--dragging {
  opacity: 0.45;
  transform: scale(0.99);
}

.volume-chapter-item--drop-before::before,
.volume-chapter-item--drop-after::after {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  height: 3px;
  border-radius: 999px;
  background: var(--color-primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-primary) 14%, transparent);
}

.volume-chapter-item--drop-before::before {
  top: -7px;
}

.volume-chapter-item--drop-after::after {
  bottom: -7px;
}

.volume-chapter-drag-handle {
  flex: 0 0 auto;
  color: var(--text-tertiary);
  font-weight: 700;
  letter-spacing: -3px;
  cursor: grab;
}

.volume-chapter-title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.volume-chapter-item small {
  flex: 0 0 auto;
  color: var(--text-secondary);
}
</style>
