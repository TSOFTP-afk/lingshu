<template>
  <header class="global-header">
    <div class="header-left">
      <div class="brand-lockup">
        <span class="brand-mark">灵</span>
        <span class="brand-copy">
          <strong>灵枢</strong>
        </span>
        <span class="desktop-pill">桌面版</span>
      </div>
      <el-dropdown
        v-if="auth.isLoggedIn"
        trigger="click"
        @command="handleAccountCommand"
      >
        <button
          class="account-chip"
          type="button"
        >
          <span class="account-avatar">{{ accountInitial }}</span>
          <span class="account-name">{{ accountName }}</span>
          <span class="account-dot online" />
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="settings">
              账号设置
            </el-dropdown-item>
            <el-dropdown-item
              divided
              command="logout"
            >
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <button
        v-else
        class="account-chip"
        type="button"
        @click="openLogin"
      >
        <span class="account-avatar">灵</span>
        <span class="account-name">未登录</span>
        <span class="account-dot" />
      </button>
      <el-breadcrumb
        v-if="breadcrumbs.length"
        separator="/"
        class="header-breadcrumb"
      >
        <el-breadcrumb-item
          v-for="item in breadcrumbs"
          :key="item.path"
          :to="item.path"
        >
          {{ item.label }}
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <div class="header-center">
      <div
        v-if="showChapterToolbar"
        class="header-chapter-toolbar"
      >
        <el-tooltip
          content="润色选中文本"
          placement="bottom"
        >
          <el-button
            class="chapter-tool-button"
            :disabled="!chapterToolbar.hasContent || !auth.isLoggedIn"
            @click="sendChapterAction('polish')"
          >
            <el-icon><MagicStick /></el-icon>
            <span>润色</span>
          </el-button>
        </el-tooltip>
        <el-tooltip
          content="检测当前章节 AI 生成概率"
          placement="bottom"
        >
          <el-button
            class="chapter-tool-button"
            :disabled="!chapterToolbar.hasContent || !auth.isLoggedIn"
            @click="sendChapterAction('detect-ai')"
          >
            <el-icon><DataAnalysis /></el-icon>
            <span>AI率检测</span>
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
            @click="sendChapterAction('save')"
          >
            <el-icon><DocumentChecked /></el-icon>
            <span>保存</span>
          </el-button>
        </el-tooltip>
        <el-tooltip
          content="删除所有未保存变动，恢复到最后一次保存"
          placement="bottom"
        >
          <el-button
            class="chapter-tool-button"
            :disabled="!chapterToolbar.dirty"
            @click="sendChapterAction('revert')"
          >
            <el-icon><RefreshLeft /></el-icon>
            <span>回退</span>
          </el-button>
        </el-tooltip>
        <el-tooltip
          content="复制整章正文"
          placement="bottom"
        >
          <el-button
            class="chapter-tool-button"
            :disabled="!chapterToolbar.hasContent"
            @click="sendChapterAction('copy')"
          >
            <el-icon><CopyDocument /></el-icon>
            <span>全章复制</span>
          </el-button>
        </el-tooltip>
        <el-tooltip
          content="打开 AI 纠错"
          placement="bottom"
        >
          <el-button
            class="chapter-tool-button"
            :disabled="!chapterToolbar.hasContent || !auth.isLoggedIn"
            @click="sendChapterAction('correction')"
          >
            <el-icon><EditPen /></el-icon>
            <span>纠错</span>
          </el-button>
        </el-tooltip>
        <el-tooltip
          content="搜索当前作品"
          placement="bottom"
        >
          <el-button
            class="chapter-tool-button"
            @click="sendChapterAction('search')"
          >
            <el-icon><Search /></el-icon>
            <span>搜索</span>
          </el-button>
        </el-tooltip>
      </div>
    </div>

    <div class="header-right">
      <!-- 同步状态 -->
      <el-tooltip
        v-if="auth.isLoggedIn && cloudStore.syncStatus !== 'idle'"
        :content="syncTooltip"
        placement="bottom"
      >
        <el-button
          class="tool-icon sync-status-btn"
          :class="{ 'sync-status-btn--error': cloudStore.syncStatus === 'error' }"
          :loading="cloudStore.isSyncing"
          @click="handleSyncClick"
        >
          <el-icon v-if="cloudStore.syncStatus === 'synced'">
            <CircleCheck />
          </el-icon>
          <el-icon v-else-if="cloudStore.syncStatus === 'error'">
            <Warning />
          </el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip
        v-if="showWorkspaceActions"
        content="分析当前选中的书籍"
        placement="bottom"
      >
        <el-button
          class="book-analysis-entry"
          :disabled="!auth.isLoggedIn"
          @click="startBookAnalysis"
        >
          <el-icon><DataAnalysis /></el-icon>
          <span>全书分析</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        :content="auth.isLoggedIn ? 'AI 对话' : '登录后使用 AI 对话'"
        placement="bottom"
      >
        <el-button
          class="tool-icon"
          :icon="ChatDotRound"
          :disabled="!auth.isLoggedIn"
          @click="$emit('chat')"
        />
      </el-tooltip>
      <el-tooltip
        :content="auth.isLoggedIn ? '浏览社区共享卡片' : '登录后访问卡片社区'"
        placement="bottom"
      >
        <el-button
          class="community-entry"
          :disabled="!auth.isLoggedIn"
          @click="openCommunity"
        >
          <el-icon><Share /></el-icon>
          <span>卡片社区</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        :content="auth.isLoggedIn ? '跳转到 AI 配置' : '登录后配置 AI'"
        placement="bottom"
      >
        <el-button
          class="ai-settings-entry"
          :disabled="!auth.isLoggedIn"
          @click="openAiSettings"
        >
          <el-icon><Connection /></el-icon>
          <span>AI设置</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        content="设置中心"
        placement="bottom"
      >
        <el-button
          class="tool-icon settings-entry"
          :icon="Setting"
          @click="openSettings"
        />
      </el-tooltip>
    </div>
  </header>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import {
  ChatDotRound,
  CircleCheck,
  Connection,
  CopyDocument,
  DataAnalysis,
  DocumentChecked,
  EditPen,
  MagicStick,
  RefreshLeft,
  Search,
  Setting,
  Share,
  Warning,
} from '@element-plus/icons-vue';
import { useEventBus } from '../../composables/useEventBus';
import { useAuthStore } from '../../stores/auth';
import { useCloudStore } from '../../stores/cloud';

