/**
 * 世界观 Store — 管理世界观数据状态，支持写回事件自动刷新
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import api from '../utils/api';
import { useEventBus } from '../composables/useEventBus';

export const useWorldStore = defineStore('world', () => {
  const worldText = ref('');
  const worldData = ref({});
  const worldSchema = ref([]);
  const loading = ref(false);
  const lastBookId = ref(null);
  let _busListenersBound = false;

  async function fetchWorld(bookId) {
    if (!bookId) {
      worldText.value = '';
      worldData.value = {};
      worldSchema.value = [];
      return;
    }
    lastBookId.value = bookId;
    loading.value = true;
    try {
      const { data } = await api.get(`/workspace/books/${bookId}/world`);
      worldText.value = data.world_text || '';
      worldData.value = data.world_data || {};
      worldSchema.value = data.world_schema || [];
    } catch {
      worldText.value = '';
      worldData.value = {};
      worldSchema.value = [];
    } finally {
      loading.value = false;
    }
  }

  function refresh() {
    if (lastBookId.value) fetchWorld(lastBookId.value);
  }

  function setWorld({ worldText: wt, worldData: wd, worldSchema: ws } = {}) {
    if (wt !== undefined) worldText.value = wt;
    if (wd !== undefined) worldData.value = wd;
    if (ws !== undefined) worldSchema.value = ws;
  }

  function _bindBusListeners() {
    if (_busListenersBound) return;
    const { on } = useEventBus();
    on('lingshu:world-updated', (payload) => {
      if (!payload || !lastBookId.value) return;
      if (payload.bookId && Number(payload.bookId) !== Number(lastBookId.value)) return;
      refresh();
    });
    on('lingshu:writeback-completed', (payload) => {
      if (!payload || !lastBookId.value) return;
      if (payload.bookId && Number(payload.bookId) !== Number(lastBookId.value)) return;
      // 仅当写回目标是 world_entry 或批量写回时刷新
      if (payload.writebackTarget && payload.writebackTarget !== 'world_entry') return;
      refresh();
    });
    _busListenersBound = true;
  }

  // 首次调用时绑定事件监听
  _bindBusListeners();

  return { worldText, worldData, worldSchema, loading, fetchWorld, refresh, setWorld };
});
