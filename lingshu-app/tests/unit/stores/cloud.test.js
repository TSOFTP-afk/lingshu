import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useCloudStore } from '../../../src/stores/cloud';

vi.mock('../../../src/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  getAuthToken: vi.fn(() => ''),
  setAuthToken: vi.fn(),
  buildWsUrl: vi.fn(),
  sendWsAuth: vi.fn(),
}));

import api from '../../../src/utils/api';

describe('useCloudStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  describe('初始状态', () => {
    it('初始时 syncStatus 为 idle，syncError 为空，lastSyncedAt 为 null', () => {
      const store = useCloudStore();
      expect(store.syncStatus).toBe('idle');
      expect(store.syncError).toBe('');
      expect(store.lastSyncedAt).toBeNull();
      expect(store.isSyncing).toBe(false);
    });
  });

  describe('isSyncing', () => {
    it('uploading 状态时 isSyncing 为 true', () => {
      const store = useCloudStore();
      store.syncStatus = 'uploading';
      expect(store.isSyncing).toBe(true);
    });

    it('syncing 状态时 isSyncing 为 true', () => {
      const store = useCloudStore();
      store.syncStatus = 'syncing';
      expect(store.isSyncing).toBe(true);
    });

    it('synced 状态时 isSyncing 为 false', () => {
      const store = useCloudStore();
      store.syncStatus = 'synced';
      expect(store.isSyncing).toBe(false);
    });

    it('idle 状态时 isSyncing 为 false', () => {
      const store = useCloudStore();
      store.syncStatus = 'idle';
      expect(store.isSyncing).toBe(false);
    });

    it('error 状态时 isSyncing 为 false', () => {
      const store = useCloudStore();
      store.syncStatus = 'error';
      expect(store.isSyncing).toBe(false);
    });
  });

  describe('uploadBookToCloud', () => {
    it('无效 bookId 时设置错误并返回', async () => {
      const store = useCloudStore();

      await store.uploadBookToCloud(null);
      expect(store.syncError).toBe('无效的书籍ID');
      expect(store.syncStatus).toBe('idle');

      await store.uploadBookToCloud(0);
      expect(store.syncError).toBe('无效的书籍ID');

      await store.uploadBookToCloud(-1);
      expect(store.syncError).toBe('无效的书籍ID');

      await store.uploadBookToCloud(1.5);
      expect(store.syncError).toBe('无效的书籍ID');
    });

    it('有效 bookId 时成功上传', async () => {
      api.post.mockResolvedValue({ data: { success: true } });

      const store = useCloudStore();
      const result = await store.uploadBookToCloud(1);

      expect(api.post).toHaveBeenCalledWith('/cloud/books/1/upload');
      expect(store.syncStatus).toBe('synced');
      expect(store.syncError).toBe('');
      expect(store.lastSyncedAt).not.toBeNull();
      expect(result).toEqual({ success: true });
    });

    it('上传失败时设置错误状态', async () => {
      api.post.mockRejectedValue({
        response: { data: { detail: '上传失败：文件过大' } },
      });

      const store = useCloudStore();
      await expect(store.uploadBookToCloud(1)).rejects.toThrow();

      expect(store.syncStatus).toBe('error');
      expect(store.syncError).toBe('上传失败：文件过大');
    });

    it('上传失败时处理无 detail 的错误', async () => {
      api.post.mockRejectedValue(new Error('Network Error'));

      const store = useCloudStore();
      await expect(store.uploadBookToCloud(1)).rejects.toThrow();

      expect(store.syncStatus).toBe('error');
      expect(store.syncError).toBe('Network Error');
    });
  });

  describe('syncUploadedBooks', () => {
    it('成功同步', async () => {
      api.post.mockResolvedValue({ data: { synced: true } });

      const store = useCloudStore();
      const result = await store.syncUploadedBooks();

      expect(api.post).toHaveBeenCalledWith('/cloud/sync');
      expect(store.syncStatus).toBe('synced');
      expect(store.lastSyncedAt).not.toBeNull();
      expect(result).toEqual({ synced: true });
    });

    it('同步失败时设置错误状态', async () => {
      api.post.mockRejectedValue({
        response: { data: { detail: '同步失败' } },
      });

      const store = useCloudStore();
      await expect(store.syncUploadedBooks()).rejects.toThrow();

      expect(store.syncStatus).toBe('error');
      expect(store.syncError).toBe('同步失败');
    });
  });

  describe('downloadCloudBook', () => {
    it('无效 cloudBookId 时设置错误并返回', async () => {
      const store = useCloudStore();

      await store.downloadCloudBook(null);
      expect(store.syncError).toBe('无效的云端书籍ID');

      await store.downloadCloudBook(0);
      expect(store.syncError).toBe('无效的云端书籍ID');

      await store.downloadCloudBook(-1);
      expect(store.syncError).toBe('无效的云端书籍ID');
    });

    it('有效 cloudBookId 时成功下载', async () => {
      api.post.mockResolvedValue({ data: { downloaded: true } });

      const store = useCloudStore();
      const result = await store.downloadCloudBook(5);

      expect(api.post).toHaveBeenCalledWith('/cloud/books/5/download');
      expect(store.syncStatus).toBe('synced');
      expect(store.lastSyncedAt).not.toBeNull();
      expect(result).toEqual({ downloaded: true });
    });

    it('下载失败时设置错误状态', async () => {
      api.post.mockRejectedValue({
        response: { data: { detail: '下载失败' } },
      });

      const store = useCloudStore();
      await expect(store.downloadCloudBook(5)).rejects.toThrow();

      expect(store.syncStatus).toBe('error');
      expect(store.syncError).toBe('下载失败');
    });
  });

  describe('fetchSyncStatus', () => {
    it('成功获取同步状态', async () => {
      const statusData = { status: 'synced', last_sync: '2024-01-01' };
      api.get.mockResolvedValue({ data: statusData });

      const store = useCloudStore();
      const result = await store.fetchSyncStatus();

      expect(api.get).toHaveBeenCalledWith('/cloud/sync/status');
      expect(result).toEqual(statusData);
    });

    it('获取失败时返回 null', async () => {
      api.get.mockRejectedValue(new Error('Network Error'));

      const store = useCloudStore();
      const result = await store.fetchSyncStatus();

      expect(result).toBeNull();
    });
  });

  describe('resetStatus', () => {
    it('重置状态为 idle', () => {
      const store = useCloudStore();
      store.syncStatus = 'error';
      store.syncError = '错误信息';

      store.resetStatus();

      expect(store.syncStatus).toBe('idle');
      expect(store.syncError).toBe('');
    });
  });
});
