// AnalysisTab 域拆分：V3 运行记录 / 明细加载（blocks/mentions/entities/facts/cards/events）/ 阶段条 / createV3Run
// ctx 为主组件构造的共享上下文：跨域状态与函数一律通过 ctx 延迟读取（单一数据源，禁止复制）。
// 纯搬移自 src/components/drawer/AnalysisTab.vue，业务逻辑未改动。
import { ref, computed } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';

const DEFAULT_V3_STAGES = [
  { key: 'init', phase: 'M0', label: '初始化' },
  { key: 'l1_semantic_blocks', phase: 'M1', label: '语义分块' },
  { key: 'entity_mentions', phase: 'M2', label: '实体提及抽取' },
  { key: 'entity_coreference', phase: 'M3', label: '共指消解' },
  { key: 'identity_resolve', phase: 'M3+', label: '身份消解' },
  { key: 'atomic_facts', phase: 'M4', label: '原子事实抽取' },
  { key: 'memory_layer', phase: 'M7', label: '记忆分层' },
  { key: 'card_events', phase: 'M5', label: '卡片生成' },
  { key: 'card_post_process', phase: 'M5+', label: '卡片后处理' },
  { key: 'probe_plans', phase: 'M8', label: '文章探针' },
  { key: 'completed', phase: 'Done', label: '完成' },
];

function normalizeV3Stages(rawStages) {
  const source = Array.isArray(rawStages) && rawStages.length ? rawStages : DEFAULT_V3_STAGES;
  return source.map((stage, index) => ({
    key: String(stage?.key || `stage_${index}`),
    phase: String(stage?.phase || `S${index + 1}`),
    label: String(stage?.label || stage?.key || `阶段 ${index + 1}`),
  }));
}

