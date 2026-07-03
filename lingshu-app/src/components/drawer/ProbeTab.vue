<template>
  <div class="probe-tab">
    <div
      v-if="!chapterId"
      class="probe-empty"
    >
      <el-empty
        description="请先在左侧选择章节"
        :image-size="80"
      />
    </div>
    <template v-else>
      <div class="probe-header">
        <div class="probe-header-info">
          <span class="probe-title">写作探针</span>
          <span class="probe-chapter">{{ chapterTitle || `章节 #${chapterId}` }}</span>
        </div>
        <div class="probe-header-actions">
          <el-button
            size="small"
            :loading="scanning"
            @click="triggerScan"
          >
            <el-icon><Refresh /></el-icon>
            <span>手动扫描</span>
          </el-button>
          <el-button
            size="small"
            type="primary"
            :loading="writebacking"
            :disabled="!hasPendingDrafts"
            @click="writebackAll"
          >
            一键写回全部
          </el-button>
        </div>
      </div>

      <div
        v-if="loading"
        class="probe-loading"
      >
        <el-skeleton :rows="3" />
      </div>

      <template v-else>
        <!-- 章节概要草稿 -->
        <div class="probe-section">
          <div class="probe-section-title">
            章节概要草稿
          </div>
          <div
            v-if="summaryDraft"
            class="probe-card probe-card-summary"
          >
            <div class="probe-card-header">
              <span class="probe-card-name">概要草稿</span>
              <el-tag
                :type="summaryDraft.status === 'applied' ? 'success' : 'warning'"
                size="small"
              >
                {{ summaryDraft.status === 'applied' ? '已采纳' : '待采纳' }}
              </el-tag>
            </div>
            <div class="probe-card-body">
              {{ summaryDraft.payload?.writeback_fields?.summary_text || '（草稿为空）' }}
            </div>
            <div class="probe-card-actions">
              <el-button
                size="small"
                type="primary"
                :disabled="summaryDraft.status === 'applied'"
                :loading="applyingSummary"
                @click="applySummary"
              >
                采纳
              </el-button>
            </div>
          </div>
          <el-empty
            v-else
            description="暂无概要草稿"
            :image-size="60"
          />
        </div>

        <!-- 人物草稿列表 -->
        <div class="probe-section">
          <div class="probe-section-title">
            人物草稿 <span class="probe-section-count">（{{ characterDrafts.length }}）</span>
          </div>
          <div
            v-if="characterDrafts.length"
            class="probe-character-list"
          >
            <div
              v-for="draft in characterDrafts"
              :key="draft.card_uid"
              class="probe-card probe-card-character"
            >
              <div class="probe-card-header">
                <span class="probe-card-name">{{ draft.payload?.writeback_fields?.name || '未命名' }}</span>
                <el-tag
                  :type="draft.status === 'applied' ? 'success' : 'warning'"
                  size="small"
                >
                  {{ draft.status === 'applied' ? '已采纳' : '待采纳' }}
                </el-tag>
              </div>
              <div class="probe-card-meta">
                <span>规则：{{ draft.payload?.source_rule || '-' }}</span>
                <span>置信度：{{ formatConfidence(draft.payload?.confidence) }}</span>
              </div>
              <div class="probe-card-body">
                {{ draft.payload?.writeback_fields?.profile_text || '（无描述）' }}
              </div>
            </div>
          </div>
          <el-empty
            v-else
            description="暂无人物草稿，写作时探针会自动扫描"
            :image-size="60"
          />
        </div>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { Refresh } from '@element-plus/icons-vue';
import { useBookStore } from '../../stores/book';
import { useEventBus } from '../../composables/useEventBus';
import api from '../../utils/api';

const bookStore = useBookStore();
const { on, off } = useEventBus();

const bookId = computed(() => bookStore.currentBookId);
const chapterId = computed(() => bookStore.activeChapterId);
const chapterTitle = computed(() => bookStore.activeTab?.title || '');

