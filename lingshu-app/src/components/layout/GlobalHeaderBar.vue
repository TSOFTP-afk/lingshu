<template>
  <header
    class="global-header"
    role="banner"
    aria-label="全局头部"
  >
    <el-button
      class="hamburger"
      type="button"
      aria-label="打开侧边导航抽屉"
      @click="$emit('open-drawer')"
    >
      <el-icon><Menu /></el-icon>
    </el-button>

    <div class="brand-lockup">
      <span class="brand-mark">灵</span>
      <span class="brand-copy">
        <strong>灵枢</strong>
      </span>
    </div>

    <nav
      v-if="breadcrumbs.length"
      aria-label="面包屑导航"
    >
      <el-breadcrumb
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
    </nav>

    <div class="header-spacer" />

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
        :aria-label="`云端同步状态：${syncTooltip}`"
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

    <!-- 全局搜索 -->
    <el-tooltip
      content="搜索当前作品"
      placement="bottom"
    >
      <el-button
        class="tool-icon"
        :icon="Search"
        aria-label="搜索当前作品"
        @click="openSearch"
      />
    </el-tooltip>

    <!-- AI 对话 -->
    <el-tooltip
      :content="auth.isLoggedIn ? 'AI 对话' : '登录后使用 AI 对话'"
      placement="bottom"
    >
      <el-button
        class="tool-icon"
        :icon="ChatDotRound"
        :disabled="!auth.isLoggedIn"
        :aria-label="auth.isLoggedIn ? '打开 AI 对话' : '登录后使用 AI 对话'"
        @click="$emit('chat')"
      />
    </el-tooltip>
  </header>
</template>

<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import {
  ChatDotRound,
  CircleCheck,
  Menu,
  Search,
  Warning,
} from '@element-plus/icons-vue';
import { useEventBus } from '../../composables/useEventBus';
import { useAuthStore } from '../../stores/auth';
import { useCloudStore } from '../../stores/cloud';

defineEmits(['chat', 'open-drawer']);

const route = useRoute();
const { emit } = useEventBus();
const auth = useAuthStore();
const cloudStore = useCloudStore();

const breadcrumbs = computed(() => {
  const items = [];
  if (route.path.startsWith('/workspace')) {
    items.push({ path: '/workspace', label: '工作台' });
  }
  if (route.path.startsWith('/community')) {
    items.push({ path: '/community', label: '卡片社区' });
  }
  if (route.path.startsWith('/settings')) {
    items.push({ path: '/settings', label: '设置' });
  }
  if (route.params.bookId) {
    items.push({
      path: `/workspace/books/${route.params.bookId}`,
      label: `书籍 #${route.params.bookId}`,
    });
  }
  return items;
});

function openSearch() {
  emit('lingshu:open-search');
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

.hamburger {
  display: none;
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: 6px;
  -webkit-app-region: no-drag;
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  -webkit-app-region: no-drag;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: linear-gradient(135deg, #13b5a8, #4169e1);
  color: #fff;
  font-size: 14px;
  font-weight: 800;
  box-shadow: 0 4px 12px rgba(15, 143, 134, 0.18);
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
  -webkit-app-region: no-drag;
}

.header-spacer {
  flex: 1;
  min-width: 0;
}

.tool-icon {
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: 6px;
  -webkit-app-region: no-drag;
}

.sync-status-btn {
  color: var(--color-primary);
}

.sync-status-btn--error {
  color: var(--color-danger);
  border-color: color-mix(in srgb, var(--color-danger) 30%, var(--border-color));
}

/* 平板及以下：隐藏品牌文案 */
@media (max-width: 1023px) {
  .brand-copy {
    display: none;
  }
}

/* 窄屏：显示汉堡按钮 */
@media (max-width: 767px) {
  .hamburger {
    display: inline-flex;
  }

  .header-breadcrumb {
    display: none;
  }
}
</style>
