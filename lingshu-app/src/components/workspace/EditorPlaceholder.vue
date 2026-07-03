<template>
  <div class="editor-placeholder">
    <span class="book-badge"><Notebook /></span>
    <h3>{{ bookTitle || '未命名作品' }}</h3>
    <p>打开一个章节，或先补齐作品大纲。</p>
    <div class="placeholder-actions">
      <el-button
        type="primary"
        @click="$emit('create-chapter', bookId)"
      >
        <el-icon><EditPen /></el-icon>
        <span>新建章节</span>
      </el-button>
      <el-button @click="$emit('open-outline')">
        <el-icon><Notebook /></el-icon>
        <span>编辑大纲</span>
      </el-button>
      <el-button @click="$emit('import')">
        <el-icon><Upload /></el-icon>
        <span>导入文稿</span>
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { EditPen, Notebook, Upload } from '@element-plus/icons-vue';

defineProps({
  bookId: { type: Number, default: null },
  bookTitle: { type: String, default: '' },
});

defineEmits(['create-chapter', 'open-outline', 'import']);
</script>

<style scoped>
.editor-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
  gap: 12px;
  padding: 24px;
  text-align: center;
  background: var(--bg-primary);
}

.book-badge {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-lg);
  color: var(--color-primary);
  background: rgba(15, 143, 134, 0.10);
  border: 1px solid rgba(15, 143, 134, 0.18);
}

.editor-placeholder h3 {
  font-size: var(--font-size-xl);
  color: var(--text-primary);
}

.editor-placeholder p {
  font-size: var(--font-size-sm);
}

.placeholder-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 4px;
}
</style>
