// AnalysisTab 域拆分：回溯任务（加载 / 实体触发创建 / 执行 / 取消）
// ctx 为主组件构造的共享上下文：跨域状态与函数一律通过 ctx 延迟读取（单一数据源，禁止复制）。
// 纯搬移自 src/components/drawer/AnalysisTab.vue，业务逻辑未改动。
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';

export function useAnalysisBacktrack(ctx) {
  const { selectedV3RunId } = ctx;

  const loadingV3BacktrackTasks = ref(false);
  const analysisV3BacktrackTasks = ref([]);
  const creatingBacktrackEntityUid = ref(null);
  const executingBacktrackTaskId = ref(null);
  const cancellingBacktrackTaskId = ref(null);

  async function loadV3BacktrackTasks(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3BacktrackTasks.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/backtrack/tasks`);
      analysisV3BacktrackTasks.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载回溯任务失败');
    } finally {
      loadingV3BacktrackTasks.value = false;
    }
  }

  async function createEntityBacktrackTask(entity) {
    if (!selectedV3RunId.value || !entity?.entity_uid) return;
    const confirmed = await ctx.confirmV3Action(`创建 ${entity.canonical_name || entity.entity_uid} 的回溯任务？`, '创建回溯任务');
    if (!confirmed) return;
    creatingBacktrackEntityUid.value = entity.entity_uid;
    try {
      const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/backtrack/tasks`, {
        trigger_type: 'entity_updated',
        target_uid: entity.entity_uid,
        reason: 'manual frontend backtrack',
      });
      ElMessage.success(`已创建回溯任务：${data.item?.impact?.counts?.cards || 0} 张卡受影响`);
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '创建回溯任务失败');
    } finally {
      creatingBacktrackEntityUid.value = null;
    }
  }

  async function executeBacktrackTask(task) {
    if (!selectedV3RunId.value || !task?.id) return;
    const confirmed = await ctx.confirmV3Action(`执行回溯任务 ${task.task_uid || task.id}？`, '执行回溯');
    if (!confirmed) return;
    executingBacktrackTaskId.value = task.id;
    try {
      const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/backtrack/tasks/${task.id}/execute`);
      ElMessage.success(`回溯完成：重算 ${data.fact_count || 0} 条事实`);
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
      await ctx.loadV3Runs(selectedV3RunId.value);
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '执行回溯失败');
    } finally {
      executingBacktrackTaskId.value = null;
    }
  }

  async function cancelBacktrackTask(task) {
    if (!selectedV3RunId.value || !task?.id) return;
    const confirmed = await ctx.confirmV3Action(`取消回溯任务 ${task.task_uid || task.id}？`, '取消回溯');
    if (!confirmed) return;
    cancellingBacktrackTaskId.value = task.id;
    try {
      await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/backtrack/tasks/${task.id}/cancel`);
      ElMessage.success('回溯任务已取消');
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
      await ctx.loadV3Runs(selectedV3RunId.value);
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '取消回溯任务失败');
    } finally {
      cancellingBacktrackTaskId.value = null;
    }
  }

  function canCancelBacktrackTask(task) {
    return task && !['running', 'completed', 'cancelled'].includes(task.status);
  }

  return {
    loadingV3BacktrackTasks,
    analysisV3BacktrackTasks,
    creatingBacktrackEntityUid,
    executingBacktrackTaskId,
    cancellingBacktrackTaskId,
    loadV3BacktrackTasks,
    createEntityBacktrackTask,
    executeBacktrackTask,
    cancelBacktrackTask,
    canCancelBacktrackTask,
  };
}
