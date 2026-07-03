/**
 * 卡片社区 Store — 管理社区卡片列表、详情、上传与删除
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import api from '../utils/api';

export const useCommunityStore = defineStore('community', () => {
  // 列表数据
  const list = ref([]);
  const total = ref(0);
  const page = ref(1);
  const pageSize = ref(20);
  // 过滤类型: '' 全部 | 'world' | 'character'
  const filterType = ref('');
  // 当前展开行详情
  const currentDetail = ref(null);
  const loading = ref(false);
  // 当前展开行 ID
  const expandedId = ref(null);

  // 拉取社区卡片列表
  async function fetchList() {
    loading.value = true;
    try {
      const params = {
        page: page.value,
        page_size: pageSize.value,
      };
      if (filterType.value) {
        params.type = filterType.value;
      }
      const { data } = await api.get('/community/cards', { params });
      list.value = data.items || [];
      total.value = data.total || 0;
      page.value = data.page || page.value;
      pageSize.value = data.page_size || pageSize.value;
    } catch (e) {
      console.error('[community] fetchList 失败:', e);
      // 出错时保留现有列表
    } finally {
      loading.value = false;
    }
  }

  // 拉取单条卡片详情
  async function fetchDetail(postId) {
    try {
      const { data } = await api.get(`/community/cards/${postId}`);
      currentDetail.value = data;
      return data;
    } catch (e) {
      console.error('[community] fetchDetail 失败:', e);
      throw e;
    }
  }

  // 上传卡片到社区
  async function uploadCard(payload) {
    try {
      const { data } = await api.post('/community/cards', payload);
      return data;
    } catch (e) {
      if (e?.response?.status === 409) {
        throw new Error('该卡片已上传到社区', { cause: e });
      }
      const msg = e?.response?.data?.detail || e?.message || '上传失败';
      throw new Error(msg, { cause: e });
    }
  }

  // 删除社区卡片
  async function deletePost(postId) {
    try {
      await api.delete(`/community/cards/${postId}`);
      return true;
    } catch (e) {
      if (e?.response?.status === 403) {
        throw new Error('无权删除他人上传的卡片', { cause: e });
      }
      if (e?.response?.status === 404) {
        throw new Error('卡片不存在', { cause: e });
      }
      const msg = e?.response?.data?.detail || e?.message || '删除失败';
      throw new Error(msg, { cause: e });
    }
  }

  // 设置过滤类型并重新拉取
  async function setFilterType(type) {
    filterType.value = type;
    page.value = 1;
    await fetchList();
  }

  // 设置页码并重新拉取
  async function setPage(n) {
    page.value = n;
    await fetchList();
  }

  // 切换展开行
  async function toggleExpand(postId) {
    if (expandedId.value === postId) {
      expandedId.value = null;
      currentDetail.value = null;
      return;
    }
    expandedId.value = postId;
    await fetchDetail(postId);
  }

  return {
    list,
    total,
    page,
    pageSize,
    filterType,
    currentDetail,
    loading,
    expandedId,
    fetchList,
    fetchDetail,
    uploadCard,
    deletePost,
    setFilterType,
    setPage,
    toggleExpand,
  };
});
