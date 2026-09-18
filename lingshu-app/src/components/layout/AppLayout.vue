<template>
  <div
    class="app-layout"
    :class="themeClass"
  >
    <SideNav v-model:drawer-open="drawerOpen" />

    <div class="app-main">
      <!-- 顶栏 -->
      <GlobalHeaderBar
        @chat="showChat = true"
        @open-drawer="drawerOpen = true"
      />

      <!-- 主体内容区（由子路由填充） -->
      <main class="app-body">
        <router-view />
      </main>

      <!-- 底栏 -->
      <StatusBar />

      <!-- 全局对话框 -->
      <AiChatPanel v-model="showChat" />
      <CorrectionPanel
        v-model="showCorrect"
        :seed="correctionSeed"
      />
      <ExportDialog v-model="showExport" />
      <SearchPanel
        v-model="showSearch"
        :seed="searchSeed"
      />
      <StarGraphView v-model="showStarGraph" />
      <ReferenceBooksView v-model="showReference" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { useEventBus } from '../../composables/useEventBus';
import { useThemeStore } from '../../stores/theme';
import GlobalHeaderBar from './GlobalHeaderBar.vue';
import SideNav from './SideNav.vue';
import StatusBar from './StatusBar.vue';
import AiChatPanel from '../dialogs/AiChatPanel.vue';
import CorrectionPanel from '../dialogs/CorrectionPanel.vue';
import ExportDialog from '../dialogs/ExportDialog.vue';
import SearchPanel from '../dialogs/SearchPanel.vue';
import StarGraphView from '../star-graph/StarGraphView.vue';
import ReferenceBooksView from '../dialogs/ReferenceBooksView.vue';

const theme = useThemeStore();
const themeClass = computed(() => theme.current !== 'white' ? `theme-${theme.current}` : '');
const { on, off, emit } = useEventBus();

// 侧栏抽屉态（<768px）
const drawerOpen = ref(false);

// 对话框显隐状态
const showChat = ref(false);
const showCorrect = ref(false);
const showExport = ref(false);
const showSearch = ref(false);
const showStarGraph = ref(false);
const showReference = ref(false);
const searchSeed = ref({ token: 0, query: '' });
const correctionSeed = ref({ token: 0, text: '' });

function openReference() {
  showReference.value = true;
}

function openStarGraph() {
  showStarGraph.value = true;
}

function openSearch(payload) {
  searchSeed.value = {
    token: Date.now(),
    query: String(payload?.query || ''),
  };
  showSearch.value = true;
}

function openChat() {
  showChat.value = true;
}

function openCorrection(event) {
  correctionSeed.value = {
    token: Date.now(),
    text: String(event?.detail?.text || ''),
  };
  showCorrect.value = true;
}

let removeElectronSearchListener = null;

function onWindowOpenSearch(event) {
  openSearch(event?.detail);
}

onMounted(() => {
  applyStoredViewSettings();
  on('lingshu:reference', openReference);
  on('lingshu:star-graph', openStarGraph);
  on('lingshu:open-chat', openChat);
  on('lingshu:open-correction', openCorrection);
  on('lingshu:open-search', openSearch);
  window.addEventListener('lingshu:open-search', onWindowOpenSearch);
  removeElectronSearchListener = window.lingshu?.onOpenSearch?.(openSearch) || null;
});

onUnmounted(() => {
  off('lingshu:reference', openReference);
  off('lingshu:star-graph', openStarGraph);
  off('lingshu:open-chat', openChat);
  off('lingshu:open-correction', openCorrection);
  off('lingshu:open-search', openSearch);
  window.removeEventListener('lingshu:open-search', onWindowOpenSearch);
  removeElectronSearchListener?.();
});

function applyStoredViewSettings() {
  const fontSize = Number.parseInt(localStorage.getItem('lingshu_font_size') || '15', 10);
  const lineHeight = Number.parseInt(localStorage.getItem('lingshu_line_height') || '160', 10);
  const safeFontSize = Number.isFinite(fontSize) ? fontSize : 15;
  const safeLineHeight = Number.isFinite(lineHeight) ? lineHeight : 160;
  document.documentElement.style.setProperty('--editor-font-size', `${safeFontSize}px`);
  document.documentElement.style.setProperty('--editor-line-height', `${Math.round(safeFontSize * safeLineHeight / 100)}px`);
  document.body.classList.toggle('focus-mode', localStorage.getItem('lingshu_focus_default') === '1');
}
</script>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: row;
  height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  overflow: hidden;
}

.app-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  height: 100vh;
}

.app-body {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}
</style>
