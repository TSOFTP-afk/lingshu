<template>
  <!-- 第一步：密钥验证 -->
  <main v-if="authStep === 'key'" class="login-shell">
    <section class="login-panel">
      <p class="eyebrow">Admin</p>
      <h1>灵镜管理台</h1>
      <p class="login-copy">请先导入管理员密钥文件以验证身份。</p>

      <el-alert v-if="keyError" class="network-alert" type="error" show-icon :closable="true"
        :title="keyError" @close="keyError = ''" />

      <div v-if="storedKey" class="key-info">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="密钥ID">{{ storedKey.key_id }}</el-descriptions-item>
          <el-descriptions-item label="颁发给">{{ storedKey.issued_to }}</el-descriptions-item>
          <el-descriptions-item label="颁发时间">{{ storedKey.issued_at }}</el-descriptions-item>
          <el-descriptions-item label="服务器">{{ storedKey.server_host }}</el-descriptions-item>
        </el-descriptions>
        <el-button type="primary" size="large" :loading="keyVerifying" @click="verifyStoredKey"
          style="width:100%;margin-top:16px">
          使用此密钥登录
        </el-button>
        <el-button size="large" @click="clearStoredKey" style="width:100%;margin-top:8px">
          使用其他密钥
        </el-button>
      </div>

      <div v-else class="key-import">
        <el-button type="primary" size="large" :loading="keyVerifying" @click="importKeyFile"
          style="width:100%">
          选择密钥文件 (.lingshu-key)
        </el-button>
        <el-divider>或手动输入密钥</el-divider>
        <el-form label-position="top" @submit.prevent="applyManualKey">
          <el-form-item label="密钥JSON">
            <el-input v-model="manualKeyJson" type="textarea" :rows="5" placeholder='粘贴密钥文件内容，如 {"key_id":"ak_xxx","secret":"..."}' />
          </el-form-item>
          <el-button type="success" size="large" style="width:100%" @click="applyManualKey">
            应用密钥
          </el-button>
        </el-form>
      </div>
    </section>
  </main>

  <!-- 第二步：账号密码登录 -->
  <main v-else-if="authStep === 'login'" class="login-shell">
    <section class="login-panel">
      <p class="eyebrow">Admin</p>
      <h1>灵镜管理台</h1>
      <p class="login-copy">密钥验证通过，请输入管理员账号密码。</p>

      <el-descriptions :column="1" border size="small" style="margin-bottom:16px">
        <el-descriptions-item label="密钥">{{ activeKey?.key_id }}</el-descriptions-item>
        <el-descriptions-item label="用户">{{ activeKey?.issued_to }}</el-descriptions-item>
      </el-descriptions>

      <el-alert v-if="networkError" class="network-alert" type="error" show-icon :closable="true"
        title="无法连接远程服务器" :description="networkErrorMsg" @close="networkError = false" />

      <el-form class="login-form" :model="loginForm" label-position="top" @submit.prevent="login">
        <el-form-item label="用户名">
          <el-input v-model="loginForm.username" size="large" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="loginForm.password" size="large" type="password"
            autocomplete="current-password" show-password @keyup.enter="login" />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loginLoading" @click="login"
          style="width:100%">登录</el-button>
        <el-button size="large" @click="authStep = 'key'" style="width:100%;margin-top:8px">
          返回密钥验证
        </el-button>
      </el-form>
    </section>
  </main>

  <!-- 管理主界面 -->
  <el-container v-else-if="authStep === 'admin'" class="admin-shell">
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
          <el-tag type="warning" effect="plain" size="small">
            <el-icon><Key /></el-icon> {{ activeKey?.key_id }}
          </el-tag>
          <el-button @click="refresh">刷新</el-button>
          <el-button type="danger" plain @click="logout">退出</el-button>
        </div>
      </el-header>

      <el-main class="content">
        <!-- 仪表盘 -->
        <section v-if="activeSection === 'dashboard'" v-loading="loading" class="dashboard">
          <div class="stat-grid">
            <article v-for="card in dashboardCards" :key="card.key" class="stat-card clickable"
              :class="{ expanded: card.expanded }" @click="card.expanded = !card.expanded">
              <div class="card-header">
                <span>{{ card.label }}</span>
                <strong>{{ card.value.toLocaleString() }}</strong>
                <el-icon class="expand-icon" :class="{ rotated: card.expanded }"><ArrowDown /></el-icon>
              </div>
              <div v-if="card.expanded" class="card-detail">
                <p class="card-desc">{{ card.description }}</p>
              </div>
            </article>
          </div>

          <div class="dashboard-grid">
            <section class="panel chart-panel">
              <div class="panel-title"><h2>用户分布</h2></div>
              <div class="chart-wrapper" v-loading="userStatsLoading">
                <v-chart v-if="pieChartOption" :option="pieChartOption" autoresize class="chart" />
                <p v-else class="chart-empty">暂无数据</p>
              </div>
            </section>
            <section class="panel chart-panel">
              <div class="panel-title"><h2>月度趋势</h2></div>
              <div class="chart-wrapper" v-loading="userStatsLoading">
                <v-chart v-if="lineChartOption" :option="lineChartOption" autoresize class="chart chart-tall" />
                <p v-else class="chart-empty">暂无数据</p>
              </div>
            </section>
          </div>

          <div class="dashboard-grid">
            <section class="panel">
              <div class="panel-title"><h2>章节状态</h2></div>
              <el-table :data="overview?.chapter_statuses || []" stripe>
                <el-table-column prop="status" label="状态" min-width="140" />
                <el-table-column prop="count" label="数量" min-width="100" />
              </el-table>
            </section>
            <section class="panel">
              <div class="panel-title"><h2>最近审计</h2></div>
              <el-table :data="overview?.recent_audits || []" stripe>
                <el-table-column prop="admin_username" label="管理员" min-width="120" />
                <el-table-column prop="action" label="动作" min-width="100" />
                <el-table-column prop="object_type" label="对象" min-width="120" />
                <el-table-column prop="created_at" label="时间" min-width="170" />
              </el-table>
            </section>
          </div>
        </section>

        <!-- 通用列表页 -->
        <section v-else class="panel">
          <div class="panel-toolbar">
            <div>
              <h2>{{ activeMeta.label }}</h2>
              <p>{{ total }} 条记录</p>
            </div>
            <div class="filters">
              <el-input v-if="activeMeta.searchable" v-model="query" clearable placeholder="搜索"
                :prefix-icon="Search" @keyup.enter="searchAndRefresh" @clear="searchAndRefresh" />
              <el-button type="primary" @click="searchAndRefresh">查询</el-button>
            </div>
          </div>

          <el-table v-loading="loading" :data="displayRows" stripe border class="data-table" empty-text="暂无数据">
            <el-table-column v-for="column in displayColumns" :key="column.prop" :prop="column.prop"
              :label="column.label" :min-width="column.width || 130" show-overflow-tooltip>
              <template #default="{ row }">
                <template v-if="column.tag">
                  <el-tag :type="column.tag[row[column.prop]] || 'info'" size="small">
                    {{ row[column.prop] || '-' }}
                  </el-tag>
                </template>
                <template v-else-if="column.bytes">
                  {{ formatBytes(row[column.prop]) }}
                </template>
                <template v-else-if="column.quota">
                  {{ formatBytes(row[column.prop]) }} / {{ formatBytes(row[column.quotaLimit as string] || 0) }}
                </template>
                <span v-else :class="{ mono: column.mono }">{{ formatValue(row[column.prop]) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" fixed="right" width="220">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <template v-if="activeSection === 'users'">
                  <el-button link :type="row.status === 'active' ? 'danger' : 'success'"
                    @click="row.status === 'active' ? banUser(row) : unbanUser(row)">
                    {{ row.status === 'active' ? '封禁' : '解封' }}
                  </el-button>
                  <el-button link @click="openQuotaEdit(row)">配额</el-button>
                </template>
                <template v-else-if="activeSection === 'devices'">
                  <el-button link type="danger" @click="revokeDevice(row)">吊销</el-button>
                </template>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination v-if="total > 0" v-model:current-page="currentPage" v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]" :total="total" layout="total, sizes, prev, pager, next, jumper"
            background class="table-pagination" @current-change="handlePageChange"
            @size-change="handlePageSizeChange" />
        </section>
      </el-main>
    </el-container>
  </el-container>

  <!-- 详情抽屉 -->
  <el-drawer v-model="detailVisible" :title="drawerTitle" size="700px">
    <section v-if="activeSection === 'users' && selected" class="edit-block">
      <h3>快速编辑</h3>
      <el-form label-position="top">
        <el-form-item label="作者权限">
          <el-switch v-model="editForm.is_author" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="管理员权限">
          <el-switch v-model="editForm.is_admin" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="账号状态">
          <el-select v-model="editForm.status">
            <el-option label="active" value="active" />
            <el-option label="disabled" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="saving" @click="saveUserEdit">保存修改</el-button>
    </section>

    <section v-if="activeSection === 'quotas' && selected" class="edit-block">
      <h3>调整配额</h3>
      <el-form label-position="top">
        <el-form-item label="会员等级">
          <el-select v-model="editForm.tier">
            <el-option label="免费版" value="free" />
            <el-option label="基础版" value="basic" />
            <el-option label="专业版" value="pro" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="saving" @click="saveQuotaEdit">保存配额</el-button>
    </section>

    <section class="raw-block">
      <h3>完整字段</h3>
      <pre class="raw-json">{{ selectedJson }}</pre>
    </section>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import axios from 'axios';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  ArrowDown, Coin, Connection, DataAnalysis, DataBoard,
  Key, Monitor, Search, Setting, User,
} from '@element-plus/icons-vue';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { PieChart, LineChart } from 'echarts/charts';
import {
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent,
} from 'echarts/components';

