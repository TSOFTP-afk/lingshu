// AnalysisTab 域拆分：探针（文章探针 plans/results + 主动探针 + localStorage 历史 + 冲突复核）
// ctx 为主组件构造的共享上下文：跨域状态与函数一律通过 ctx 延迟读取（单一数据源，禁止复制）。
// 纯搬移自 src/components/drawer/AnalysisTab.vue，业务逻辑未改动。
import { ref, computed } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';

export function useAnalysisProbes(ctx) {
  const { bookId, selectedV3RunId } = ctx;

  const loadingV3ProbePlans = ref(false);
  const loadingV3ProbeResults = ref(false);
  const analysisV3ProbePlans = ref([]);
  const analysisV3ProbeResults = ref([]);
  const activeProbeQuery = ref('');
  const activeProbeLoading = ref(false);
  const activeProbeResults = ref([]);

  const probeConflictResults = computed(() => analysisV3ProbeResults.value.filter(result => (
    result.consistency === 'inconsistent' || result.status === 'manual_review' || result.result?.manual_review_required
  )));

  const probeManualReviewCount = computed(() => probeConflictResults.value.length);

  const activeProbeResultsOnly = computed(() =>
    analysisV3ProbeResults.value.filter(r => r.probe_mode !== 'passive')
  );
  const activeProbePlansOnly = computed(() =>
    analysisV3ProbePlans.value.filter(p => p.probe_mode !== 'passive')
  );

  async function loadV3ProbePlans(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3ProbePlans.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/probes/plans`);
      analysisV3ProbePlans.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载文章探针计划失败');
    } finally {
      loadingV3ProbePlans.value = false;
    }
  }

  async function loadV3ProbeResults(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3ProbeResults.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/probes/results`);
      analysisV3ProbeResults.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载文章探针结果失败');
    } finally {
      loadingV3ProbeResults.value = false;
    }
  }

  async function runActiveProbe() {
    const query = activeProbeQuery.value.trim();
    if (!query) return;
    const bid = bookId.value;
    if (!bid) {
      ElMessage.warning('请先选择一本书');
      return;
    }
    activeProbeLoading.value = true;
    try {
      const { data } = await api.post(`/workspace/books/${bid}/active-probe`, { query });
      const result = { ...data, id: Date.now() };
      activeProbeResults.value.unshift(result);
      saveActiveProbeHistory(bid, result);
      activeProbeQuery.value = '';
    } catch (e) {
      ElMessage.error(e.response?.data?.detail || '主动探针执行失败');
    } finally {
      activeProbeLoading.value = false;
    }
  }

  function saveActiveProbeHistory(bookId, result) {
    const key = `lingshu_active_probes_${bookId}`;
    try {
      const existing = JSON.parse(localStorage.getItem(key) || '[]');
      existing.unshift(result);
      localStorage.setItem(key, JSON.stringify(existing.slice(0, 20)));
    } catch { /* ignore */ }
  }

  function loadActiveProbeHistory(bookId) {
    const key = `lingshu_active_probes_${bookId}`;
    try {
      activeProbeResults.value = JSON.parse(localStorage.getItem(key) || '[]');
    } catch {
      activeProbeResults.value = [];
    }
  }

  return {
    loadingV3ProbePlans,
    loadingV3ProbeResults,
    analysisV3ProbePlans,
    analysisV3ProbeResults,
    activeProbeQuery,
    activeProbeLoading,
    activeProbeResults,
    probeConflictResults,
    probeManualReviewCount,
    activeProbeResultsOnly,
    activeProbePlansOnly,
    loadV3ProbePlans,
    loadV3ProbeResults,
    runActiveProbe,
    loadActiveProbeHistory,
  };
}
