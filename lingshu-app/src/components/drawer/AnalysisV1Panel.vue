<!-- LEGACY：V1 一次性管线，仅握手兼容保留 -->
<template>
  <template v-if="analysisMode === 'v1'">
    <div
      v-if="analysisV1Runs.length"
      class="result-section"
    >
      <div class="result-label">
        V1 运行记录
      </div>
      <div
        v-for="run in analysisV1Runs"
        :key="run.id"
        class="run-item"
        :class="{ active: run.id === selectedV1RunId, 'run-failed': run.status === 'failed' }"
        @click="loadV1RunCards(run.id)"
      >
        <div class="run-item-main">
          <div class="run-title">
            #{{ run.id }} · <span :class="{ 'run-status-failed': run.status === 'failed' }">{{ runStatusText(run.status) }}</span>
          </div>
          <div class="run-meta">
            {{ run.card_count || 0 }} 卡 · {{ run.pipeline_version || 'v1' }} · {{ run.updated_at || run.created_at }}
          </div>
          <div
            v-if="run.status === 'failed' && run.error_text"
            class="run-error"
          >
            失败原因：{{ run.error_text }}
          </div>
        </div>
        <el-tag
          size="small"
          :type="run.status === 'failed' ? 'danger' : 'info'"
          effect="plain"
        >
          {{ run.status === 'failed' ? '失败' : 'V1' }}
        </el-tag>
      </div>
    </div>

    <div
      v-if="selectedV1Run && selectedV1Run.status === 'failed'"
      class="run-failure-panel"
    >
      <div class="run-failure-head">
        <span class="run-failure-title">分析失败</span>
        <el-tag
          size="small"
          type="danger"
          effect="plain"
        >
          运行 #{{ selectedV1Run.id }}
        </el-tag>
      </div>
      <div class="run-failure-body">
        {{ selectedV1Run.error_text || '失败原因未知，请稍后重试或查看服务器日志。' }}
      </div>
      <div class="run-failure-time">
        {{ selectedV1Run.updated_at || selectedV1Run.created_at }}
      </div>
    </div>

    <div
      v-if="selectedV1RunId && analysisV1Cards.length"
      class="result-section"
    >
      <div class="result-label">
        V1 草案卡 ({{ analysisV1Cards.length }} 张)
      </div>
      <div
        v-for="card in analysisV1Cards"
        :key="card.id"
        class="v3-card-item"
        @click="openV1CardDetail(card)"
      >
        <div class="v3-card-head">
          <span class="v3-card-title">{{ card.payload?.title || card.card_uid }}</span>
          <span class="v3-card-tags">
            <el-tag
              size="small"
              :type="cardStatusTagType(card.status)"
              effect="plain"
            >
              {{ card.status === 'draft' ? '草案' : card.status === 'applied' ? '已写回' : card.status === 'superseded' ? '已取代' : card.status }}
            </el-tag>
            <el-tag
              size="small"
              effect="plain"
            >
              {{ card.card_type === 'full_payload' ? '完整分析' : card.card_type === 'characters' ? '人物' : card.card_type === 'world' ? '世界观' : card.card_type }}
            </el-tag>
          </span>
        </div>
        <div class="v3-card-meta">
          评分 {{ confidenceText(card.ars_score) }}
        </div>
        <div
          v-if="card.payload?.summary"
          class="v3-card-summary"
        >
          {{ card.payload.summary }}
        </div>
      </div>
    </div>

    <div
      v-else-if="!loadingV1Runs && !loadingV1Cards && !analysisV1Runs.length"
      class="empty-hint"
    >
      暂无 V1 分析数据
    </div>
  </template>

  <!-- V1 卡片详情弹窗 -->
  <el-dialog
    v-model="v1CardDetailVisible"
    :title="v1CardDetailCard?.payload?.title || 'V1 卡片详情'"
    width="560px"
    destroy-on-close
    class="card-detail-dialog"
  >
    <template v-if="v1CardDetailCard">
      <div class="detail-section">
        <div class="detail-head">
          <span class="detail-label">基本信息</span>
          <span class="v3-card-tags">
            <el-tag
              size="small"
              :type="cardStatusTagType(v1CardDetailCard.status)"
              effect="plain"
            >
              {{ v1CardDetailCard.status === 'draft' ? '草案' : v1CardDetailCard.status === 'applied' ? '已写回' : v1CardDetailCard.status === 'superseded' ? '已取代' : v1CardDetailCard.status }}
            </el-tag>
            <el-tag
              size="small"
              effect="plain"
            >
              {{ v1CardDetailCard.card_type === 'full_payload' ? '完整分析' : v1CardDetailCard.card_type === 'characters' ? '人物' : v1CardDetailCard.card_type === 'world' ? '世界观' : v1CardDetailCard.card_type }}
            </el-tag>
          </span>
        </div>
        <div class="detail-grid">
          <div class="detail-field">
            <span class="detail-key">卡片 UID</span>
            <span class="detail-value mono">{{ v1CardDetailCard.card_uid }}</span>
          </div>
          <div class="detail-field">
            <span class="detail-key">评分</span>
            <span class="detail-value">{{ confidenceText(v1CardDetailCard.ars_score) }}</span>
          </div>
        </div>
      </div>

      <div
        v-if="v1CardDetailCard.payload"
        class="detail-section"
      >
        <div class="detail-head">
          <span class="detail-label">分析内容</span>
        </div>
        <div class="detail-summary">
          <pre class="v1-payload-preview">{{ JSON.stringify(v1CardDetailCard.payload, null, 2) }}</pre>
        </div>
      </div>
    </template>

    <template #footer>
      <div class="dialog-footer">
        <el-button
          size="small"
          @click="v1CardDetailVisible = false"
        >
          关闭
        </el-button>
        <el-button
          v-if="v1CardDetailCard?.status === 'applied'"
          size="small"
          type="success"
          disabled
        >
          已写回
        </el-button>
        <el-button
          v-else-if="v1CardDetailCard?.status === 'superseded'"
          size="small"
          type="warning"
          disabled
        >
          已取代
        </el-button>
        <el-button
          v-else
          size="small"
          type="primary"
          :loading="applyingV1Run"
          @click="applyV1Run(false)"
        >
          确认写回
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  analysisMode: {
    type: String,
    default: 'v3',
  },
  analysisV1Runs: {
    type: Array,
    default: () => [],
  },
  analysisV1Cards: {
    type: Array,
    default: () => [],
  },
  selectedV1RunId: {
    type: Number,
    default: null,
  },
  selectedV1Run: {
    type: Object,
    default: null,
  },
  loadingV1Runs: {
    type: Boolean,
    default: false,
  },
  loadingV1Cards: {
    type: Boolean,
    default: false,
  },
  v1CardDetailVisible: {
    type: Boolean,
    default: false,
  },
  v1CardDetailCard: {
    type: Object,
    default: null,
  },
  applyingV1Run: {
    type: Boolean,
    default: false,
  },
  // 共享工具 / V1 域操作（由主组件从 composable 解构后直传，保持单一数据源）
  runStatusText: {
    type: Function,
    required: true,
  },
  cardStatusTagType: {
    type: Function,
    required: true,
  },
  confidenceText: {
    type: Function,
    required: true,
  },
  loadV1RunCards: {
    type: Function,
    required: true,
  },
  openV1CardDetail: {
    type: Function,
    required: true,
  },
  applyV1Run: {
    type: Function,
    required: true,
  },
});

const emit = defineEmits(['update:v1CardDetailVisible']);

const v1CardDetailVisible = computed({
  get: () => props.v1CardDetailVisible,
  set: (value) => emit('update:v1CardDetailVisible', value),
});
</script>

<style scoped src="./analysis-tab-v1.css"></style>
