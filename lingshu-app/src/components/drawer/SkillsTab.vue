<template>
  <div class="skills-tab">
    <div class="tab-header">
      <span class="tab-title">Skills</span>
      <el-button
        size="small"
        text
        type="primary"
        :disabled="!bookId"
        @click="$emit('manage')"
      >
        完整管理
      </el-button>
    </div>

    <div
      v-if="groupedSkills.length"
      class="skills-list"
    >
      <div
        v-for="item in groupedSkills"
        :key="item.id"
        class="skill-item"
        :class="{ 'skill-item--active': selectedId === item.id }"
        @click="onSelect(item)"
      >
        <el-tag
          :type="scopeType(item.scope)"
          size="small"
          effect="plain"
        >
          {{ item.scope }}
        </el-tag>
        <span class="skill-name">{{ item.name }}</span>
        <span class="skill-category">{{ item.category }}</span>
      </div>
    </div>
    <el-empty
      v-else
      description="暂无已启用 Skills"
      :image-size="50"
    />

    <!-- Skill 详情预览 -->
    <div
      v-if="selectedSkill"
      class="skill-preview"
    >
      <div class="preview-line">
        <b>{{ selectedSkill.name }}</b>
      </div>
      <div class="preview-line">
        {{ selectedSkill.summary }}
      </div>
      <div class="preview-line preview-desc">
        {{ selectedSkill.instruction_text || '无指令' }}
      </div>
      <div class="preview-meta">
        来源: {{ selectedSkill.source_title || '-' }} · {{ selectedSkill.source_license || '未记录' }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue';
import { useBookStore } from '../../stores/book';
import api from '../../utils/api';

defineEmits(['manage']);

const bookStore = useBookStore();
const bookId = computed(() => bookStore.currentBookId);

const allSkills = ref([]);
const selectedId = ref(null);
const selectedSkill = ref(null);

const groupedSkills = computed(() => allSkills.value);

function scopeType(scope) {
  return scope === '全局' ? '' : scope === '书籍' ? 'success' : 'warning';
}

async function loadSkills() {
  if (!bookId.value) { allSkills.value = []; return; }
  try {
    const { data } = await api.get(`/workspace/books/${bookId.value}/skills`);
    const items = [
      ...(data.global || []).map(s => ({ ...s, scope: '全局' })),
      ...(data.book || []).map(s => ({ ...s, scope: '书籍' })),
    ];
    allSkills.value = items;
  } catch { allSkills.value = []; }
}

function onSelect(item) {
  selectedId.value = item.id;
  selectedSkill.value = item;
}

watch(bookId, loadSkills);
onMounted(loadSkills);
</script>

<style scoped>
.skills-tab { padding: 4px 0; }
.tab-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.skill-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: var(--radius-sm); cursor: pointer; font-size: 12px; transition: background var(--transition-fast); }
.skill-item:hover { background: var(--bg-hover); }
.skill-item--active { background: var(--bg-active); }
.skill-name { color: var(--text-primary); font-weight: 500; }
.skill-category { color: var(--text-placeholder); margin-left: auto; }
.skill-preview { margin-top: 12px; padding: 10px; background: var(--bg-tertiary); border-radius: var(--radius-sm); font-size: 12px; line-height: 1.6; }
.preview-desc { color: var(--text-secondary); }
.preview-meta { margin-top: 8px; color: var(--text-placeholder); font-size: 11px; }
</style>
