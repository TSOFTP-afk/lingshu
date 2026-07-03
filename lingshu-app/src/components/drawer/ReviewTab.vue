<template>
  <div class="review-tab">
    <div class="tab-header">
      <span class="tab-title">审查记录</span>
    </div>

    <div
      v-if="!bookId"
      class="empty-hint"
    >
      请先选择作品
    </div>

    <template v-else>
      <div class="review-actions">
        <el-button
          size="small"
          :loading="reviewing"
          :disabled="!chapterContent || !auth.isLoggedIn"
          @click="onReviewCurrent"
        >
          审查当前章节
        </el-button>
      </div>

      <el-progress
        v-if="progress"
        :percentage="progress.percent"
        style="margin: 8px 0"
      />

      <div
        v-if="findings.length"
        class="findings-list"
      >
        <div
          v-for="(f, idx) in findings"
          :key="idx"
          class="finding-item"
        >
          <el-tag
            :type="f.level === 'critical' ? 'danger' : f.level === 'warning' ? 'warning' : 'info'"
            size="small"
          >
            {{ f.category || '问题' }}
          </el-tag>
          <span class="finding-text">{{ f.description || f.message || '' }}</span>
          <span
            v-if="f.score"
            class="finding-score"
          >{{ f.score }}分</span>
        </div>
      </div>
      <el-empty
        v-else-if="!reviewing && findings.length === 0"
        description="暂无审查结果"
        :image-size="50"
      />
    </template>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import { useAuthStore } from '../../stores/auth';
import api, { buildWsUrl, sendWsAuth } from '../../utils/api';

const bookStore = useBookStore();
const auth = useAuthStore();
const bookId = computed(() => bookStore.currentBookId);

const reviewing = ref(false);
const progress = ref(null);
const findings = ref([]);
const chapterContent = ref('');

let ws = null;

async function onReviewCurrent() {
  if (!auth.requireAiAccess()) return;
  const chapterId = bookStore.activeChapterId;
  if (!chapterId) { ElMessage.warning('请先打开一个章节'); return; }

  // 获取章节内容
  try {
    const { data } = await api.get(`/workspace/chapters/${chapterId}`);
    chapterContent.value = data.content || '';
  } catch { ElMessage.error('获取章节内容失败'); return; }

  if (!chapterContent.value.trim()) { ElMessage.warning('章节内容为空'); return; }

  reviewing.value = true;
  findings.value = [];

  const sourcebookContext = await loadSourcebookContext();
  ws = new WebSocket(buildWsUrl('/ws/review'));

  ws.onopen = () => {
    sendWsAuth(ws);
    ws.send(JSON.stringify({
      type: 'review', task_id: Date.now().toString(),
      payload: {
        book_id: bookId.value,
        chapter_id: chapterId,
        content: chapterContent.value,
        sourcebook_context: sourcebookContext,
      },
    }));
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'progress') {
      progress.value = { percent: msg.payload.percent || 0 };
    } else if (msg.type === 'result') {
      findings.value = msg.payload.findings || [];
      reviewing.value = false;
      closeWs();
    } else if (msg.type === 'error') {
      ElMessage.error(msg.payload?.message || '审查失败');
      reviewing.value = false;
      closeWs();
    }
  };

  ws.onerror = () => { ElMessage.error('连接失败'); reviewing.value = false; };
}

function closeWs() { if (ws) { ws.close(); ws = null; } }

async function loadSourcebookContext() {
  if (!bookId.value) return '';
  try {
    const { data } = await api.get(`/workspace/books/${bookId.value}/references`);
    return data.context || '';
  } catch {
    return '';
  }
}
</script>

<style scoped>
.review-tab { padding: 4px 0; }
.tab-header { margin-bottom: 10px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.review-actions { margin-bottom: 8px; }
.empty-hint { color: var(--text-placeholder); font-size: 12px; padding: 16px 0; text-align: center; }
.finding-item { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border-light); font-size: 12px; }
.finding-item:last-child { border-bottom: none; }
.finding-text { flex: 1; color: var(--text-primary); line-height: 1.5; }
.finding-score { font-size: 11px; color: var(--text-placeholder); white-space: nowrap; }
</style>
