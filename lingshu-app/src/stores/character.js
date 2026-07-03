/**
 * 人物 Store — 管理人物卡列表状态，支持写回事件自动刷新
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import api from '../utils/api';
import { useEventBus } from '../composables/useEventBus';

export const useCharacterStore = defineStore('character', () => {
  const characters = ref([]);
  const characterSchemas = ref({ protagonist: [], supporting: [] });
  const loading = ref(false);
  const lastBookId = ref(null);
  let _busListenersBound = false;

  // 状态机相关状态
  const currentStateMachine = ref(null);      // 当前选中人物的状态机
  const cycles = ref([]);                      // 当前人物的循环日志列表
  const snapshots = ref([]);                   // 当前人物的快照存档列表
  const stateMachineLoading = ref(false);      // 状态机加载状态
  const currentCharacterId = ref(null);        // 当前查看的 character_id

  async function fetchCharacters(bookId) {
    if (!bookId) {
      characters.value = [];
      characterSchemas.value = { protagonist: [], supporting: [] };
      return;
    }
    lastBookId.value = bookId;
    loading.value = true;
    try {
      const { data } = await api.get(`/workspace/books/${bookId}/characters`);
      characters.value = data.items || [];
      characterSchemas.value = data.schemas || characterSchemas.value;
    } catch {
      characters.value = [];
    } finally {
      loading.value = false;
    }
  }

  function refresh() {
    if (lastBookId.value) fetchCharacters(lastBookId.value);
  }

  // ============ 状态机相关 actions ============

  async function fetchStateMachine(characterId) {
    if (!characterId) { currentStateMachine.value = null; return; }
    currentCharacterId.value = characterId;
    stateMachineLoading.value = true;
    try {
      const { data } = await api.get(`/workspace/characters/${characterId}/state-machine`);
      currentStateMachine.value = data.item || null;
    } catch {
      currentStateMachine.value = null;
    } finally {
      stateMachineLoading.value = false;
    }
  }

  async function updateStateMachine(characterId, payload) {
    // payload: {desire_text: "...", mbti_type: "...", ...} 仅含需更新字段
    const { data } = await api.patch(`/workspace/characters/${characterId}/state-machine`, payload);
    if (data.item) currentStateMachine.value = data.item;
    return data.item;
  }

  async function fetchCycles(characterId, cycleType = null) {
    if (!characterId) { cycles.value = []; return; }
    const params = cycleType ? `?cycle_type=${cycleType}` : '';
    try {
      const { data } = await api.get(`/workspace/characters/${characterId}/cycles${params}`);
      cycles.value = data.items || [];
    } catch {
      cycles.value = [];
    }
  }

  async function createCycle(characterId, cycleData) {
    const { data } = await api.post(`/workspace/characters/${characterId}/cycles`, cycleData);
    // 创建后刷新循环列表与状态机（累计增值可能变化）
    await fetchCycles(characterId);
    await fetchStateMachine(characterId);
    return data.item;
  }

  async function fetchSnapshots(characterId) {
    if (!characterId) { snapshots.value = []; return; }
    try {
      const { data } = await api.get(`/workspace/characters/${characterId}/snapshots`);
      snapshots.value = data.items || [];
    } catch {
      snapshots.value = [];
    }
  }

  async function createSnapshot(characterId, payload = {}) {
    const { data } = await api.post(`/workspace/characters/${characterId}/snapshots`, payload);
    await fetchSnapshots(characterId);
    return data.item;
  }

  function clearStateMachine() {
    currentStateMachine.value = null;
    cycles.value = [];
    snapshots.value = [];
    currentCharacterId.value = null;
  }

  function _bindBusListeners() {
    if (_busListenersBound) return;
    const { on } = useEventBus();
    on('lingshu:characters-updated', (payload) => {
      if (!payload || !lastBookId.value) return;
      if (payload.bookId && Number(payload.bookId) !== Number(lastBookId.value)) return;
      refresh();
    });
    on('lingshu:writeback-completed', (payload) => {
      if (!payload || !lastBookId.value) return;
      if (payload.bookId && Number(payload.bookId) !== Number(lastBookId.value)) return;
      // 仅当写回目标是 character 或批量写回时刷新
      if (payload.writebackTarget && payload.writebackTarget !== 'character') return;
      refresh();
    });
    _busListenersBound = true;
  }

  // 首次调用时绑定事件监听
  _bindBusListeners();

  return {
    // 现有
    characters, characterSchemas, loading, fetchCharacters, refresh,
    // 状态机相关
    currentStateMachine, cycles, snapshots, stateMachineLoading, currentCharacterId,
    fetchStateMachine, updateStateMachine, fetchCycles, createCycle,
    fetchSnapshots, createSnapshot, clearStateMachine,
  };
});
