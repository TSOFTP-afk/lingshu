// AnalysisTab 域拆分：V1 一次性管线（LEGACY，仅握手兼容保留）
// ctx 为主组件构造的共享上下文：跨域状态与函数一律通过 ctx 延迟读取（单一数据源，禁止复制）。
// 纯搬移自 src/components/drawer/AnalysisTab.vue，业务逻辑未改动。
import { ref, computed } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';

export function useAnalysisV1Legacy(ctx) {
  const { bookId, auth, confirmV3Action, emit } = ctx;

  const creatingV1OneShotRun = ref(false);
  const loadingV1Runs = ref(false);
  const loadingV1Cards = ref(false);
  const analysisV1Runs = ref([]);
  const analysisV1Cards = ref([]);
  const selectedV1RunId = ref(null);
  const v1CardDetailVisible = ref(false);
  const v1CardDetailCard = ref(null);
  const applyingV1Run = ref(false);

  const selectedV1Run = computed(() => analysisV1Runs.value.find(run => run.id === selectedV1RunId.value) || null);

  async function createV1OneShotRun() {
    if (!auth.requireAiAccess()) return;
    if (!bookId.value) return;
    creatingV1OneShotRun.value = true;
    analysisV1Cards.value = [];
    selectedV1RunId.value = null;
    try {
      const { data } = await api.post(`/workspace/books/${bookId.value}/analysis-v1/one-shot`, { use_ai: true });
      const runId = data.run_id || data.item?.id;
      ElMessage.success('V1 一次性读完分析已完成');
      await loadV1Runs(runId);
    } catch (error) {
      ElMessage.error(ctx.errorMessage(error) || 'V1 一次性读完分析失败');
    } finally {
      creatingV1OneShotRun.value = false;
    }
  }

  async function loadV1Runs(preferredRunId = null) {
    if (!bookId.value) return;
    loadingV1Runs.value = true;
    try {
      const { data } = await api.get(`/workspace/books/${bookId.value}/analysis/runs`);
      analysisV1Runs.value = data.items || [];
      const nextRunId = preferredRunId || selectedV1RunId.value || analysisV1Runs.value[0]?.id || null;
      if (nextRunId) await loadV1RunCards(nextRunId);
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载 V1 运行记录失败');
    } finally {
      loadingV1Runs.value = false;
    }
  }

  async function loadV1RunCards(runId) {
    if (!runId) return;
    selectedV1RunId.value = runId;
    loadingV1Cards.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis/runs/${runId}/cards`);
      analysisV1Cards.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载 V1 草案卡失败');
    } finally {
      loadingV1Cards.value = false;
    }
  }

  function openV1CardDetail(card) {
    v1CardDetailCard.value = card;
    v1CardDetailVisible.value = true;
  }

  async function applyV1Run(allowWeakEvidence = false) {
    if (!selectedV1RunId.value) return;
    const weakEvidenceAllowed = allowWeakEvidence === true;
    const confirmed = await confirmV3Action(
      `确认将 V1 分析运行 #${selectedV1RunId.value} 的草案写回到正式数据？此操作将更新正式数据。`,
      '确认写回',
    );
    if (!confirmed) return;
    applyingV1Run.value = true;
    try {
      const { data } = await api.post(`/workspace/analysis/runs/${selectedV1RunId.value}/apply`, {
        user_override: weakEvidenceAllowed,
        allow_weak_evidence: weakEvidenceAllowed,
      });
      ElMessage.success(`写回成功：${data.applied_cards || 0} 张卡已应用`);
      v1CardDetailVisible.value = false;
      await loadV1Runs(selectedV1RunId.value);
      // 通知其他组件刷新业务数据
      emit('lingshu:characters-updated', { bookId: bookId.value, source: 'v1_writeback' });
      emit('lingshu:world-updated', { bookId: bookId.value, source: 'v1_writeback' });
      emit('lingshu:book-updated', { bookId: bookId.value, source: 'v1_writeback' });
    } catch (error) {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;
      // 409 = 证据不足，提示用户是否弱证据覆盖
      if (status === 409 && detail?.requires_user_override) {
        const retry = await confirmV3Action(
          '分析草案证据不足，是否以弱证据模式强制写回？',
          '弱证据写回',
        );
        if (retry) {
          applyingV1Run.value = false;
          return applyV1Run(true);
        }
      }
      ElMessage.error(ctx.errorMessage(error) || '写回失败');
    } finally {
      applyingV1Run.value = false;
    }
  }

  return {
    creatingV1OneShotRun,
    loadingV1Runs,
    loadingV1Cards,
    analysisV1Runs,
    analysisV1Cards,
    selectedV1RunId,
    v1CardDetailVisible,
    v1CardDetailCard,
    applyingV1Run,
    selectedV1Run,
    createV1OneShotRun,
    loadV1Runs,
    loadV1RunCards,
    openV1CardDetail,
    applyV1Run,
  };
}
