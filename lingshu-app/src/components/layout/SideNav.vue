<template>
  <!-- 抽屉态遮罩（<768px） -->
  <div
    v-if="isDrawerMode"
    class="sidenav-overlay"
    :class="{ 'is-open': drawerOpen }"
    aria-hidden="true"
    @click="closeDrawer"
  />
  <aside
    class="sidenav"
    :class="{
      'sidenav--collapsed': isCollapsedMode,
      'sidenav--drawer': isDrawerMode,
      'is-open': drawerOpen,
    }"
    aria-label="侧边导航"
  >
    <!-- 顶部账号区 -->
    <div class="sidenav-account">
      <el-dropdown
        v-if="auth.isLoggedIn"
        ref="accountDropdownRef"
        trigger="click"
        @command="handleAccountCommand"
        @visible-change="onAccountDropdownVisibleChange"
      >
        <button
          class="account-chip"
          type="button"
          aria-haspopup="true"
          :aria-expanded="accountDropdownVisible ? 'true' : 'false'"
          :aria-label="`账号菜单：${accountName}`"
        >
          <span class="account-avatar">{{ accountInitial }}</span>
          <span
            v-if="!isCollapsedMode"
            class="account-name"
          >{{ accountName }}</span>
          <span
            v-if="!isCollapsedMode"
            class="account-dot online"
          />
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
        aria-label="点击登录灵枢账号"
        @click="openLogin"
      >
        <span class="account-avatar">灵</span>
        <span
          v-if="!isCollapsedMode"
          class="account-name"
        >未登录</span>
      </button>
    </div>

    <!-- 中部导航项 -->
    <nav
      class="sidenav-nav"
      aria-label="主导航"
    >
      <el-tooltip
        v-for="item in navItems"
        :key="item.key"
        :content="item.label"
        placement="right"
        :disabled="!isCollapsedMode"
      >
        <button
          class="nav-item"
          :class="{
            active: isActive(item),
            disabled: item.disabled,
          }"
          type="button"
          :disabled="item.disabled"
          :aria-current="isActive(item) ? 'page' : undefined"
          :aria-label="item.label"
          @click="onNavClick(item)"
        >
          <el-icon class="nav-icon">
            <component :is="item.icon" />
          </el-icon>
          <span
            v-if="!isCollapsedMode"
            class="nav-label"
          >{{ item.label }}</span>
        </button>
      </el-tooltip>
    </nav>

    <!-- 底部主题切换 -->
    <div
      class="sidenav-footer"
      role="group"
      aria-label="主题切换"
    >
      <el-tooltip
        v-for="theme in themeList"
        :key="theme.key"
        :content="theme.label"
        placement="right"
        :disabled="!isCollapsedMode"
      >
        <button
          class="theme-button"
          :class="{ active: theme.current === theme.key }"
          type="button"
          :title="theme.label"
          :aria-label="`切换到${theme.label}主题`"
          :aria-pressed="theme.current === theme.key ? 'true' : 'false'"
          @click="setTheme(theme.key)"
        >
          <span
            class="theme-swatch"
            :style="{ background: theme.swatch }"
          />
          <span
            v-if="!isCollapsedMode"
            class="theme-label"
          >{{ theme.label }}</span>
        </button>
      </el-tooltip>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import {
  Connection,
  DataAnalysis,
  Document,
  Files,
  Setting,
  Share,
} from '@element-plus/icons-vue';
import { useEventBus } from '../../composables/useEventBus';
import { useAuthStore } from '../../stores/auth';
import { useThemeStore } from '../../stores/theme';

defineProps({
  drawerOpen: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['update:drawerOpen']);

const route = useRoute();
const router = useRouter();
const bus = useEventBus();
const busEmit = bus.emit;
const auth = useAuthStore();
const theme = useThemeStore();

// 视口断点状态
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1920);

// 账号下拉菜单可见性（用于同步 aria-expanded）
const accountDropdownVisible = ref(false);
const accountDropdownRef = ref(null);
function onAccountDropdownVisibleChange(visible) {
  accountDropdownVisible.value = visible;
}

function onResize() {
  viewportWidth.value = window.innerWidth;
}

onMounted(() => {
  window.addEventListener('resize', onResize);
});

onUnmounted(() => {
  window.removeEventListener('resize', onResize);
});

// 1024–1439px 折叠图标条；<768px 抽屉态
const isCollapsedMode = computed(() => viewportWidth.value >= 768 && viewportWidth.value < 1024);
const isDrawerMode = computed(() => viewportWidth.value < 768);

const accountName = computed(() => auth.user?.display_name || auth.user?.username || '未登录');
const accountInitial = computed(() => String(accountName.value || '灵').trim().slice(0, 1).toUpperCase() || '灵');

