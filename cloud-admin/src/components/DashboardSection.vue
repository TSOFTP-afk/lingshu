<template>
  <section v-loading="loading" class="dashboard">
    <!-- 用户统计卡片 -->
    <div class="stat-grid">
      <article
        v-for="card in userStatCards"
        :key="card.key"
        class="stat-card clickable"
        :class="{ expanded: card.expanded }"
        @click="card.expanded = !card.expanded"
      >
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

    <div class="stat-grid">
      <article
        v-for="card in cloudUsageCards"
        :key="card.key"
        class="stat-card clickable"
        :class="{ expanded: card.expanded }"
        @click="card.expanded = !card.expanded"
      >
        <div class="card-header">
          <span>{{ card.label }}</span>
          <strong>{{ formatStatCard(card) }}</strong>
          <el-icon class="expand-icon" :class="{ rotated: card.expanded }"><ArrowDown /></el-icon>
        </div>
        <div v-if="card.expanded" class="card-detail">
          <p class="card-desc">{{ card.description }}</p>
        </div>
      </article>
    </div>

    <!-- 图表区 -->
    <div class="dashboard-grid">
      <section class="panel chart-panel">
        <div class="panel-title">
          <h2>用户分布</h2>
        </div>
        <div class="chart-wrapper" v-loading="userStatsLoading">
          <v-chart v-if="pieChartOption" :option="pieChartOption" autoresize class="chart" />
          <p v-else class="chart-empty">暂无数据</p>
        </div>
      </section>
      <section class="panel chart-panel">
        <div class="panel-title">
          <h2>月度趋势</h2>
          <div class="chart-controls">
            <el-select
              v-if="trendGranularity === 'monthly'"
              v-model="selectedMonth"
              size="small"
              style="width: 120px"
            >
              <el-option v-for="m in availableMonths" :key="m.value" :label="m.label" :value="m.value" />
            </el-select>
            <el-select
              v-if="trendGranularity === 'yearly'"
              v-model="selectedYear"
              size="small"
              style="width: 110px"
            >
              <el-option v-for="y in availableYears" :key="y" :label="String(y)" :value="y" />
            </el-select>
            <el-radio-group v-model="trendGranularity" size="small">
              <el-radio-button value="monthly">按天</el-radio-button>
              <el-radio-button value="yearly">按年</el-radio-button>
            </el-radio-group>
          </div>
        </div>
        <div class="chart-wrapper" v-loading="userStatsLoading">
          <v-chart v-if="lineChartOption" :option="lineChartOption" autoresize class="chart chart-tall" />
          <p v-else class="chart-empty">暂无数据</p>
        </div>
      </section>
    </div>

    <!-- 概览数据 -->
    <div class="dashboard-grid">
      <section class="panel">
        <div class="panel-title">
          <h2>章节状态</h2>
        </div>
        <el-table :data="overview?.chapter_statuses || []" stripe>
          <el-table-column prop="status" label="状态" min-width="140" />
          <el-table-column prop="count" label="数量" min-width="100" />
        </el-table>
      </section>
      <section class="panel">
        <div class="panel-title">
          <h2>最近审计</h2>
        </div>
        <el-table :data="overview?.recent_audits || []" stripe>
          <el-table-column prop="admin_username" label="管理员" min-width="120" />
          <el-table-column prop="action" label="动作" min-width="100" />
          <el-table-column prop="object_type" label="对象" min-width="120" />
          <el-table-column prop="created_at" label="时间" min-width="170" />
        </el-table>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { ArrowDown } from '@element-plus/icons-vue';
import { useApi, type Row } from '../composables/useApi';

const props = defineProps<{ token: string }>();

const { apiGet, formatStatCard } = useApi(ref(props.token));

const loading = ref(false);
const overview = ref<Row | null>(null);
const userStats = ref<Row | null>(null);
const userStatsLoading = ref(false);
const trendGranularity = ref('monthly');
const selectedYear = ref(new Date().getFullYear());
const selectedMonth = ref(`${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`);

const userStatCards = reactive([
  { key: 'total', label: '总注册用户', value: 0, expanded: false, description: '系统中所有注册用户的总数。' },
  { key: 'new', label: '当月新增', value: 0, expanded: false, description: '本月新注册的用户数量。' },
  { key: 'dormant', label: '潜水用户', value: 0, expanded: false, description: '连续3个月未更新活动的活跃用户，可能已流失。' },
  { key: 'active', label: '当月活跃', value: 0, expanded: false, description: '本月有过活动更新的活跃用户数量。' },
]);

