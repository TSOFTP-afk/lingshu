<template>
  <LoginPanel
    v-if="!token || !currentUser"
    :login-loading="loginLoading"
    :network-error="networkError"
    :network-error-msg="networkErrorMsg"
    @login="login"
    @close-network-error="networkError = false"
  />

  <el-container v-else class="admin-shell">
    <el-aside width="232px" class="sidebar">
      <div class="brand">
        <span class="brand-mark">镜</span>
        <div>
          <strong>灵镜管理台</strong>
          <small>全站数据与审计</small>
        </div>
      </div>
      <el-menu class="nav-menu" :default-active="activeSection" @select="selectSection">
        <el-menu-item v-for="item in sections" :key="item.key" :index="item.key">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <p class="eyebrow">{{ activeMeta.kicker }}</p>
          <h1>{{ activeMeta.label }}</h1>
        </div>
        <div class="top-actions">
          <el-tag type="success" effect="light">{{ currentUser.username }} ({{ currentUser.role }})</el-tag>
          <el-button @click="refreshActiveSection">刷新</el-button>
          <el-button type="danger" plain @click="() => logout()">退出</el-button>
        </div>
      </el-header>

      <el-main class="content">
        <DashboardSection
          v-if="activeSection === 'dashboard'"
          ref="dashboardRef"
          :token="token"
        />
        <ListSection
          v-else
          ref="listRef"
          :token="token"
          :active-section="activeSection"
          :active-meta="activeMeta"
          @open-detail="(row: Row) => drawerRef?.open(row)"
          @open-quota-edit="(row: Row) => drawerRef?.openQuotaEdit(row)"
        />
      </el-main>
    </el-container>
  </el-container>

  <DetailDrawer
    ref="drawerRef"
    :token="token"
    :active-section="activeSection"
    @refresh-required="refreshActiveSection"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import axios from 'axios';
import { ElMessage } from 'element-plus';
import {
  Coin,
  Connection,
  DataAnalysis,
  DataBoard,
  Monitor,
  Setting,
  User,
} from '@element-plus/icons-vue';
import { _obfuscate, _deobfuscate, isNetworkError, showNetworkError } from './composables/useApi';
import type { Row } from './composables/useApi';
import LoginPanel from './components/LoginPanel.vue';
import DashboardSection from './components/DashboardSection.vue';
import ListSection from './components/ListSection.vue';
import DetailDrawer from './components/DetailDrawer.vue';

type SectionKey = 'dashboard' | 'users' | 'devices' | 'sync' | 'quotas' | 'audits' | 'settings';
type SectionMeta = {
  key: SectionKey;
  label: string;
  kicker: string;
  icon: any;
  searchable?: boolean;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

const token = ref('');
// 异步解密 Token
_deobfuscate(sessionStorage.getItem('admin_auth_token') || '').then((decrypted) => {
  token.value = decrypted;
  if (decrypted) loadMe();
});
const currentUser = ref<Row | null>(null);
const loginLoading = ref(false);
const activeSection = ref<SectionKey>('dashboard');
const networkError = ref(false);
const networkErrorMsg = ref('');

const sections: SectionMeta[] = [
  { key: 'dashboard', label: '仪表盘', kicker: 'Dashboard', icon: DataBoard },
  { key: 'users', label: '用户管理', kicker: 'Users', icon: User, searchable: true },
  { key: 'devices', label: '设备管理', kicker: 'Devices', icon: Monitor, searchable: true },
  { key: 'sync', label: '同步监控', kicker: 'Sync', icon: Connection },
  { key: 'quotas', label: '配额与计费', kicker: 'Quotas', icon: Coin, searchable: true },
  { key: 'audits', label: '操作审计', kicker: 'Audit', icon: DataAnalysis },
  { key: 'settings', label: '系统设置', kicker: 'Settings', icon: Setting },
];

const activeMeta = computed<SectionMeta>(() => sections.find((item) => item.key === activeSection.value) || sections[0]);
const isAdmin = computed(() => !!currentUser.value && currentUser.value.role);

const dashboardRef = ref<InstanceType<typeof DashboardSection> | null>(null);
const listRef = ref<InstanceType<typeof ListSection> | null>(null);
const drawerRef = ref<InstanceType<typeof DetailDrawer> | null>(null);

async function login(username: string, password: string) {
  if (!username || !password) {
    ElMessage.warning('请输入用户名和密码');
    return;
  }
  loginLoading.value = true;
  try {
    const response = await axios.post(`${API_BASE}/admin/auth/login`, {
      username,
      password,
    });
    currentUser.value = response.data.admin;
    token.value = response.data.access_token;
    _obfuscate(token.value).then((encrypted) => {
      sessionStorage.setItem('admin_auth_token', encrypted);
    });
    await refreshActiveSection();
  } catch (error: any) {
    if (isNetworkError(error)) {
      networkError.value = true;
      networkErrorMsg.value = showNetworkError('登录');
    } else {
      const detail = error?.response?.data?.detail || '登录失败，请检查管理员账号密码';
      ElMessage.error(detail);
    }
  } finally {
    loginLoading.value = false;
  }
}

async function loadMe() {
  if (!token.value) return;
  try {
    const response = await axios.get(`${API_BASE}/admin/auth/me`, {
      headers: token.value ? { Authorization: `Bearer ${token.value}` } : {},
    });
    currentUser.value = response.data;
    if (isAdmin.value) {
      await refreshActiveSection();
    }
  } catch (error: any) {
    if (isNetworkError(error)) {
      showNetworkError('验证身份');
    }
    logout(false);
  }
}

function logout(showMessage = true) {
  token.value = '';
  currentUser.value = null;
  sessionStorage.removeItem('admin_auth_token');
  if (showMessage) ElMessage.success('已退出后台');
}

async function selectSection(key: string) {
  activeSection.value = key as SectionKey;
  await refreshActiveSection();
}

function refreshActiveSection() {
  if (activeSection.value === 'dashboard') {
    return dashboardRef.value?.refresh();
  } else {
    return listRef.value?.refresh();
  }
}


</script>

<style scoped>
.admin-shell {
  min-height: 100vh;
}

.sidebar {
  min-height: 100vh;
  background: #1a2e44;
  color: #f6fbff;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
}

.brand {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 22px 20px;
}

.brand-mark {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 8px;
  background: #3a7bbf;
  font-size: 24px;
  font-weight: 900;
}

.brand strong,
.brand small {
  display: block;
}

.brand small {
  margin-top: 4px;
  color: #9db8d0;
}

.nav-menu {
  border-right: 0;
  background: transparent;
}

.nav-menu :deep(.el-menu-item) {
  color: #c8deec;
}

.nav-menu :deep(.el-menu-item.is-active) {
  background: rgba(58, 123, 191, 0.16);
  color: #ffffff;
}

.topbar {
  height: auto;
  min-height: 86px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 28px;
  background: rgba(255, 255, 255, 0.86);
  border-bottom: 1px solid #c7d4e0;
}

.eyebrow {
  margin: 0 0 6px;
  color: #3a7bbf;
  font-weight: 800;
  letter-spacing: 0;
}

.topbar h1 {
  margin: 0;
  font-size: 28px;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.content {
  padding: 28px;
}

@media (max-width: 900px) {
  .admin-shell {
    display: block;
  }

  .sidebar {
    width: 100% !important;
    min-height: auto;
  }

  .nav-menu {
    display: flex;
    overflow-x: auto;
  }

  .content {
    padding: 16px;
  }
}
</style>
