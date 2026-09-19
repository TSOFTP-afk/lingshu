// ContentEditor 域拆分：写作探针伴随（8 秒防抖触发后台扫描 + 探针配置加载 + 定时器生命周期）
// ctx 为组件构造的共享上下文：props 为组件单一数据源（章节 ID、内容变化触发点仍留在组件）。
// 生命周期钩子在 composable 内注册（setup 同步期调用，合法）。纯搬移自 src/components/workspace/ContentEditor.vue。
import { ref, watch, onMounted, onUnmounted } from 'vue';
import api from '../../utils/api';
import { useEventBus } from '../useEventBus';
import { useBookStore } from '../../stores/book';

export function useEditorProbePolling(ctx) {
  const { props } = ctx;
  const bookStore = useBookStore();
  const { emit: busEmit } = useEventBus();

  // 写作探针伴随：8 秒防抖触发后台扫描
  const PROBE_DEFAULT_INTERVAL_MS = 8000;
  const probeTimer = ref(null);
  const probeIntervalMs = ref(PROBE_DEFAULT_INTERVAL_MS);
  const probeConfigLoaded = ref(false);

  function clearProbeTimer() {
    if (probeTimer.value) {
      clearTimeout(probeTimer.value);
      probeTimer.value = null;
    }
  }

  function scheduleProbeScan() {
    if (!props.chapterId || !bookStore.currentBookId) return;
    if (probeIntervalMs.value <= 0) return; // 探针未启用
    clearProbeTimer();
    probeTimer.value = setTimeout(() => {
      probeTimer.value = null;
      triggerProbeScan();
    }, probeIntervalMs.value);
  }

  async function triggerProbeScan() {
    const bookId = bookStore.currentBookId;
    const chapterId = props.chapterId;
    if (!bookId || !chapterId) return;
    try {
      const { data } = await api.post(
        `/workspace/books/${bookId}/chapters/${chapterId}/writing-probe`,
      );
      // 仅当本次扫描产生新草稿时通知 ProbeTab 刷新
      const newChars = data?.character_drafts?.length || 0;
      const newSummary = !!data?.summary_draft;
      if (newChars > 0 || newSummary) {
        busEmit('lingshu:probe-scan-completed', { book_id: bookId, chapter_id: chapterId });
      }
    } catch (e) {
      // 静默失败：探针未启用（403）、未登录（401）等不打扰用户写作
    }
  }

  async function loadProbeConfig() {
    if (probeConfigLoaded.value) return;
    probeConfigLoaded.value = true;
    try {
      const { data } = await api.get('/settings/ai');
      const probe = data?.profiles?.writing_probe;
      if (probe) {
        if (probe.interval_seconds && probe.interval_seconds >= 5) {
          probeIntervalMs.value = probe.interval_seconds * 1000;
        }
        // 探针未启用时禁用自动扫描
        if (probe.probe_enabled === false) {
          probeIntervalMs.value = 0;
        }
      }
    } catch (e) {
      // 配置加载失败时使用默认 8 秒间隔
    }
  }

  // 章节切换时清空探针定时器，避免旧章节的扫描覆盖新章节
  watch(() => props.chapterId, () => {
    clearProbeTimer();
  });

  onMounted(() => {
    loadProbeConfig();
  });

  onUnmounted(() => {
    clearProbeTimer();
  });

  return {
    probeTimer,
    probeIntervalMs,
    scheduleProbeScan,
    triggerProbeScan,
    loadProbeConfig,
    clearProbeTimer,
  };
}