const cloudUsageCards = reactive([
  { key: 'book_fulltexts', label: '全本快照', value: 0, expanded: false, description: '已保存当前全本快照的用户作品数量。', format: '' },
  { key: 'book_fulltext_chars', label: '全本文字', value: 0, format: 'number', expanded: false, description: '当前全本快照的文字总量。' },
  { key: 'online_seconds', label: '在线时长', value: 0, format: 'duration', expanded: false, description: '按登录 token 估算的累计在线时长。' },
  { key: 'analysis_runs', label: '分析次数', value: 0, expanded: false, description: '经过云端 API 记录的分析触发次数。', format: '' },
  { key: 'ai_total_tokens', label: 'AI Token', value: 0, format: 'number', expanded: false, description: '经过云端 API 记录的 AI token 总用量。' },
  { key: 'total_input_chars', label: '总输入字数', value: 0, format: 'number', expanded: false, description: '分析与 AI 请求累计输入字数。' },
]);

function updateDashboardCards(data: Row) {
  const counts = data?.counts || {};
  for (const card of cloudUsageCards) {
    card.value = counts[card.key] || 0;
  }
}

function updateUserStatCards(data: Row) {
  userStatCards[0].value = data.total_users || 0;
  userStatCards[1].value = data.new_this_month || 0;
  userStatCards[2].value = data.dormant_users || 0;
  userStatCards[3].value = data.active_this_month || 0;
}

const pieChartOption = computed(() => {
  const s = userStats.value;
  if (!s) return null;
  const total = s.total_users || 1;
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '45%'],
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

const availableYears = computed(() => {
  const currentYear = new Date().getFullYear();
  const years: number[] = [];
  for (let y = currentYear; y >= 2026; y--) years.push(y);
  return years;
});

const availableMonths = computed(() => {
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMon = now.getMonth() + 1;
  const months: { label: string; value: string }[] = [];
  for (let y = 2026; y <= currentYear; y++) {
    const mStart = y === 2026 ? 6 : 1;
    const mEnd = y === currentYear ? currentMon : 12;
    for (let m = mStart; m <= mEnd; m++) {
      const value = `${y}-${String(m).padStart(2, '0')}`;
      months.push({ label: value, value });
    }
  }
  return months;
});

async function refresh() {
  loading.value = true;
  try {
    overview.value = await apiGet('/admin/overview');
    updateDashboardCards(overview.value || {});
    userStatsLoading.value = true;
    try {
      const stats = await apiGet('/admin/user-stats', { granularity: trendGranularity.value, month: selectedMonth.value });
      userStats.value = stats;
      updateUserStatCards(stats);
    } catch {
      // user-stats 加载失败不影响主流程
    } finally {
      userStatsLoading.value = false;
    }
  } catch {
    // handled by caller
  } finally {
    loading.value = false;
  }
}

watch(() => props.token, (newToken) => {
  (useApi as any).__token = newToken;
});

defineExpose({ refresh });
</script>

<style scoped>
.dashboard,
.panel {
  display: grid;
  gap: 18px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px;
}

.stat-card,
.panel {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #c7d4e0;
  border-radius: 8px;
  box-shadow: 0 16px 42px rgba(50, 80, 110, 0.12);
}

.stat-card {
  padding: 18px;
}

.stat-card span {
  display: block;
  color: #617a91;
  font-weight: 700;
}

.stat-card strong {
  display: block;
  margin-top: 10px;
  font-size: 30px;
}

.stat-card.clickable {
  cursor: pointer;
  transition: box-shadow 0.2s;
}

.stat-card.clickable:hover {
  box-shadow: 0 4px 16px rgba(50, 80, 110, 0.18);
}

.card-header {
  position: relative;
}

.expand-icon {
  position: absolute;
  right: 0;
  top: 4px;
  font-size: 16px;
  color: #94aec5;
  transition: transform 0.25s;
}

.expand-icon.rotated {
  transform: rotate(180deg);
}

.card-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #d8e5ef;
}

.card-desc {
  margin: 0;
  color: #607990;
  font-size: 13px;
  line-height: 1.5;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
}

.panel {
  padding: 22px;
}

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.panel h2 {
  margin-bottom: 4px;
  font-size: 20px;
}

.chart-panel {
  min-height: 360px;
}

.chart-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chart-wrapper {
  min-height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chart {
  width: 100%;
  height: 300px;
}

.chart.chart-tall {
  height: 420px;
}

.chart-empty {
  color: #94aec5;
  font-size: 14px;
}

.panel p {
  margin: 0;
  color: #6a8195;
}

@media (max-width: 900px) {
  .dashboard-grid {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
