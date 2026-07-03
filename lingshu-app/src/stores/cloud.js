/**
 * 云端同步 Store — 管理书籍上传/同步状态
 */
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import api from '../utils/api';

export const useCloudStore = defineStore('cloud', () => {
  // 同步状态: 'idle' | 'uploading' | 'syncing' | 'synced' | 'error'
  const syncStatus = ref('idle');
  const syncError = ref('');
  const lastSyncedAt = ref(null);

  const isSyncing = computed(() => syncStatus.value === 'uploading' || syncStatus.value === 'syncing');

  async function uploadBookToCloud(bookId) {
    // 验证 bookId 为正整数
    if (!bookId || !Number.isInteger(bookId) || bookId <= 0) {
      syncError.value = '无效的书籍ID';
      return;
    }
    syncStatus.value = 'uploading';
    syncError.value = '';
    try {
      const { data } = await api.post(`/cloud/books/${bookId}/upload`);
      syncStatus.value = 'synced';
      lastSyncedAt.value = new Date().toISOString();
      return data;
    } catch (e) {
      syncStatus.value = 'error';
      syncError.value = e?.response?.data?.detail || e?.message || '上传失败';
      throw e;
    }
  }

  async function syncUploadedBooks() {
    syncStatus.value = 'syncing';
    syncError.value = '';
    try {
      const { data } = await api.post('/cloud/sync');
      syncStatus.value = 'synced';
      lastSyncedAt.value = new Date().toISOString();
      return data;
    } catch (e) {
      syncStatus.value = 'error';
      syncError.value = e?.response?.data?.detail || e?.message || '同步失败';
      throw e;
    }
  }

  async function downloadCloudBook(cloudBookId) {
    if (!cloudBookId || !Number.isInteger(cloudBookId) || cloudBookId <= 0) {
      syncError.value = '无效的云端书籍ID';
      return;
    }
    syncStatus.value = 'syncing';
    syncError.value = '';
    try {
      const { data } = await api.post(`/cloud/books/${cloudBookId}/download`);
      syncStatus.value = 'synced';
      lastSyncedAt.value = new Date().toISOString();
      return data;
    } catch (e) {
      syncStatus.value = 'error';
      syncError.value = e?.response?.data?.detail || e?.message || '下载失败';
      throw e;
    }
  }

  async function fetchSyncStatus() {
    try {
      const { data } = await api.get('/cloud/sync/status');
      return data;
    } catch {
      return null;
    }
  }

  function resetStatus() {
    syncStatus.value = 'idle';
    syncError.value = '';
  }

  return {
    syncStatus,
    syncError,
    lastSyncedAt,
    isSyncing,
    uploadBookToCloud,
    downloadCloudBook,
    syncUploadedBooks,
    fetchSyncStatus,
    resetStatus,
  };
});
