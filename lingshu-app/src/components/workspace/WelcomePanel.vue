<template>
  <div class="empty-state">
    <section class="welcome-panel">
      <div class="welcome-brand">
        <span class="welcome-mark">灵</span>
        <span>灵枢工作台</span>
      </div>
      <h2>开始新的创作项目</h2>
      <p>选择左侧作品，或从这里创建一本文稿。</p>
      <div class="welcome-actions">
        <el-button
          type="primary"
          size="large"
          @click="$emit('create')"
        >
          <el-icon><CirclePlus /></el-icon>
          <span>新建作品</span>
        </el-button>
        <el-button
          size="large"
          @click="$emit('import')"
        >
          <el-icon><Upload /></el-icon>
          <span>导入文稿</span>
        </el-button>
        <el-button
          size="large"
          @click="$emit('reference')"
        >
          <el-icon><Collection /></el-icon>
          <span>参考书库</span>
        </el-button>
      </div>
      <div class="welcome-stats">
        <div>
          <strong>{{ bookCount }}</strong>
          <span>作品</span>
        </div>
        <div>
          <strong>{{ chapterCount }}</strong>
          <span>章节</span>
        </div>
        <div>
          <strong>{{ formattedTotalWords }}</strong>
          <span>总字数</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { CirclePlus, Collection, Upload } from '@element-plus/icons-vue';

const props = defineProps({
  bookCount: { type: Number, default: 0 },
  chapterCount: { type: Number, default: 0 },
  totalWordCount: { type: Number, default: 0 },
});

defineEmits(['create', 'import', 'reference']);

const formattedTotalWords = computed(() => {
  const count = props.totalWordCount;
  if (count >= 10000) return `${(count / 10000).toFixed(1)}万`;
  return String(count);
});
</script>

<style scoped>
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.48), rgba(246, 248, 251, 0.76)),
    repeating-linear-gradient(0deg, rgba(15, 143, 134, 0.045), rgba(15, 143, 134, 0.045) 1px, transparent 1px, transparent 42px),
    repeating-linear-gradient(90deg, rgba(31, 111, 235, 0.035), rgba(31, 111, 235, 0.035) 1px, transparent 1px, transparent 42px);
}

.welcome-panel {
  width: min(720px, 100%);
  padding: 30px 34px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: rgba(255, 255, 255, 0.88);
  box-shadow: var(--shadow-lg);
}

.welcome-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 700;
}

.welcome-mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  color: #fff;
  background: linear-gradient(135deg, #13b5a8, #4169e1);
}

.welcome-panel h2 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  color: var(--text-primary);
  letter-spacing: 0;
}

.welcome-panel p {
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.welcome-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;
}

.welcome-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 24px;
}

.welcome-stats div {
  min-width: 0;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-secondary);
}

.welcome-stats strong,
.welcome-stats span {
  display: block;
}

.welcome-stats strong {
  color: var(--text-primary);
  font-size: 20px;
  line-height: 1.2;
}

.welcome-stats span {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 12px;
}

@media (max-width: 920px) {
  .welcome-panel {
    padding: 24px;
  }

  .welcome-stats {
    grid-template-columns: 1fr;
  }
}
</style>
