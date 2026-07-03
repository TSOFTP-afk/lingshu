<template>
  <div class="drawer-panel">
    <div class="drawer-titlebar">
      <span class="drawer-title">工具箱</span>
    </div>

    <el-tabs
      v-model="activeTab"
      class="drawer-tabs"
    >
      <el-tab-pane name="overview">
        <template #label>
          <span class="drawer-tab-label"><el-icon><Histogram /></el-icon>概览</span>
        </template>
        <OverviewTab />
      </el-tab-pane>
      <el-tab-pane
        v-if="showShortcuts"
        name="shortcuts"
      >
        <template #label>
          <span class="drawer-tab-label"><el-icon><Operation /></el-icon>快捷键</span>
        </template>
        <ShortcutsTab />
      </el-tab-pane>
      <el-tab-pane name="characters">
        <template #label>
          <span class="drawer-tab-label"><el-icon><User /></el-icon>人物</span>
        </template>
        <CharactersTab />
      </el-tab-pane>
      <el-tab-pane name="world">
        <template #label>
          <span class="drawer-tab-label"><el-icon><Guide /></el-icon>世界</span>
        </template>
        <WorldTab />
      </el-tab-pane>
      <el-tab-pane name="skills">
        <template #label>
          <span class="drawer-tab-label"><el-icon><Collection /></el-icon>Skills</span>
        </template>
        <SkillsTab />
      </el-tab-pane>
      <el-tab-pane name="generate">
        <template #label>
          <span class="drawer-tab-label"><el-icon><MagicStick /></el-icon>生成</span>
        </template>
        <GenerateTab />
      </el-tab-pane>
      <el-tab-pane name="analysis">
        <template #label>
          <span class="drawer-tab-label"><el-icon><DataAnalysis /></el-icon>分析</span>
        </template>
        <AnalysisTab />
      </el-tab-pane>
      <el-tab-pane name="probe">
        <template #label>
          <span class="drawer-tab-label"><el-icon><Aim /></el-icon>探针</span>
        </template>
        <ProbeTab />
      </el-tab-pane>
      <el-tab-pane name="foreshadow">
        <template #label>
          <span class="drawer-tab-label"><el-icon><Connection /></el-icon>伏笔</span>
        </template>
        <ForeshadowTab />
      </el-tab-pane>
      <el-tab-pane name="review">
        <template #label>
          <span class="drawer-tab-label"><el-icon><Tickets /></el-icon>记录</span>
        </template>
        <ReviewTab />
      </el-tab-pane>
      <el-tab-pane name="tasks">
        <template #label>
          <span class="drawer-tab-label"><el-icon><List /></el-icon>任务</span>
        </template>
        <TasksTab />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue';
import {
  Aim,
  Collection,
  Connection,
  DataAnalysis,
  Guide,
  Histogram,
  List,
  MagicStick,
  Operation,
  Tickets,
  User,
} from '@element-plus/icons-vue';
import { useEventBus } from '../../composables/useEventBus';
import OverviewTab from './OverviewTab.vue';
import ShortcutsTab from './ShortcutsTab.vue';
import CharactersTab from './CharactersTab.vue';
import WorldTab from './WorldTab.vue';
import SkillsTab from './SkillsTab.vue';
import GenerateTab from './GenerateTab.vue';
import AnalysisTab from './AnalysisTab.vue';
import ProbeTab from './ProbeTab.vue';
import ForeshadowTab from './ForeshadowTab.vue';
import ReviewTab from './ReviewTab.vue';
import TasksTab from './TasksTab.vue';

const props = defineProps({
  selectionKind: { type: String, default: 'none' },
});

const { on, off } = useEventBus();
const activeTab = ref('overview');
const showShortcuts = computed(() => props.selectionKind === 'book');
const validTabs = computed(() => new Set([
  'overview',
  ...(showShortcuts.value ? ['shortcuts'] : []),
  'characters',
  'world',
  'skills',
  'generate',
  'analysis',
  'probe',
  'foreshadow',
  'review',
  'tasks',
]));

watch(validTabs, (tabs) => {
  if (!tabs.has(activeTab.value)) activeTab.value = 'overview';
});

// 根据左侧选中节点类型自动切换标签页
watch(() => props.selectionKind, (kind, oldKind) => {
  if (kind === oldKind) return;
  const tabMap = {
    book: 'overview',
    volume: 'overview',
    chapter: 'analysis',
  };
  const target = tabMap[kind];
  if (target && validTabs.value.has(target)) {
    activeTab.value = target;
  }
});

function onOpenDrawerTab(payload) {
  const name = typeof payload === 'string' ? payload : payload?.name;
  if (validTabs.value.has(name)) activeTab.value = name;
}

onMounted(() => on('lingshu:drawer-tab', onOpenDrawerTab));
onUnmounted(() => off('lingshu:drawer-tab', onOpenDrawerTab));
</script>

<style scoped>
.drawer-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, var(--bg-secondary), var(--bg-tertiary));
  border-left: 1px solid var(--border-color);
}
.drawer-titlebar {
  display: flex;
  align-items: center;
  min-height: 54px;
  padding: 10px 18px 8px;
  border-bottom: 1px solid var(--border-light);
}
.drawer-title {
  font-size: var(--font-size-base);
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0;
}
.drawer-tabs {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.drawer-tabs :deep(.el-tabs__header) {
  margin: 0 8px;
}
.drawer-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--border-light);
}
.drawer-tabs :deep(.el-tabs__item) {
  height: 36px;
  padding: 0 9px;
}
.drawer-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: auto;
  padding: 12px;
  background: var(--bg-primary);
}
.drawer-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}
</style>