const drafts = ref([]);
const loading = ref(false);
const scanning = ref(false);
const writebacking = ref(false);
const applyingSummary = ref(false);

const summaryDraft = computed(() =>
  drafts.value.find(d => d.card_type === 'writing_probe_summary') || null,
);
const characterDrafts = computed(() =>
  drafts.value.filter(d => d.card_type === 'writing_probe_character'),
);
const hasPendingDrafts = computed(() =>
  drafts.value.some(d => d.status !== 'applied'),
);

watch([bookId, chapterId], () => {
  loadDrafts();
});

onMounted(() => {
  loadDrafts();
  on('lingshu:probe-scan-completed', onScanCompleted);
});

onUnmounted(() => {
  off('lingshu:probe-scan-completed', onScanCompleted);
});

function onScanCompleted(payload) {
  // 仅当事件携带当前章节时刷新
  if (!payload || Number(payload.chapter_id) === Number(chapterId.value)) {
    loadDrafts();
  }
}

async function loadDrafts() {
  if (!bookId.value || !chapterId.value) {
    drafts.value = [];
    return;
  }
  loading.value = true;
  try {
    const { data } = await api.get(
      `/workspace/books/${bookId.value}/chapters/${chapterId.value}/writing-probe/drafts`,
    );
    drafts.value = data.items || [];
  } catch (e) {
    drafts.value = [];
    // 探针未启用或登录态异常时静默处理，避免噪音
    if (e.response?.status >= 500) {
      ElMessage.error('草稿加载失败');
    }
  } finally {
    loading.value = false;
  }
}

async function triggerScan() {
  if (!bookId.value || !chapterId.value) return;
  scanning.value = true;
  try {
    const { data } = await api.post(
      `/workspace/books/${bookId.value}/chapters/${chapterId.value}/writing-probe`,
    );
    const charCount = data?.character_drafts?.length || 0;
    const hasSummary = !!data?.summary_draft;
    ElMessage.success(`扫描完成：新人物 ${charCount} 条，概要 ${hasSummary ? 1 : 0} 条`);
    await loadDrafts();
  } catch (e) {
    if (e.response?.status === 403) {
      ElMessage.warning('请在 AI 设置中启用写作探针');
    } else {
      ElMessage.error(e.response?.data?.detail || e.message || '扫描失败');
    }
  } finally {
    scanning.value = false;
  }
}

async function applySummary() {
  if (!summaryDraft.value) return;
  applyingSummary.value = true;
  try {
    const text = summaryDraft.value.payload?.writeback_fields?.summary_text || '';
    await api.post(`/workspace/chapters/${chapterId.value}/apply-summary`, {
      summary_text: text,
    });
    ElMessage.success('概要已写回');
    await loadDrafts();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '写回失败');
  } finally {
    applyingSummary.value = false;
  }
}

async function writebackAll() {
  if (!bookId.value || !chapterId.value) return;
  writebacking.value = true;
  try {
    const { data } = await api.post(
      `/workspace/books/${bookId.value}/chapters/${chapterId.value}/writing-probe/writeback-all`,
    );
    ElMessage.success(`写回完成：成功 ${data.success}/${data.total}`);
    await loadDrafts();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '写回失败');
  } finally {
    writebacking.value = false;
  }
}

function formatConfidence(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '-';
  return num.toFixed(2);
}
</script>

<style scoped>
.probe-tab {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px;
}
.probe-empty {
  padding: 24px 0;
}
.probe-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.probe-header-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.probe-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}
.probe-chapter {
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.probe-header-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.probe-loading {
  padding: 12px;
}
.probe-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.probe-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  padding: 0 4px;
}
.probe-section-count {
  color: var(--text-muted);
  font-weight: normal;
}
.probe-character-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.probe-card {
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-primary);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.probe-card-summary {
  background: linear-gradient(180deg, var(--bg-secondary), var(--bg-primary));
}
.probe-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.probe-card-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.probe-card-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}
.probe-card-body {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}
.probe-card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
</style>