use([CanvasRenderer, PieChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent]);

type Row = Record<string, any>;
type SectionKey = 'dashboard' | 'users' | 'devices' | 'sync' | 'quotas' | 'audits' | 'settings';
type AuthStep = 'key' | 'login' | 'admin';

// ---------- 全局状态 ----------
const authStep = ref<AuthStep>('key');
const activeKey = ref<Row | null>(null);
const storedKey = ref<Row | null>(null);
const keyError = ref('');
const keyVerifying = ref(false);

const lingjing = (window as any).lingjing;
const API_PATH_PREFIX = '/api';
const API_BASE = lingjing?.serverBaseUrl ? `${String(lingjing.serverBaseUrl).replace(/\/+$/, '')}/api` : '/api';
const token = ref(sessionStorage.getItem('admin_auth_token') || '');
const currentUser = ref<Row | null>(null);
const loginLoading = ref(false);
const loading = ref(false);
const saving = ref(false);
const activeSection = ref<SectionKey>('dashboard');
const query = ref('');
const overview = ref<Row | null>(null);
const allItems = ref<Row[]>([]);
const total = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);
const loadedWindowPage = ref(1);
const selected = ref<Row | null>(null);
const detailVisible = ref(false);
const editForm = reactive<Row>({});
const loginForm = reactive({ username: '', password: '' });

