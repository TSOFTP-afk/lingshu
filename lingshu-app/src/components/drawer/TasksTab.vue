<template>
  <div class="tasks-tab">
    <div class="tab-header">
      <span class="tab-title">任务面板</span>
      <el-button
        v-if="tasks.length"
        size="small"
        text
        @click="tasks = tasks.filter(t => t.status === 'running')"
      >
        清已完成
      </el-button>
    </div>

    <div
      v-if="!tasks.length"
      class="empty-hint"
    >
      暂无活跃任务
    </div>

    <div
      v-else
      class="task-list"
    >
      <div
        v-for="task in tasks"
        :key="task.id"
        class="task-item"
      >
        <el-tag
          :type="task.status === 'running' ? 'primary' : task.status === 'done' ? 'success' : 'danger'"
          size="small"
          effect="plain"
        >
          {{ task.label || '任务' }}
        </el-tag>
        <div class="task-content">
          <div class="task-message">
            {{ task.message || '' }}
          </div>
          <el-progress
            v-if="task.percent !== undefined"
            :percentage="task.percent"
            :stroke-width="4"
          />
        </div>
        <el-button
          v-if="task.status === 'running'"
          size="small"
          text
          type="danger"
          @click="$emit('cancel', task.id)"
        >
          取消
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';

defineEmits(['cancel']);
const tasks = ref([]);

// 暴露方法供外部调用
defineExpose({
  addTask(label) {
    const task = { id: Date.now(), status: 'running', label, message: '启动中...', percent: 0 };
    tasks.value.unshift(task);
    return task;
  },
  updateTask(id, updates) {
    const t = tasks.value.find(t => t.id === id);
    if (t) Object.assign(t, updates);
  },
  removeTask(id) {
    tasks.value = tasks.value.filter(t => t.id !== id);
  },
});
</script>

<style scoped>
.tasks-tab { padding: 4px 0; }
.tab-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.empty-hint { color: var(--text-placeholder); font-size: 12px; padding: 16px 0; text-align: center; }
.task-item { display: flex; align-items: flex-start; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border-light); }
.task-content { flex: 1; min-width: 0; }
.task-message { font-size: 12px; color: var(--text-primary); margin-bottom: 4px; }
</style>
