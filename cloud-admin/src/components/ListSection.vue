<template>
  <section class="panel">
    <div class="panel-toolbar">
      <div>
        <h2>{{ activeMeta.label }}</h2>
        <p>{{ total }} 条记录</p>
      </div>
      <div class="filters">
        <el-input
          v-if="activeMeta.searchable"
          v-model="query"
          clearable
          placeholder="搜索"
          :prefix-icon="Search"
          @keyup.enter="searchAndRefresh"
          @clear="searchAndRefresh"
        />
        <el-select
          v-if="activeSection === 'sync'"
          v-model="syncStateFilter"
          placeholder="同步状态"
          clearable
          style="width: 140px"
          @change="searchAndRefresh"
        >
          <el-option label="空闲" value="idle" />
          <el-option label="待推送" value="pending" />
          <el-option label="推送中" value="pushing" />
          <el-option label="拉取中" value="pulling" />
          <el-option label="冲突" value="conflict" />
          <el-option label="错误" value="error" />
        </el-select>
        <el-select
          v-if="activeSection === 'quotas'"
          v-model="tierFilter"
          placeholder="会员等级"
          clearable
          style="width: 130px"
          @change="searchAndRefresh"
        >
          <el-option label="免费版" value="free" />
          <el-option label="基础版" value="basic" />
          <el-option label="专业版" value="pro" />
        </el-select>
        <el-button type="primary" @click="searchAndRefresh">查询</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="displayRows" stripe border class="data-table" empty-text="暂无数据">
      <el-table-column
        v-for="column in displayColumns"
        :key="column.prop"
        :prop="column.prop"
        :label="column.label"
        :min-width="column.width || 130"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <template v-if="column.tag">
            <el-tag :type="column.tag[row[column.prop]] || 'info'" size="small">
              {{ row[column.prop] || '-' }}
            </el-tag>
          </template>
          <template v-else-if="column.bytes">
            {{ formatBytes(row[column.prop]) }}
          </template>
          <template v-else-if="column.seconds">
            {{ formatDuration(row[column.prop]) }}
          </template>
          <template v-else-if="column.number">
            {{ formatNumber(row[column.prop]) }}
          </template>
          <template v-else-if="column.quota">
            {{ formatBytes(row[column.prop]) }} / {{ formatBytes(row[column.quotaLimit as string] || 0) }}
          </template>
          <span v-else :class="{ mono: column.mono }">{{ formatValue(row[column.prop]) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="220">
        <template #default="{ row }">
          <el-button link type="primary" @click="$emit('open-detail', row)">详情</el-button>
          <template v-if="activeSection === 'users'">
            <el-button
              link
              :type="row.status === 'active' ? 'danger' : 'success'"
              @click="row.status === 'active' ? banUser(row) : unbanUser(row)"
            >
              {{ row.status === 'active' ? '封禁' : '解封' }}
            </el-button>
            <el-button link @click="$emit('open-quota-edit', row)">配额</el-button>
          </template>
          <template v-else-if="activeSection === 'devices'">
            <el-button link type="danger" @click="revokeDevice(row)">吊销</el-button>
          </template>
          <template v-else-if="activeSection === 'sync'">
            <el-button link type="warning" @click="resetSync(row)">重置</el-button>
            <el-button v-if="row.sync_state === 'error'" link type="primary" @click="retrySync(row)">重试</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > 0"
      v-model:current-page="currentPage"
      v-model:page-size="pageSize"
      :page-sizes="[10, 20, 50]"
      :total="total"
      layout="total, sizes, prev, pager, next, jumper"
      background
      class="table-pagination"
      @current-change="handlePageChange"
      @size-change="handlePageSizeChange"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Search } from '@element-plus/icons-vue';
import { useApi, type Row } from '../composables/useApi';
import { columnsBySection } from '../composables/useColumns';

type SectionKey = 'dashboard' | 'users' | 'devices' | 'sync' | 'quotas' | 'audits' | 'settings';
type SectionMeta = {
  key: SectionKey;
  label: string;
  kicker: string;
  icon: any;
  searchable?: boolean;
};

const props = defineProps<{
  token: string;
  activeSection: SectionKey;
  activeMeta: SectionMeta;
}>();

defineEmits<{
  'open-detail': [row: Row];
  'open-quota-edit': [row: Row];
}>();

const { apiGet, apiPost, apiDelete, formatNumber, formatValue, formatBytes, formatDuration } = useApi(ref(props.token));

const loading = ref(false);
const query = ref('');
const syncStateFilter = ref('');
const tierFilter = ref('');
const allItems = ref<Row[]>([]);
const total = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);
const loadedWindowPage = ref(1);