// 网络错误
const networkError = ref(false);
const networkErrorMsg = ref('');

// 图表
const userStats = ref<Row | null>(null);
const userStatsLoading = ref(false);

const sections = [
  { key: 'dashboard', label: '仪表盘', kicker: 'Dashboard', icon: DataBoard },
  { key: 'users', label: '用户管理', kicker: 'Users', icon: User, searchable: true },
  { key: 'devices', label: '设备管理', kicker: 'Devices', icon: Monitor, searchable: true },
  { key: 'sync', label: '同步监控', kicker: 'Sync', icon: Connection },
  { key: 'quotas', label: '配额与计费', kicker: 'Quotas', icon: Coin, searchable: true },
  { key: 'audits', label: '操作审计', kicker: 'Audit', icon: DataAnalysis },
  { key: 'settings', label: '系统设置', kicker: 'Settings', icon: Setting },
];

const activeMeta = computed(() => sections.find((s) => s.key === activeSection.value) || sections[0]);
const isAdmin = computed(() => !!currentUser.value && currentUser.value.role);
const drawerTitle = computed(() => selected.value ? `${activeMeta.value.label} #${selected.value.id || ''}` : '详情');
const selectedJson = computed(() => JSON.stringify(selected.value || {}, null, 2));

// ---------- 仪表盘卡片 ----------
const dashboardCards = reactive([
  { key: 'users', label: '用户', value: 0, expanded: false, description: '系统中所有注册用户的总数。' },
  { key: 'active_users', label: '活跃用户', value: 0, expanded: false, description: '活跃用户数量。' },
  { key: 'books', label: '作品', value: 0, expanded: false, description: '系统中所有作品的数量。' },
  { key: 'chapters', label: '章节', value: 0, expanded: false, description: '系统中所有章节的数量。' },
  { key: 'bookshelf_items', label: '书架条目', value: 0, expanded: false, description: '书架中的条目数量。' },
  { key: 'active_tokens', label: '有效 Token', value: 0, expanded: false, description: '当前有效的登录令牌数量。' },
  { key: 'trusted_devices', label: '可信设备', value: 0, expanded: false, description: '已信任的设备数量。' },
]);

