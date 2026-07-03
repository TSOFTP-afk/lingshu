<template>
  <el-dialog
    v-model="visible"
    title="AI 纠错"
    width="660px"
    @close="$emit('close')"
  >
    <div
      v-if="!bookId"
      class="empty-hint"
    >
      请先打开一个章节
    </div>
    <template v-else>
      <p class="corr-hint">
        输入需要纠错的文本，AI 将返回修改建议。
      </p>
      <el-input
        v-model="text"
        type="textarea"
        :rows="6"
        placeholder="粘贴需要纠错的文本..."
      />

      <div class="corr-actions">
        <el-button
          type="primary"
          :loading="correcting"
          :disabled="!text.trim() || !auth.isLoggedIn"
          @click="onCorrect"
        >
          开始纠错
        </el-button>
        <el-button
          v-if="correcting"
          type="danger"
          text
          @click="onCancel"
        >
          取消
        </el-button>
      </div>

      <div
        v-if="result"
        class="corr-result"
      >
        <div class="result-label">
          纠错结果
        </div>
        <div
          v-for="(r, idx) in findings"
          :key="idx"
          class="corr-item"
        >
          <span class="corr-original">{{ r.original || index }}</span>
          <span class="corr-arrow">→</span>
          <span class="corr-corrected">{{ r.correction || '' }}</span>
          <span
            v-if="r.reason"
            class="corr-reason"
          >{{ r.reason }}</span>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed } from 'vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import { useAuthStore } from '../../stores/auth';
import { buildWsUrl, sendWsAuth } from '../../utils/api';

const props = defineProps({
  modelValue: Boolean,
  seed: { type: Object, default: () => ({}) },
});
const emit = defineEmits(['update:modelValue', 'close']);

const visible = ref(props.modelValue);
watch(() => props.modelValue, v => { visible.value = v; });
watch(visible, v => emit('update:modelValue', v));
watch(() => props.seed?.token, () => {
  text.value = String(props.seed?.text || '');
  result.value = '';
  findings.value = [];
});

const bookStore = useBookStore();
const auth = useAuthStore();
const bookId = computed(() => bookStore.currentBookId);

const text = ref('');
const correcting = ref(false);
const result = ref('');
const findings = ref([]);
let ws = null;

function onCorrect() {
  if (!auth.requireAiAccess()) return;
  if (!text.value.trim()) return;
  correcting.value = true;
  result.value = '';
  findings.value = [];

  ws = new WebSocket(buildWsUrl('/ws/chat'));

  ws.onopen = () => {
    sendWsAuth(ws);
    ws.send(JSON.stringify({
      type: 'chat', task_id: Date.now().toString(),
      payload: { messages: [{ role: 'user', content: `请纠正以下中文文本中的错别字、语法错误和不规范表达，输出JSON格式：\n${text.value}` }] },
    }));
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'chunk') { result.value += msg.payload.text || ''; }
    else if (msg.type === 'result') {
      result.value = msg.payload.text || result.value;
      correcting.value = false;
      try {
        const parsed = JSON.parse(result.value);
        findings.value = Array.isArray(parsed) ? parsed : [parsed];
      } catch {
        findings.value = [{ original: text.value, correction: result.value, reason: '' }];
      }
      closeWs();
    } else if (msg.type === 'error') {
      ElMessage.error(msg.payload?.message || '纠错失败');
      correcting.value = false;
      closeWs();
    }
  };
  ws.onerror = () => { ElMessage.error('连接失败'); correcting.value = false; };
}

function onCancel() { if (ws) ws.send(JSON.stringify({ type: 'cancel' })); correcting.value = false; closeWs(); }
function closeWs() { if (ws) { ws.close(); ws = null; } }
</script>

<style scoped>
.empty-hint { color: var(--text-placeholder); font-size: 13px; text-align: center; padding: 24px; }
.corr-hint { font-size: 12px; color: var(--text-secondary); margin-bottom: 10px; }
.corr-actions { display: flex; gap: 8px; margin: 12px 0; }
.corr-result { margin-top: 12px; }
.result-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; }
.corr-item { padding: 8px; background: var(--bg-tertiary); border-radius: var(--radius-sm); margin-bottom: 6px; font-size: 12px; }
.corr-original { color: var(--color-danger); text-decoration: line-through; }
.corr-arrow { margin: 0 6px; color: var(--text-placeholder); }
.corr-corrected { color: var(--color-success); font-weight: 600; }
.corr-reason { display: block; color: var(--text-secondary); font-size: 11px; margin-top: 4px; }
</style>
