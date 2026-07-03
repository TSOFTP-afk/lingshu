/**
 * 伏笔 store — 管理伏笔列表的加载、增删改查与同步。
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../utils/api';

export const useForeshadowStore = defineStore('foreshadow', () => {
  const items = ref([]);
  const loading = ref(false);
  const statusFilter = ref(''); // ''=全部 / pending / resolved / abandoned

  async function load(bookId, { status } = {}) {
    if (!bookId) {
      items.value = [];
      return;
    }
    loading.value = true;
    try {
      const params = {};
      if (status) params.status = status;
      const { data } = await api.get(`/workspace/books/${bookId}/foreshadows`, { params });
      items.value = data.items || [];
    } catch (e) {
      items.value = [];
      if (e.response?.status >= 500) {
        ElMessage.error('伏笔列表加载失败');
      }
    } finally {
      loading.value = false;
    }
  }

  async function create(bookId, payload) {
    const { data } = await api.post(`/workspace/books/${bookId}/foreshadows`, payload);
    items.value.unshift(data.item);
    return data.item;
  }

  async function update(foreshadowId, fields) {
    const { data } = await api.patch(`/workspace/foreshadows/${foreshadowId}`, fields);
    const idx = items.value.findIndex(it => it.id === foreshadowId);
    if (idx >= 0) items.value[idx] = data.item;
    return data.item;
  }

  async function remove(foreshadowId) {
    await api.delete(`/workspace/foreshadows/${foreshadowId}`);
    items.value = items.value.filter(it => it.id !== foreshadowId);
  }

  async function syncFromAnalysis(bookId) {
    const { data } = await api.post(`/workspace/books/${bookId}/foreshadows/sync`);
    if (data.added > 0) {
      ElMessage.success(`从分析同步 ${data.added} 条伏笔`);
      await load(bookId, { status: statusFilter.value || undefined });
    } else {
      ElMessage.info('暂无新的伏笔可同步');
    }
    return data.added;
  }

  return {
    items,
    loading,
    statusFilter,
    load,
    create,
    update,
    remove,
    syncFromAnalysis,
  };
});
