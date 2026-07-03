/**
 * 章节 Store — 章节内容管理
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import api from '../utils/api';

export const useChapterStore = defineStore('chapter', () => {
  const chapters = ref([]);
  const currentChapter = ref(null);
  const loading = ref(false);
  const saving = ref(false);

  async function fetchChapters(bookId) {
    loading.value = true;
    try {
      const { data } = await api.get(`/workspace/books/${bookId}/chapters`);
      chapters.value = data.items || [];
    } finally {
      loading.value = false;
    }
  }

  async function fetchChapter(chapterId) {
    const { data } = await api.get(`/workspace/chapters/${chapterId}`);
    currentChapter.value = data;
    return data;
  }

  async function createChapter(bookId, title, volumeId = null) {
    const path = volumeId
      ? `/workspace/volumes/${volumeId}/chapters`
      : `/workspace/books/${bookId}/chapters`;
    const { data } = await api.post(path, { title });
    chapters.value.push(data.item || data);
    return data.item || data;
  }

  async function saveChapter(chapterId, payload) {
    saving.value = true;
    try {
      const { data } = await api.patch(`/workspace/chapters/${chapterId}`, payload);
      currentChapter.value = data.item || data;
      return data;
    } finally {
      saving.value = false;
    }
  }

  async function deleteChapter(chapterId) {
    await api.delete(`/workspace/chapters/${chapterId}`);
    chapters.value = chapters.value.filter(c => c.id !== chapterId);
  }

  return { chapters, currentChapter, loading, saving, fetchChapters, fetchChapter, createChapter, saveChapter, deleteChapter };
});