function updateDashboardCards(data: Row) {
  const counts = data?.counts || {};
  for (const card of dashboardCards) {
    card.value = counts[card.key] || 0;
  }
}

// ---------- 图表 ----------
const pieChartOption = computed(() => {
  const s = userStats.value;
  if (!s) return null;
  const total = s.total_users || 1;
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie', radius: ['40%', '70%'], center: ['50%', '45%'],
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 16, fontWeight: 'bold' } },
      data: [
        { name: '潜水用户', value: s.dormant_users || 0, itemStyle: { color: '#f56c6c' } },
        { name: '当月活跃', value: s.active_this_month || 0, itemStyle: { color: '#67c23a' } },
        { name: '当月新增', value: s.new_this_month || 0, itemStyle: { color: '#409eff' } },
        { name: '其他注册用户', value: Math.max(0, total - (s.new_this_month || 0) - (s.dormant_users || 0) - (s.active_this_month || 0)), itemStyle: { color: '#c0c4cc' } },
      ],
    }],
  };
});

const lineChartOption = computed(() => {
  const trends = userStats.value?.trends;
  if (!trends) return null;
  const months = trends.new_users?.map((d: Row) => d.month) || [];
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['当月新增', '潜水用户', '当月活跃'], bottom: 0 },
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: months, axisLabel: { rotate: 45, fontSize: 11 } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '当月新增', type: 'line', data: trends.new_users?.map((d: Row) => d.count) || [], smooth: true, color: '#409eff' },
      { name: '潜水用户', type: 'line', data: trends.dormant_users?.map((d: Row) => d.count) || [], smooth: true, color: '#f56c6c' },
      { name: '当月活跃', type: 'line', data: trends.active_users?.map((d: Row) => d.count) || [], smooth: true, color: '#67c23a' },
    ],
  };
});

// ---------- 表格列定义 ----------
const columnsBySection: Record<string, Array<{ prop: string; label: string; width?: number; mono?: boolean; tag?: Record<string, string>; bytes?: boolean; quota?: string; quotaLimit?: string }>> = {
  users: [
    { prop: 'id', label: 'ID', width: 80 },
    { prop: 'username', label: '用户名', width: 130 },
    { prop: 'is_author', label: '作者', width: 90 },
    { prop: 'is_admin', label: '管理员', width: 100 },
    { prop: 'status', label: '状态', width: 110, tag: { active: 'success', disabled: 'danger' } },
    { prop: 'token_count', label: 'Token', width: 100 },
    { prop: 'device_count', label: '设备', width: 100 },
    { prop: 'created_at', label: '创建时间', width: 170 },
  ],
  devices: [
    { prop: 'id', label: 'ID', width: 80 },
    { prop: 'username', label: '用户', width: 130 },
    { prop: 'fingerprint', label: '指纹', width: 220, mono: true },
    { prop: 'device_info', label: '设备信息', width: 220 },
    { prop: 'ip_address', label: 'IP', width: 130 },
    { prop: 'trusted_until', label: '可信到', width: 170 },
  ],
  sync: [
    { prop: 'book_title', label: '作品名', width: 180 },
    { prop: 'username', label: '用户', width: 120 },
    { prop: 'sync_state', label: '同步状态', width: 110, tag: { idle: 'info', pending: '', pushing: 'warning', pulling: 'warning', conflict: 'danger', error: 'danger' } },
    { prop: 'last_synced_at', label: '最后同步', width: 170 },
  ],
  quotas: [
    { prop: 'username', label: '用户', width: 120 },
    { prop: 'tier', label: '会员等级', width: 110, tag: { free: 'info', basic: '', pro: 'success' } },
    { prop: 'sync_storage_used_bytes', label: '同步容量', width: 160, quota: 'sync_storage_used_bytes', quotaLimit: 'sync_storage_limit_bytes' },
    { prop: 'ai_calls_used', label: 'AI 调用', width: 110 },
    { prop: 'expires_at', label: '到期时间', width: 170 },
  ],
  audits: [
    { prop: 'id', label: 'ID', width: 80 },
    { prop: 'admin_username', label: '管理员', width: 130 },
    { prop: 'action', label: '动作', width: 110 },
    { prop: 'object_type', label: '对象类型', width: 140 },
    { prop: 'created_at', label: '时间', width: 170 },
  ],
  settings: [
    { prop: 'key', label: '键', width: 200, mono: true },
    { prop: 'value_json', label: '值', width: 300 },
    { prop: 'description', label: '说明', width: 200 },
  ],
};