const route = useRoute();
const router = useRouter();
defineEmits(['chat']);
const { on, off, emit } = useEventBus();
const auth = useAuthStore();
const cloudStore = useCloudStore();
const chapterToolbar = ref({
  visible: false,
  hasContent: false,
  dirty: false,
  title: '',
});

const showChapterToolbar = computed(() => route.path.startsWith('/workspace') && chapterToolbar.value.visible);
const showWorkspaceActions = computed(() => route.path.startsWith('/workspace'));
const accountName = computed(() => auth.user?.display_name || auth.user?.username || '未登录');
const accountInitial = computed(() => String(accountName.value || '灵').trim().slice(0, 1).toUpperCase() || '灵');

const breadcrumbs = computed(() => {
  const items = [];
  if (route.path.startsWith('/workspace')) {
    items.push({ path: '/workspace', label: '工作台' });
  }
  if (route.params.bookId) {
    items.push({
      path: `/workspace/books/${route.params.bookId}`,
      label: `书籍 #${route.params.bookId}`,
    });
  }
  return items;
});

function openSettings() {
  router.push('/settings');
}

function openAiSettings() {
  router.push('/settings/ai');
}

function openCommunity() {
  router.push('/community');
}

function openLogin() {
  emit('lingshu:open-login');
}

function handleAccountCommand(command) {
  if (command === 'settings') {
    router.push('/settings');
    return;
  }
  if (command === 'logout') {
    auth.logout();
    ElMessage.success('已退出登录');
  }
}

const syncTooltip = computed(() => {
  const status = cloudStore.syncStatus;
  if (status === 'uploading') return '正在上传到云端...';
  if (status === 'syncing') return '正在同步...';
  if (status === 'synced') return '已同步到云端';
  if (status === 'error') return cloudStore.syncError || '同步失败，点击重试';
  return '';
});

async function handleSyncClick() {
  if (cloudStore.syncStatus === 'error') {
    try {
      await cloudStore.syncUploadedBooks();
      ElMessage.success('同步成功');
    } catch {
      ElMessage.error(cloudStore.syncError || '同步失败');
    }
  }
}

function sendChapterAction(action) {
  emit('lingshu:chapter-toolbar-action', { action });
}

function startBookAnalysis() {
  emit('lingshu:book-analysis-start');
}

function onChapterToolbarState(payload) {
  const detail = payload || {};
  chapterToolbar.value = {
    visible: Boolean(detail.visible),
    hasContent: Boolean(detail.hasContent),
    dirty: Boolean(detail.dirty),
    title: String(detail.title || ''),
  };
}

