/**
 * 生成 Store — 管理章节生成快照与写作技巧 Skills
 *
 * 对应后端:
 *   /workspace/chapters/{chapter_id}/generation-snapshots
 *   /workspace/generation-snapshots/{snapshot_id}
 *   /workspace/writing-techniques/skills
 *   /workspace/writing-techniques/to-selected-skills
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import api from '../utils/api';

export const useGenerationStore = defineStore('generation', () => {
  const snapshots = ref([]);
  const writingSkills = ref([]);
  const selectedSkillIds = ref([]);
  const loading = ref(false);

  async function fetchSnapshots(chapterId) {
    if (!chapterId) {
      snapshots.value = [];
      return;
    }
    loading.value = true;
    try {
      const { data } = await api.get(`/workspace/chapters/${chapterId}/generation-snapshots`);
      snapshots.value = data.items || [];
    } catch {
      snapshots.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function createSnapshot(chapterId, payload) {
    const { data } = await api.post(`/workspace/chapters/${chapterId}/generation-snapshots`, payload);
    return data.item;
  }

  async function deleteSnapshot(snapshotId) {
    await api.delete(`/workspace/generation-snapshots/${snapshotId}`);
  }

  async function restoreSnapshot(snapshotId) {
    const { data } = await api.post(`/workspace/generation-snapshots/${snapshotId}/restore`);
    return data.item;
  }

  async function fetchWritingSkills() {
    try {
      const { data } = await api.get(`/workspace/writing-techniques/skills`);
      writingSkills.value = data.items || [];
    } catch {
      writingSkills.value = [];
    }
  }

  async function toSelectedSkills(skillIds) {
    if (!skillIds || !skillIds.length) return [];
    const { data } = await api.post(`/workspace/writing-techniques/to-selected-skills`, { skill_ids: skillIds });
    return data.items || [];
  }

  function clearSnapshots() {
    snapshots.value = [];
    selectedSkillIds.value = [];
  }

  return {
    snapshots,
    writingSkills,
    selectedSkillIds,
    loading,
    fetchSnapshots,
    createSnapshot,
    deleteSnapshot,
    restoreSnapshot,
    fetchWritingSkills,
    toSelectedSkills,
    clearSnapshots,
  };
});