const displayColumns = computed(() => columnsBySection[activeSection.value] || []);
const displayRows = computed(() => {
  if (activeSection.value === 'dashboard') return [];
  const offset = (currentPage.value - loadedWindowPage.value) * pageSize.value;
  return allItems.value.slice(offset, offset + pageSize.value);
});

// ============================================================
//  密钥文件管理
// ============================================================

const manualKeyJson = ref('');

async function loadStoredKey() {
  if (!lingjing) return;
  const hasKey = await lingjing.keyHasStored();
  if (hasKey) {
    const result = await lingjing.keyLoad();
    if (result.ok) {
      storedKey.value = result.keyData;
    }
  }
}

async function importKeyFile() {
  keyVerifying.value = true;
  keyError.value = '';
  try {
    if (lingjing) {
      // Electron模式
      const fileResult = await lingjing.keyOpenFileDialog();
      if (!fileResult.ok || fileResult.canceled) {
        keyVerifying.value = false;
        return;
      }
      const readResult = await lingjing.keyReadFile(fileResult.filePath);
      if (!readResult.ok) {
        keyError.value = readResult.error;
        return;
      }
      activeKey.value = readResult.keyData;
      const storeResult = await lingjing.keyStore(readResult.keyData);
      if (!storeResult.ok) {
        keyError.value = storeResult.error || '密钥安全存储失败';
        return;
      }
      storedKey.value = readResult.keyData;
    } else {
      // 浏览器模式：使用HTML5文件选择器
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.lingshu-key,.json';
      const file = await new Promise<File | null>((resolve) => {
        input.onchange = () => resolve(input.files?.[0] || null);
        input.click();
      });
      if (!file) {
        keyVerifying.value = false;
        return;
      }
      const text = await file.text();
      const keyData = JSON.parse(text);
      if (!keyData.key_id || !keyData.secret || !keyData.issued_to) {
        keyError.value = '密钥文件格式无效';
        return;
      }
      activeKey.value = keyData;
      storedKey.value = keyData;
    }
    // 进入密码登录步骤
    loginForm.username = activeKey.value!.issued_to || '';
    authStep.value = 'login';
  } catch (err: any) {
    keyError.value = err.message || '导入密钥文件失败';
  } finally {
    keyVerifying.value = false;
  }
}

async function applyManualKey() {
  keyError.value = '';
  try {
    const keyData = JSON.parse(manualKeyJson.value.trim());
    if (!keyData.key_id || !keyData.secret || !keyData.issued_to) {
      keyError.value = '密钥格式无效，需要 key_id、secret、issued_to 字段';
      return;
    }
    if (lingjing) {
      const storeResult = await lingjing.keyStore(keyData);
      if (!storeResult.ok) {
        keyError.value = storeResult.error || '密钥安全存储失败';
        return;
      }
      const safeKeyData = {
        key_id: keyData.key_id,
        issued_to: keyData.issued_to,
        cache_expires_at: Date.now() + 15 * 60 * 1000,
      };
      activeKey.value = safeKeyData;
      storedKey.value = safeKeyData;
    } else {
      activeKey.value = keyData;
      storedKey.value = keyData;
    }
    loginForm.username = keyData.issued_to || '';
    authStep.value = 'login';
  } catch (err: any) {
    keyError.value = 'JSON解析失败，请检查格式';
  }
}