const displayColumns = computed(() => columnsBySection[props.activeSection] || []);

const displayRows = computed(() => {
  const offset = (currentPage.value - loadedWindowPage.value) * pageSize.value;
  return allItems.value.slice(offset, offset + pageSize.value);
});

async function refresh() {
  loading.value = true;
  try {
    const endpoints: Record<string, string> = {
      users: '/admin/users',
      devices: '/admin/devices',
      sync: '/admin/sync/books',
      quotas: '/admin/quotas',
      audits: '/admin/audit-logs',
      settings: '/admin/settings',
    };

    const params: Row = {
      page: currentPage.value,
      page_size: pageSize.value,
    };
    if (props.activeMeta.searchable && query.value.trim()) {
      params.q = query.value.trim();
    }
    if (props.activeSection === 'sync' && syncStateFilter.value) {
      params.state = syncStateFilter.value;
    }
    if (props.activeSection === 'quotas' && tierFilter.value) {
      params.tier = tierFilter.value;
    }

    const data = await apiGet(endpoints[props.activeSection], params);
    allItems.value = data.items || [];
    total.value = data.total || 0;
    loadedWindowPage.value = data.page || 1;
  } catch (error: any) {
    if (error?.response?.status === 401 || error?.response?.status === 403) {
      throw error;
    }
    ElMessage.error('加载数据失败');
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
  const windowStart = loadedWindowPage.value;
  const windowEnd = windowStart + Math.ceil(allItems.value.length / pageSize.value) - 1;
  if (page >= windowStart && page <= windowEnd) {
    currentPage.value = page;
  } else {
    currentPage.value = page;
    refresh();
  }
}

function handlePageSizeChange() {
  currentPage.value = 1;
  loadedWindowPage.value = 1;
  refresh();
}

async function confirmAction(message: string) {
  await ElMessageBox.confirm(message, '确认操作', {
    confirmButtonText: '确认',
    cancelButtonText: '取消',
    type: 'warning',
  });
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
  await confirmAction('确认吊销此设备？吊销后该设备需重新登录。');
  await apiDelete(`/admin/devices/${row.id}`);
  ElMessage.success('设备已吊销');
  await refresh();
}

async function resetSync(row: Row) {
  await confirmAction('确认重置此作品的同步状态？');
  await apiPost(`/admin/sync/books/${row.id}/reset`);
  ElMessage.success('同步状态已重置');
  await refresh();
}

async function retrySync(row: Row) {
  await apiPost(`/admin/sync/queue/${row.id}/retry`);
  ElMessage.success('已加入重试队列');
  await refresh();
}

watch(() => props.activeSection, () => {
  query.value = '';
  syncStateFilter.value = '';
  tierFilter.value = '';
  currentPage.value = 1;
  pageSize.value = 20;
  loadedWindowPage.value = 1;
});

defineExpose({ refresh, searchAndRefresh });
</script>

<style scoped>
.panel {
  display: grid;
  gap: 18px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #c7d4e0;
  border-radius: 8px;
  box-shadow: 0 16px 42px rgba(50, 80, 110, 0.12);
  padding: 22px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.panel h2 {
  margin-bottom: 4px;
  font-size: 20px;
}

.panel p {
  margin: 0;
  color: #6a8195;
}

.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.filters .el-input {
  width: 260px;
}

.data-table {
  width: 100%;
}

.table-pagination {
  margin-top: 18px;
  justify-content: flex-end;
}

@media (max-width: 900px) {
  .panel-toolbar {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
