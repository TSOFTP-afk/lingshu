<template>
  <div class="floating-chapter-toolbar">
    <el-tooltip
      content="润色选中文本"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button"
        :disabled="!chapterToolbar.hasContent || !auth.isLoggedIn"
        @click="sendAction('polish')"
      >
        <el-icon><MagicStick /></el-icon>
        <span class="btn-label">润色</span>
      </el-button>
    </el-tooltip>
    <el-tooltip
      content="检测当前章节 AI 生成概率"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button"
        :disabled="!chapterToolbar.hasContent || !auth.isLoggedIn"
        @click="sendAction('detect-ai')"
      >
        <el-icon><DataAnalysis /></el-icon>
        <span class="btn-label">AI率检测</span>
      </el-button>
    </el-tooltip>
    <el-tooltip
      content="保存当前章节"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button chapter-tool-button--primary"
        type="primary"
        :disabled="!chapterToolbar.dirty"
        @click="sendAction('save')"
      >
        <el-icon><DocumentChecked /></el-icon>
        <span class="btn-label">保存</span>
      </el-button>
    </el-tooltip>
    <el-tooltip
      content="删除所有未保存变动，恢复到最后一次保存"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button"
        :disabled="!chapterToolbar.dirty"
        @click="sendAction('revert')"
      >
        <el-icon><RefreshLeft /></el-icon>
        <span class="btn-label">回退</span>
      </el-button>
    </el-tooltip>
    <el-tooltip
      content="复制整章正文"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button"
        :disabled="!chapterToolbar.hasContent"
        @click="sendAction('copy')"
      >
        <el-icon><CopyDocument /></el-icon>
        <span class="btn-label">全章复制</span>
      </el-button>
    </el-tooltip>
    <el-tooltip
      content="打开 AI 纠错"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button"
        :disabled="!chapterToolbar.hasContent || !auth.isLoggedIn"
        @click="sendAction('correction')"
      >
        <el-icon><EditPen /></el-icon>
        <span class="btn-label">纠错</span>
      </el-button>
    </el-tooltip>
    <el-tooltip
      content="搜索当前作品"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button"
        @click="sendAction('search')"
      >
        <el-icon><Search /></el-icon>
        <span class="btn-label">搜索</span>
      </el-button>
    </el-tooltip>

    <div class="toolbar-spacer" />

    <el-tooltip
      content="进入全屏编辑"
      placement="bottom"
    >
      <el-button
        class="chapter-tool-button chapter-tool-button--edit"
        type="success"
        @click="sendAction('edit')"
      >
        <el-icon><Edit /></el-icon>
        <span class="btn-label">编辑</span>
      </el-button>
    </el-tooltip>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive } from 'vue';
import {
  CopyDocument,
  DataAnalysis,
  DocumentChecked,
  Edit,
  EditPen,
  MagicStick,
  RefreshLeft,
  Search,
} from '@element-plus/icons-vue';
import { useEventBus } from '../../composables/useEventBus';
import { useAuthStore } from '../../stores/auth';

const { on, off, emit } = useEventBus();
const auth = useAuthStore();

// 由父级 v-else-if 控制显隐；这里仅维护按钮状态
const chapterToolbar = reactive({
  hasContent: false,
  dirty: false,
  title: '',
});

function sendAction(action) {
  emit('lingshu:chapter-toolbar-action', { action });
}

function onChapterToolbarState(payload) {
  const detail = payload || {};
  chapterToolbar.hasContent = Boolean(detail.hasContent);
  chapterToolbar.dirty = Boolean(detail.dirty);
  chapterToolbar.title = String(detail.title || '');
}

onMounted(() => on('lingshu:chapter-toolbar-state', onChapterToolbarState));
onUnmounted(() => off('lingshu:chapter-toolbar-state', onChapterToolbarState));
</script>

<style scoped>
.floating-chapter-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--floating-toolbar-height);
  padding: 0 12px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border-light);
  position: sticky;
  top: 0;
  z-index: 5;
  overflow-x: auto;
  scrollbar-width: thin;
  flex-shrink: 0;
}

.floating-chapter-toolbar::-webkit-scrollbar {
  height: 4px;
}

.toolbar-spacer {
  flex: 1;
  min-width: 8px;
}

.chapter-tool-button {
  height: 30px;
  min-width: 76px;
  padding: 0 12px;
  border-radius: 6px;
  font-weight: 700;
  flex: 0 0 auto;
}

.chapter-tool-button--primary {
  min-width: 92px;
}

.chapter-tool-button--edit {
  min-width: 84px;
  margin-left: auto;
}

/* 平板及以下：仅图标 */
@media (max-width: 1023px) {
  .chapter-tool-button,
  .chapter-tool-button--primary,
  .chapter-tool-button--edit {
    width: 30px;
    min-width: 30px;
    padding: 0;
  }

  .btn-label {
    display: none;
  }

  .chapter-tool-button--edit {
    margin-left: 0;
  }
}
</style>