async function verifyStoredKey() {
  if (!storedKey.value) return;
  keyVerifying.value = true;
  try {
    activeKey.value = storedKey.value;
    loginForm.username = storedKey.value.issued_to || '';
    authStep.value = 'login';
  } finally {
    keyVerifying.value = false;
  }
}

async function clearStoredKey() {
  if (lingjing) {
    await lingjing.keyRemove();
  }
  storedKey.value = null;
  activeKey.value = null;
}

// ============================================================
//  HMAC签名 + API请求
// ============================================================

async function computeHmac(message: string): Promise<string> {
  if (!activeKey.value) return '';
  if (lingjing) {
    const result = await lingjing.computeHmac(message);
    if (!result.ok) {
      keyError.value = result.error || '密钥签名失败';
      activeKey.value = null;
      throw new Error(keyError.value);
    }
    return result.signature;
  }
  if (!activeKey.value.secret) return '';
  // 浏览器模式：使用Web Crypto API
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', encoder.encode(activeKey.value.secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(message));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function authHeaders() {
  return token.value ? { Authorization: `Bearer ${token.value}` } : {};
}

function hmacMessage(ts: string, method: string, path: string) {
  return `${ts}\n${method.toUpperCase()}\n${path}`;
}

async function signedHeaders(method: string, path: string): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...authHeaders() };
  if (activeKey.value) {
    const ts = Date.now().toString();
    const sig = await computeHmac(hmacMessage(ts, method, path));
    headers['X-Client-KeyId'] = activeKey.value.key_id;
    headers['X-Client-Ts'] = ts;
    headers['X-Client-Sig'] = sig;
  }
  return headers;
}

async function apiGet(path: string, params: Row = {}) {
  const headers = await signedHeaders('GET', `${API_PATH_PREFIX}${path}`);
  const response = await axios.get(`${API_BASE}${path}`, { params, headers });
  return response.data;
}

async function apiPatch(path: string, payload: Row) {
  const headers = await signedHeaders('PATCH', `${API_PATH_PREFIX}${path}`);
  const response = await axios.patch(`${API_BASE}${path}`, payload, { headers });
  return response.data;
}

async function apiPost(path: string, payload: Row = {}) {
  const headers = await signedHeaders('POST', `${API_PATH_PREFIX}${path}`);
  const response = await axios.post(`${API_BASE}${path}`, payload, { headers });
  return response.data;
}

async function apiDelete(path: string) {
  const headers = await signedHeaders('DELETE', `${API_PATH_PREFIX}${path}`);
  const response = await axios.delete(`${API_BASE}${path}`, { headers });
  return response.data;
}

// ============================================================
//  登录
// ============================================================

async function login() {
  if (!loginForm.username.trim() || !loginForm.password) {
    ElMessage.warning('请输入用户名和密码');
    return;
  }
  loginLoading.value = true;
  networkError.value = false;
  try {
    // 计算HMAC签名
    const ts = Date.now().toString();
    const loginPath = '/admin/auth/login';
    const hmac = await computeHmac(hmacMessage(ts, 'POST', `${API_PATH_PREFIX}${loginPath}`));

    const response = await axios.post(`${API_BASE}${loginPath}`, {
      username: loginForm.username.trim(),
      password: loginForm.password,
      key_id: activeKey.value?.key_id || '',
      timestamp: ts,
      hmac_signature: hmac,
    });

    currentUser.value = response.data.admin;
    token.value = response.data.access_token;
    sessionStorage.setItem('admin_auth_token', token.value);
    authStep.value = 'admin';
    await refresh();
  } catch (error: any) {
    if (!error.response) {
      networkError.value = true;
      networkErrorMsg.value = '无法连接到远程服务器。请检查网络连接。';
      ElMessage.error(networkErrorMsg.value);
    } else {
      const detail = error?.response?.data?.detail || '登录失败';
      ElMessage.error(detail);
    }
  } finally {
    loginLoading.value = false;
  }
}