export function useAnalysisV3Runs(ctx) {
  const { auth, bookId, selectedV3RunId, runV3AnalysisOverWs } = ctx;

  const creatingV3Run = ref(false);
  const analysisV3Progress = ref({ percent: 0, message: '' });
  const runningIncrementalV3Run = ref(false);
  const useAiAnalysis = ref(false);
  const runningMemoryLayer = ref(false);
  const runningProbes = ref(false);
  const loadingV3Runs = ref(false);
  const loadingV3Blocks = ref(false);
  const loadingV3Mentions = ref(false);
  const loadingV3Entities = ref(false);
  const loadingV3Facts = ref(false);
  const loadingV3Cards = ref(false);
  const loadingV3Events = ref(false);
  const analysisV3Runs = ref([]);
  const analysisV3Blocks = ref([]);
  const analysisV3Mentions = ref([]);
  const analysisV3Entities = ref([]);
  const analysisV3Facts = ref([]);
  const analysisV3Cards = ref([]);
  const analysisV3Events = ref([]);
  const analysisV3WorkflowTab = ref('overview');

  const selectedV3Run = computed(() => analysisV3Runs.value.find(run => run.id === selectedV3RunId.value) || null);

  function currentV3StageIndexForRun(run) {
    const stages = normalizeV3Stages(run?.meta?.stages);
    const explicit = Number(run?.meta?.current_stage_index);
    if (Number.isFinite(explicit) && explicit >= 0) {
      return Math.min(explicit, Math.max(0, stages.length - 1));
    }
    const step = String(run?.meta?.current_step || '');
    const normalizedStep = step === 'article_probes' ? 'probe_plans' : step === 'workflow_ui' ? 'completed' : step;
    const byStep = stages.findIndex(stage => stage.key === normalizedStep);
    if (byStep >= 0) return byStep;
    const phase = String(run?.meta?.current_phase || '');
    const byPhase = stages.findIndex(stage => stage.phase === phase);
    if (byPhase >= 0) return byPhase;
    if (['probes_ready', 'completed'].includes(String(run?.status || ''))) {
      return Math.max(0, stages.length - 1);
    }
    return 0;
  }

  function currentV3StageTextForRun(run) {
    const stages = normalizeV3Stages(run?.meta?.stages);
    const index = currentV3StageIndexForRun(run);
    return run?.meta?.current_stage_label || stages[index]?.label || run?.meta?.current_phase || 'M0';
  }

  const currentV3StageIndex = computed(() => currentV3StageIndexForRun(selectedV3Run.value));

  const currentV3StageText = computed(() => currentV3StageTextForRun(selectedV3Run.value));

  const v3StageItems = computed(() => {
    const stages = normalizeV3Stages(selectedV3Run.value?.meta?.stages);
    const currentIndex = currentV3StageIndex.value;
    return stages.map((stage, index) => ({
      ...stage,
      state: index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'pending',
    }));
  });

  async function loadV3Blocks(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3Blocks.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/blocks`);
      analysisV3Blocks.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载语义块失败');
    } finally {
      loadingV3Blocks.value = false;
    }
  }

  async function loadV3Mentions(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3Mentions.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/mentions`);
      analysisV3Mentions.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载提及候选失败');
    } finally {
      loadingV3Mentions.value = false;
    }
  }

  async function loadV3Entities(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3Entities.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/entities`);
      analysisV3Entities.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载实体候选失败');
    } finally {
      loadingV3Entities.value = false;
    }
  }

  async function loadV3Facts(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3Facts.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/facts`);
      analysisV3Facts.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载原子事实失败');
    } finally {
      loadingV3Facts.value = false;
    }
  }

  async function loadV3Cards(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3Cards.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/cards`);
      analysisV3Cards.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载 V3 草案卡失败');
    } finally {
      loadingV3Cards.value = false;
    }
  }

  async function loadV3Events(runId) {
    if (!runId) return;
    selectedV3RunId.value = runId;
    loadingV3Events.value = true;
    try {
      const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/events`);
      analysisV3Events.value = data.items || [];
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '加载 V3 卡片事件失败');
    } finally {
      loadingV3Events.value = false;
    }
  }

  async function runMemoryLayer() {
    if (!selectedV3RunId.value) return;
    runningMemoryLayer.value = true;
    try {
      const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/steps/memory_layer`);
      ElMessage.success(`记忆分层完成：${data.classified_fact_count || 0} 条事实，${data.summary_fact_count || 0} 条摘要`);
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
      await ctx.loadV3Runs(selectedV3RunId.value);
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '记忆分层失败');
    } finally {
      runningMemoryLayer.value = false;
    }
  }

  async function runProbes() {
    if (!selectedV3RunId.value) return;
    runningProbes.value = true;
    try {
      const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/steps/probes`);
      ElMessage.success(`文章探针完成：${data.probe_plan_count || 0} 个计划，${data.probe_result_count || 0} 个结果`);
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
      await ctx.loadV3Runs(selectedV3RunId.value);
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '文章探针失败');
    } finally {
      runningProbes.value = false;
    }
  }

  async function createV3Run() {
    if (!auth.requireAiAccess()) return;
    if (!bookId.value) return;
    creatingV3Run.value = true;
    analysisV3Progress.value = { percent: 0, message: 'V3 分析启动中...' };
    analysisV3Blocks.value = [];
    analysisV3Mentions.value = [];
    analysisV3Entities.value = [];
    analysisV3Facts.value = [];
    analysisV3Cards.value = [];
    analysisV3Events.value = [];
    ctx.analysisV3ProbePlans.value = [];
    ctx.analysisV3ProbeResults.value = [];
    ctx.analysisV3BacktrackTasks.value = [];
    ctx.analysisV3Review.value = null;
    ctx.entityVersionsForReview.value = [];
    ctx.resetEntityReviewForms();
    try {
      const data = await runV3AnalysisOverWs();
      const runId = data.run_id || data.item?.id;
      ElMessage.success('全书分析已完成');
      await ctx.loadV3Runs(runId);
    } catch (error) {
      ElMessage.error(ctx.errorMessage(error) || '分析失败');
      analysisV3Progress.value = { percent: 0, message: '' };
    } finally {
      creatingV3Run.value = false;
    }
  }

  async function createIncrementalV3Run() {
    if (!auth.requireAiAccess()) return;
    if (!bookId.value || !selectedV3RunId.value) return;
    runningIncrementalV3Run.value = true;
    try {
      const { data } = await api.post(`/workspace/books/${bookId.value}/analysis-v3/incremental`, {
        base_run_id: selectedV3RunId.value,
        use_ai: useAiAnalysis.value,
      });
      const runId = data.run_id || data.item?.id;
      ElMessage.success('增量更新已完成');
      await ctx.loadV3Runs(runId);
    } catch (error) {
      ElMessage.error(ctx.errorMessage(error) || '增量分析失败');
    } finally {
      runningIncrementalV3Run.value = false;
    }
  }

  return {
    creatingV3Run,
    analysisV3Progress,
    runningIncrementalV3Run,
    useAiAnalysis,
    runningMemoryLayer,
    runningProbes,
    loadingV3Runs,
    loadingV3Blocks,
    loadingV3Mentions,
    loadingV3Entities,
    loadingV3Facts,
    loadingV3Cards,
    loadingV3Events,
    analysisV3Runs,
    analysisV3Blocks,
    analysisV3Mentions,
    analysisV3Entities,
    analysisV3Facts,
    analysisV3Cards,
    analysisV3Events,
    analysisV3WorkflowTab,
    selectedV3Run,
    currentV3StageIndexForRun,
    currentV3StageTextForRun,
    currentV3StageIndex,
    currentV3StageText,
    v3StageItems,
    loadV3Blocks,
    loadV3Mentions,
    loadV3Entities,
    loadV3Facts,
    loadV3Cards,
    loadV3Events,
    runMemoryLayer,
    runProbes,
    createV3Run,
    createIncrementalV3Run,
  };
}
