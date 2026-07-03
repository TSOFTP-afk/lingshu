/**
 * 任务 Store — AI 任务状态管理，占位
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useTaskStore = defineStore('task', () => {
  const tasks = ref([]);

  function addTask(task) {
    tasks.value.unshift({ id: Date.now(), status: 'pending', ...task });
  }

  function updateTask(taskId, updates) {
    const idx = tasks.value.findIndex(t => t.id === taskId);
    if (idx >= 0) Object.assign(tasks.value[idx], updates);
  }

  function clearCompleted() {
    tasks.value = tasks.value.filter(t => t.status !== 'completed');
  }

  return { tasks, addTask, updateTask, clearCompleted };
});