function logout() {
  token.value = '';
  currentUser.value = null;
  sessionStorage.removeItem('admin_auth_token');
  authStep.value = 'key';
  ElMessage.success('已退出后台');
}

// ============================================================
//  数据加载
// ============================================================

async function selectSection(key: string) {
  activeSection.value = key as SectionKey;
  query.value = '';
  currentPage.value = 1;
  loadedWindowPage.value = 1;
  await refresh();
}

async function refresh() {
  if (!token.value || !currentUser.value) return;
  loading.value = true;
  try {
    if (activeSection.value === 'dashboard') {
      overview.value = await apiGet('/admin/overview');
      updateDashboardCards(overview.value || {});
      userStatsLoading.value = true;
      try {
        userStats.value = await apiGet('/admin/user-stats');
      } catch { /* noop */ } finally {
        userStatsLoading.value = false;
      }
      return;
    }

    const endpoints: Record<string, string> = {
      users: '/admin/users',
      devices: '/admin/devices',
      sync: '/admin/sync/books',
      quotas: '/admin/quotas',
      audits: '/admin/audit-logs',
      settings: '/admin/settings',
    };

    const params: Row = { page: currentPage.value, page_size: pageSize.value };
    if (activeMeta.value.searchable && query.value.trim()) {
      params.q = query.value.trim();
    }

    const data = await apiGet(endpoints[activeSection.value], params);
    allItems.value = data.items || [];
    total.value = data.total || 0;
    loadedWindowPage.value = data.page || 1;
  } catch (error: any) {
    if (error?.response?.status === 401 || error?.response?.status === 403) {
      ElMessage.error('权限校验失败');
      logout();
    } else {
      ElMessage.error('加载数据失败');
    }
  } finally {
    loading.value = false;
  }
}

function searchAndRefresh() {
  currentPage.value = 1;
  loadedWindowPage.value = 1;
  refresh();
}

function handlePageChange(page: number) {
  currentPage.value = page;
  refresh();
}

function handlePageSizeChange() {
  currentPage.value = 1;
  loadedWindowPage.value = 1;
  refresh();
}