onMounted(() => on('lingshu:chapter-toolbar-state', onChapterToolbarState));
onUnmounted(() => off('lingshu:chapter-toolbar-state', onChapterToolbarState));
</script>

<style scoped>
.global-header {
  display: flex;
  align-items: center;
  height: var(--header-height);
  padding: 0 12px;
  background: linear-gradient(180deg, var(--bg-primary), var(--bg-secondary));
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
  gap: 10px;
  -webkit-app-region: drag;
  box-shadow: var(--shadow-sm);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  -webkit-app-region: no-drag;
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.account-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  max-width: 150px;
  padding: 0 8px 0 4px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  color: var(--text-regular);
  background: color-mix(in srgb, var(--bg-secondary) 82%, transparent);
  font: inherit;
  cursor: pointer;
  -webkit-app-region: no-drag;
}

.account-chip:hover {
  border-color: color-mix(in srgb, var(--color-primary) 34%, var(--border-color));
  color: var(--text-primary);
  background: color-mix(in srgb, var(--color-primary) 8%, var(--bg-secondary));
}

.account-avatar {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  color: #fff;
  background: linear-gradient(135deg, #13b5a8, #4169e1);
  font-size: 12px;
  font-weight: 800;
  flex: 0 0 auto;
}

.account-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
}

.account-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--text-placeholder);
  flex: 0 0 auto;
}

.account-dot.online {
  background: #15b881;
}

.settings-entry {
  color: var(--text-regular);
  background: var(--bg-secondary);
}

.ai-settings-entry,
.book-analysis-entry,
.community-entry {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  color: var(--text-regular);
  background: var(--bg-secondary);
  font-weight: 700;
}

.book-analysis-entry {
  color: var(--color-primary);
  border-color: color-mix(in srgb, var(--color-primary) 24%, var(--border-color));
  background: color-mix(in srgb, var(--color-primary) 8%, var(--bg-secondary));
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: linear-gradient(135deg, #13b5a8, #4169e1);
  color: #fff;
  font-size: 16px;
  font-weight: 800;
  box-shadow: 0 6px 14px rgba(15, 143, 134, 0.20);
}

.brand-copy {
  display: flex;
  align-items: center;
  line-height: 1;
}

.brand-copy strong {
  color: var(--text-primary);
  font-size: 14px;
}

.header-breadcrumb {
  font-size: var(--font-size-xs);
  min-width: 0;
  padding-left: 10px;
  border-left: 1px solid var(--border-color);
}

.header-center {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-width: 0;
  -webkit-app-region: no-drag;
}

.header-chapter-toolbar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
  transform: translateX(clamp(-92px, -5vw, -48px));
}

.header-chapter-toolbar::-webkit-scrollbar {
  display: none;
}

.chapter-tool-button {
  height: 34px;
  min-width: 82px;
  padding: 0 14px;
  border-radius: 7px;
  font-weight: 700;
  flex: 0 0 auto;
}

.chapter-tool-button--primary {
  min-width: 98px;
}

@media (max-width: 1280px) {
  .chapter-tool-button,
  .chapter-tool-button--primary {
    width: 34px;
    min-width: 34px;
    padding: 0;
  }

  .chapter-tool-button :deep(> span > span) {
    display: none;
  }
}

.header-right {
  display: flex;
  align-items: center;
  gap: 5px;
  -webkit-app-region: no-drag;
  white-space: nowrap;
}

.desktop-pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid rgba(15, 143, 134, 0.18);
  background: rgba(15, 143, 134, 0.08);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 600;
}

.tool-icon {
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: 6px;
}

.sync-status-btn {
  color: var(--color-primary);
}

.sync-status-btn--error {
  color: var(--color-danger);
  border-color: color-mix(in srgb, var(--color-danger) 30%, var(--border-color));
}

@media (max-width: 1100px) {
  .desktop-pill,
  .header-breadcrumb {
    display: none;
  }

  .header-chapter-toolbar {
    justify-content: flex-start;
    gap: 8px;
    transform: translateX(-28px);
  }

  .chapter-tool-button {
    min-width: 72px;
    padding: 0 10px;
  }

  .ai-settings-entry span,
  .book-analysis-entry span,
  .community-entry span {
    display: none;
  }

  .ai-settings-entry,
  .book-analysis-entry,
  .community-entry {
    width: 30px;
    padding: 0;
  }

  .account-chip {
    width: 30px;
    padding: 0;
    justify-content: center;
  }

  .account-name,
  .account-dot {
    display: none;
  }
}
</style>