// 导航项配置
const navItems = computed(() => {
  const items = [
    { key: 'workspace', label: '工作台', icon: Document, to: '/workspace' },
    { key: 'community', label: '卡片社区', icon: Share, to: '/community' },
    {
      key: 'reference',
      label: '参考书',
      icon: Files,
      event: 'lingshu:reference',
    },
    {
      key: 'star-graph',
      label: '星图',
      icon: Connection,
      event: 'lingshu:star-graph',
    },
    {
      key: 'book-analysis',
      label: '全书分析',
      icon: DataAnalysis,
      event: 'lingshu:book-analysis-start',
      onlyWorkspace: true,
      disabled: !auth.isLoggedIn,
    },
    { key: 'settings', label: '设置', icon: Setting, to: '/settings' },
  ];
  return items.filter((item) => !item.onlyWorkspace || route.path.startsWith('/workspace'));
});

const themeList = computed(() => [
  { key: 'white', label: '白昼', swatch: 'linear-gradient(135deg, #fbfcfd, #d4eeea)', current: theme.current },
  { key: 'light-blue', label: '浅蓝', swatch: 'linear-gradient(135deg, #f0f5ff, #b3cfff)', current: theme.current },
  { key: 'night', label: '夜行', swatch: 'linear-gradient(135deg, #1e1e2e, #40407a)', current: theme.current },
  { key: 'sepia', label: '羊皮纸', swatch: 'linear-gradient(135deg, #f4ecd8, #d0b878)', current: theme.current },
]);

function isActive(item) {
  if (item.to) {
    if (item.key === 'workspace') return route.path.startsWith('/workspace');
    if (item.key === 'settings') return route.path.startsWith('/settings');
    if (item.key === 'community') return route.path.startsWith('/community');
  }
  return false;
}

function onNavClick(item) {
  // 抽屉态点击后自动关闭
  if (isDrawerMode.value) {
    closeDrawer();
  }
  if (item.disabled) return;
  if (item.event) {
    busEmit(item.event);
    return;
  }
  if (item.to) {
    router.push(item.to);
  }
}

function setTheme(key) {
  theme.apply(key);
}

function handleAccountCommand(command) {
  if (isDrawerMode.value) closeDrawer();
  if (command === 'settings') {
    router.push('/settings');
    return;
  }
  if (command === 'logout') {
    auth.logout();
    ElMessage.success('已退出登录');
  }
}

function openLogin() {
  if (isDrawerMode.value) closeDrawer();
  busEmit('lingshu:open-login');
}

function closeDrawer() {
  emit('update:drawerOpen', false);
}
</script>

<style scoped>
.sidenav {
  display: flex;
  flex-direction: column;
  width: var(--sidenav-width);
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  -webkit-app-region: drag;
  transition: width var(--transition-normal);
  overflow: hidden;
}

.sidenav--collapsed {
  width: var(--sidenav-collapsed-width);
}

/* 抽屉态：默认隐藏，is-open 时滑入 */
.sidenav--drawer {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 1000;
  transform: translateX(-100%);
  box-shadow: var(--shadow-lg);
  transition: transform var(--transition-normal);
}

.sidenav--drawer.is-open {
  transform: translateX(0);
}

.sidenav-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
  background: rgba(0, 0, 0, 0.4);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--transition-normal);
}

.sidenav-overlay.is-open {
  opacity: 1;
  pointer-events: auto;
}

.sidenav-account {
  padding: 12px 10px;
  border-bottom: 1px solid var(--border-light);
  -webkit-app-region: no-drag;
}

.account-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 36px;
  padding: 0 8px 0 4px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  color: var(--text-regular);
  background: color-mix(in srgb, var(--bg-primary) 82%, transparent);
  font: inherit;
  cursor: pointer;
}

.account-chip:hover {
  border-color: color-mix(in srgb, var(--color-primary) 34%, var(--border-color));
  color: var(--text-primary);
  background: color-mix(in srgb, var(--color-primary) 8%, var(--bg-primary));
}

.sidenav--collapsed .account-chip {
  justify-content: center;
  padding: 0;
}

.account-avatar {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
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
  font-size: 13px;
  font-weight: 700;
  flex: 1;
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

.sidenav-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 8px;
  overflow-y: auto;
  -webkit-app-region: no-drag;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 38px;
  padding: 0 10px;
  border: none;
  border-radius: 8px;
  color: var(--text-regular);
  background: transparent;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.nav-item:hover:not(.disabled) {
  background: var(--bg-hover);
  color: var(--color-primary);
}

.nav-item.active {
  background: var(--bg-active);
  color: var(--color-primary);
}

.nav-item.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.sidenav--collapsed .nav-item {
  justify-content: center;
  padding: 0;
}

.nav-icon {
  font-size: 18px;
  flex: 0 0 auto;
}

.nav-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidenav-footer {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 10px 8px;
  border-top: 1px solid var(--border-light);
  -webkit-app-region: no-drag;
}

.sidenav--collapsed .sidenav-footer {
  grid-template-columns: 1fr;
}

.theme-button {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 6px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.theme-button:hover {
  border-color: var(--color-primary);
  color: var(--text-primary);
}

.theme-button.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--bg-active);
}

.sidenav--collapsed .theme-button {
  justify-content: center;
  padding: 0;
}

.theme-swatch {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 4px;
  flex: 0 0 auto;
  border: 1px solid rgba(0, 0, 0, 0.08);
}

.theme-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 平板断点：折叠态下隐藏 footer 文字 */
@media (max-width: 1023px) {
  .sidenav-footer {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>
