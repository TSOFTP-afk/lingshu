import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useTaskStore } from '../../../src/stores/task';

describe('useTaskStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 tasks 为空数组', () => {
      const store = useTaskStore();
      expect(store.tasks).toEqual([]);
    });
  });

  describe('addTask', () => {
    it('添加任务到列表头部', () => {
      const store = useTaskStore();
      store.addTask({ title: '任务1', type: 'ai' });

      expect(store.tasks).toHaveLength(1);
      expect(store.tasks[0].title).toBe('任务1');
      expect(store.tasks[0].type).toBe('ai');
      expect(store.tasks[0].status).toBe('pending');
      expect(store.tasks[0].id).toBeTruthy();
    });

    it('新任务添加到列表头部', () => {
      const store = useTaskStore();
      store.addTask({ title: '任务1' });
      store.addTask({ title: '任务2' });

      expect(store.tasks[0].title).toBe('任务2');
      expect(store.tasks[1].title).toBe('任务1');
    });

    it('每个任务有唯一的 id（基于 Date.now）', () => {
      const store = useTaskStore();
      // 使用 mock Date.now 确保不同 id
      const realDateNow = Date.now;
      let counter = 1000;
      Date.now = () => counter++;

      store.addTask({ title: '任务1' });
      store.addTask({ title: '任务2' });

      expect(store.tasks[0].id).not.toBe(store.tasks[1].id);

      Date.now = realDateNow;
    });
  });

  describe('updateTask', () => {
    it('更新指定任务', () => {
      const store = useTaskStore();
      const realDateNow = Date.now;
      let counter = 2000;
      Date.now = () => counter++;

      store.addTask({ title: '任务1' });

      const taskId = store.tasks[0].id;
      store.updateTask(taskId, { status: 'running', progress: 50 });

      expect(store.tasks[0].status).toBe('running');
      expect(store.tasks[0].progress).toBe(50);
      expect(store.tasks[0].title).toBe('任务1'); // 原属性不变

      Date.now = realDateNow;
    });

    it('更新不存在的任务无操作', () => {
      const store = useTaskStore();
      store.addTask({ title: '任务1' });

      store.updateTask(99999, { status: 'completed' });

      expect(store.tasks[0].status).toBe('pending');
    });
  });

  describe('clearCompleted', () => {
    it('清除已完成的任务', () => {
      const store = useTaskStore();
      // 使用 mock Date.now 确保每个任务有唯一 id
      const realDateNow = Date.now;
      let counter = 3000;
      Date.now = () => counter++;

      store.addTask({ title: '任务1' });
      store.addTask({ title: '任务2' });
      store.addTask({ title: '任务3' });

      const task1 = store.tasks.find(t => t.title === '任务1');
      const task2 = store.tasks.find(t => t.title === '任务2');
      const task3 = store.tasks.find(t => t.title === '任务3');

      store.updateTask(task1.id, { status: 'completed' });
      store.updateTask(task2.id, { status: 'completed' });

      store.clearCompleted();

      expect(store.tasks).toHaveLength(1);
      expect(store.tasks[0].title).toBe('任务3');

      Date.now = realDateNow;
    });

    it('没有已完成任务时无操作', () => {
      const store = useTaskStore();
      store.addTask({ title: '任务1' });

      store.clearCompleted();

      expect(store.tasks).toHaveLength(1);
    });
  });
});
