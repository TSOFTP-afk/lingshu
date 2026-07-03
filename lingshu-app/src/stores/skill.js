/**
 * Skills Store — 占位
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useSkillStore = defineStore('skill', () => {
  const skills = ref([]);

  async function fetchSkills(_bookId) {
    // TODO: 阶段 2 实现
  }

  return { skills, fetchSkills };
});