// ---------- 格式化工具 ----------
function formatValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function formatBytes(bytes: number | undefined | null) {
  if (!bytes && bytes !== 0) return '-';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

// ---------- 详情与编辑 ----------
async function openDetail(row: Row) {
  try {
    if (activeSection.value === 'users') {
      selected.value = await apiGet(`/admin/users/${row.id}`);
      prepareUserEditForm();
    } else {
      selected.value = { ...row };
    }
    detailVisible.value = true;
  } catch { ElMessage.error('读取详情失败'); }
}

function prepareUserEditForm() {
  Object.keys(editForm).forEach((k) => delete editForm[k]);
  if (!selected.value) return;
  Object.assign(editForm, {
    is_author: Number(selected.value.is_author || 0),
    is_admin: Number(selected.value.is_admin || 0),
    status: selected.value.status || 'active',
  });
}

function openQuotaEdit(row: Row) {
  selected.value = { ...row };
  prepareUserEditForm();
  detailVisible.value = true;
}

async function saveUserEdit() {
  if (!selected.value) return;
  saving.value = true;
  try {
    selected.value = (await apiPatch(`/admin/users/${selected.value.id}`, editForm)).item;
    prepareUserEditForm();
    await refresh();
    ElMessage.success('已保存');
  } catch { ElMessage.error('保存失败'); } finally { saving.value = false; }
}

async function saveQuotaEdit() {
  if (!selected.value) return;
  saving.value = true;
  try {
    await apiPatch(`/admin/users/${selected.value.user_id || selected.value.id}`, editForm);
    ElMessage.success('配额已保存');
    detailVisible.value = false;
    await refresh();
  } catch { ElMessage.error('保存失败'); } finally { saving.value = false; }
}

async function confirmAction(message: string) {
  await ElMessageBox.confirm(message, '确认操作', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' });
}

async function banUser(row: Row) {
  await confirmAction(`确认禁用用户 ${row.username}？`);
  await apiDelete(`/admin/users/${row.id}`);
  ElMessage.success('用户已禁用');
  await refresh();
}

async function unbanUser(row: Row) {
  await apiPost(`/admin/users/${row.id}/restore`);
  ElMessage.success('用户已恢复');
  await refresh();
}

async function revokeDevice(row: Row) {
  await confirmAction('确认吊销此设备？');
  await apiDelete(`/admin/devices/${row.id}`);
  ElMessage.success('设备已吊销');
  await refresh();
}

// ---------- 初始化 ----------
onMounted(loadStoredKey);
</script>

<style scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
  background: #0b1220;
}

.login-panel {
  width: min(480px, 100%);
  padding: 34px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #c7d4e0;
  border-radius: 8px;
  box-shadow: 0 22px 60px rgba(50, 80, 110, 0.18);
}

.eyebrow {
  margin: 0 0 6px;
  color: #3a7bbf;
  font-weight: 800;
}

h1, h2, h3, p { margin-top: 0; }

.login-panel h1 { margin-bottom: 8px; font-size: 30px; }

.login-copy { color: #607990; }

.network-alert { margin-top: 16px; }

.key-info { margin-top: 20px; }

.key-import { margin-top: 20px; }

.login-form { margin-top: 22px; }
.login-form .el-button { width: 100%; }

.admin-shell { min-height: 100vh; }

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

.brand strong, .brand small { display: block; }
.brand small { margin-top: 4px; color: #9db8d0; }

.nav-menu { border-right: 0; background: transparent; }
.nav-menu :deep(.el-menu-item) { color: #c8deec; }
.nav-menu :deep(.el-menu-item.is-active) { background: rgba(58, 123, 191, 0.16); color: #fff; }

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

.topbar h1 { margin: 0; font-size: 28px; }

.top-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

.content { padding: 28px; }

.dashboard, .panel { display: grid; gap: 18px; }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px;
}

.stat-card, .panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #c7d4e0;
  border-radius: 8px;
  box-shadow: 0 16px 42px rgba(50, 80, 110, 0.12);
}

.stat-card { padding: 18px; }
.stat-card span { display: block; color: #617a91; font-weight: 700; }
.stat-card strong { display: block; margin-top: 10px; font-size: 30px; }
.stat-card.clickable { cursor: pointer; transition: box-shadow 0.2s; }
.stat-card.clickable:hover { box-shadow: 0 4px 16px rgba(50, 80, 110, 0.18); }

.card-header { position: relative; }
.expand-icon { position: absolute; right: 0; top: 4px; font-size: 16px; color: #94aec5; transition: transform 0.25s; }
.expand-icon.rotated { transform: rotate(180deg); }
.card-detail { margin-top: 12px; padding-top: 12px; border-top: 1px solid #d8e5ef; }
.card-desc { margin: 0; color: #607990; font-size: 13px; line-height: 1.5; }

.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; }
.panel { padding: 22px; }
.panel-title, .panel-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.panel h2 { margin-bottom: 4px; font-size: 20px; }

.chart-panel { min-height: 360px; }
.chart-wrapper { min-height: 300px; display: flex; align-items: center; justify-content: center; }
.chart { width: 100%; height: 300px; }
.chart.chart-tall { height: 420px; }
.chart-empty { color: #94aec5; font-size: 14px; }

.panel p { margin: 0; color: #6a8195; }

.filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: flex-end; }
.filters .el-input { width: 260px; }

.data-table { width: 100%; }

.edit-block { padding-bottom: 24px; border-bottom: 1px solid #d8e5ef; }
.raw-block { padding-top: 22px; }
.raw-json {
  max-height: 420px;
  overflow: auto;
  padding: 14px;
  border-radius: 6px;
  background: #0d2234;
  color: #d8efff;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.table-pagination { margin-top: 18px; justify-content: flex-end; }

@media (max-width: 900px) {
  .admin-shell { display: block; }
  .sidebar { width: 100% !important; min-height: auto; }
  .nav-menu { display: flex; overflow-x: auto; }
  .topbar, .panel-toolbar, .dashboard-grid { display: grid; grid-template-columns: 1fr; }
  .content { padding: 16px; }
}
</style>
