<template>
  <el-dialog
    v-model="visible"
    title="AI 对话"
    width="min(780px, calc(100vw - 24px))"
    class="ai-chat-dialog"
    :close-on-click-modal="false"
    @open="onOpen"
    @close="$emit('close')"
  >
    <div class="chat-container">
      <div class="persona-bar">
        <div class="persona-field">
          <span class="persona-label">我扮演</span>
          <el-select
            v-model="selfCharacterId"
            size="small"
            filterable
            :disabled="sending || !bookId"
            @change="onPersonaChange"
          >
            <el-option
              label="我（作者本人）"
              :value="0"
            />
            <el-option
              v-for="ch in characters"
              :key="`self-${ch.id}`"
              :label="characterLabel(ch)"
              :value="Number(ch.id)"
            />
          </el-select>
        </div>
        <div class="persona-field">
          <span class="persona-label">AI 扮演</span>
          <el-select
            v-model="aiCharacterId"
            size="small"
            filterable
            :disabled="sending || !bookId"
            @change="onPersonaChange"
          >
            <el-option
              label="写作助手"
              :value="0"
            />
            <el-option
              v-for="ch in characters"
              :key="`ai-${ch.id}`"
              :label="characterLabel(ch)"
              :value="Number(ch.id)"
            />
          </el-select>
        </div>
        <div class="persona-actions">
          <el-button
            size="small"
            :icon="Refresh"
            :disabled="sending || !bookId"
            @click="loadCharacters"
          >
            刷新人物
          </el-button>
          <el-button
            size="small"
            :icon="Delete"
            :disabled="sending || !messages.length"
            @click="clearHistory"
          >
            清空历史
          </el-button>
        </div>
      </div>

      <div class="chat-status">
        <span>{{ contextLabel }}</span>
        <span v-if="statusText">{{ statusText }}</span>
      </div>

      <div
        ref="msgContainer"
        class="chat-messages"
      >
        <el-empty
          v-if="!messages.length && !streaming"
          description="暂无对话"
          :image-size="52"
        />
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="chat-msg"
          :class="`msg-${msg.role}`"
        >
          <div class="msg-meta">
            {{ msg.name || messageRoleLabel(msg.role) }} · {{ msg.time }}
          </div>
          <div class="msg-content">
            {{ msg.content }}
          </div>
        </div>
        <div
          v-if="streaming"
          class="chat-msg msg-assistant"
        >
          <div class="msg-meta">
            {{ aiDisplayLabel }} · 回复中
          </div>
          <div class="msg-content">
            {{ streamText }}<span class="cursor">|</span>
          </div>
        </div>
      </div>

      <div class="chat-input-row">
        <el-input
          ref="inputRef"
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          :placeholder="auth.isLoggedIn ? '输入消息，Enter 发送，Shift+Enter 换行' : '请先登录后再使用 AI 对话'"
          :disabled="sending || !auth.isLoggedIn"
          @keydown.enter.exact.prevent="onSend"
        />
        <div class="input-actions">
          <span class="input-hint">{{ activeChapterLabel }}</span>
          <div class="input-buttons">
            <el-button
              size="small"
              :icon="Close"
              :disabled="!sending"
              @click="cancelReply"
            >
              取消回复
            </el-button>
            <el-button
              type="primary"
              size="small"
              :loading="sending"
              :disabled="!input.trim() || !auth.isLoggedIn"
              @click="onSend"
            >
              发送
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue';
import { Close, Delete, Refresh } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import { useAuthStore } from '../../stores/auth';
import api, { buildWsUrl, sendWsAuth } from '../../utils/api';

const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'close']);

const visible = ref(props.modelValue);
watch(() => props.modelValue, value => { visible.value = value; });
watch(visible, value => emit('update:modelValue', value));

const bookStore = useBookStore();
const auth = useAuthStore();
const bookId = computed(() => bookStore.currentBookId || (bookStore.books.length === 1 ? bookStore.books[0]?.id : null));
const activeChapter = computed(() => bookStore.activeChapterId ? bookStore.getChapterTab(bookStore.activeChapterId) : null);
const activeChapterLabel = computed(() => {
  if (!bookId.value) return '选择作品后会自动带入作品上下文';
  if (!activeChapter.value) return '当前作品上下文';
  return `当前章节：${activeChapter.value.title || `#${activeChapter.value.id}`}`;
});

const characters = ref([]);
const selfCharacterId = ref(0);
const aiCharacterId = ref(0);
const messages = ref([]);
const input = ref('');
const sending = ref(false);
const streaming = ref(false);
const streamText = ref('');
const statusText = ref('');
const msgContainer = ref(null);
const inputRef = ref(null);
let ws = null;

const selfCharacter = computed(() => characters.value.find(ch => Number(ch.id) === Number(selfCharacterId.value)) || null);
const aiCharacter = computed(() => characters.value.find(ch => Number(ch.id) === Number(aiCharacterId.value)) || null);
const selfDisplayLabel = computed(() => selfCharacter.value?.name || '我');
const aiDisplayLabel = computed(() => aiCharacter.value?.name || '写作助手');
const contextLabel = computed(() => {
  const selfPart = selfCharacter.value ? `你：${characterLabel(selfCharacter.value)}` : '你：作者本人';
  const aiPart = aiCharacter.value ? `AI：${characterLabel(aiCharacter.value)}` : 'AI：写作助手';
  return `${selfPart}  |  ${aiPart}`;
});

watch(bookId, async () => {
  selfCharacterId.value = 0;
  aiCharacterId.value = 0;
  clearHistory();
  if (visible.value) await loadCharacters();
});

async function onOpen() {
  await loadCharacters();
  nextTick(() => inputRef.value?.focus?.());
}

async function loadCharacters() {
  if (!bookId.value) {
    characters.value = [];
    return;
  }
  try {
    const { data } = await api.get(`/workspace/books/${bookId.value}/characters`);
    characters.value = data.items || [];
    const ids = new Set(characters.value.map(ch => Number(ch.id)));
    if (!ids.has(Number(selfCharacterId.value))) selfCharacterId.value = 0;
    if (!ids.has(Number(aiCharacterId.value))) aiCharacterId.value = 0;
  } catch {
    characters.value = [];
    ElMessage.warning('人物身份加载失败');
  }
}

function onPersonaChange() {
  if (messages.value.length) {
    clearHistory();
    ElMessage.info('身份已切换，对话历史已清空');
  }
}

function onSend() {
  if (!auth.requireAiAccess()) return;
  const text = input.value.trim();
  if (!text || sending.value) return;

  const userMessage = {
    role: 'user',
    content: text,
    name: selfDisplayLabel.value,
    time: timeNow(),
  };
  messages.value.push(userMessage);
  input.value = '';
  sending.value = true;
  streaming.value = true;
  streamText.value = '';
  statusText.value = '正在连接 AI...';

  const taskId = Date.now().toString();
  ws = new WebSocket(buildWsUrl('/ws/chat'));

  ws.onopen = () => {
    statusText.value = 'AI 思考中...';
    sendWsAuth(ws);
    ws.send(JSON.stringify({
      type: 'chat',
      task_id: taskId,
      payload: {
        messages: messages.value.map(item => ({ role: item.role, content: item.content })),
        book_id: bookId.value,
        chapter_id: bookStore.activeChapterId,
        self_character_id: selfCharacterId.value || null,
        ai_character_id: aiCharacterId.value || null,
        current_content: activeChapter.value?.content || '',
      },
    }));
  };

  ws.onmessage = (event) => {
    const msg = safeParse(event.data);
    if (!msg) return;
    if (msg.type === 'progress') {
      statusText.value = msg.payload?.message || 'AI 思考中...';
      return;
    }
    if (msg.type === 'chunk') {
      streamText.value += msg.payload?.text || '';
      scrollBottom();
      return;
    }
    if (msg.type === 'result') {
      finishReply(msg.payload || {});
      return;
    }
    if (msg.type === 'error') {
      failReply(msg.payload?.message || '对话失败');
    }
  };

  ws.onerror = () => failReply('连接 AI 服务失败');
  ws.onclose = () => {
    if (sending.value) failReply('AI 连接已断开');
  };

  nextTick(scrollBottom);
}

function finishReply(payload) {
  const cancelled = payload.status === 'cancelled';
  const text = String(payload.text || streamText.value || '').trim();
  if (text) {
    messages.value.push({
      role: 'assistant',
      content: text,
      name: aiDisplayLabel.value,
      time: timeNow(),
    });
  } else if (cancelled) {
    ElMessage.info('回复已取消');
  }
  sending.value = false;
  streaming.value = false;
  streamText.value = '';
  statusText.value = cancelled ? '回复已取消' : '';
  closeWs();
  nextTick(scrollBottom);
}

function failReply(message) {
  ElMessage.error(message);
  sending.value = false;
  streaming.value = false;
  streamText.value = '';
  statusText.value = '';
  closeWs();
}

function cancelReply() {
  if (!ws || !sending.value) return;
  try {
    ws.send(JSON.stringify({ type: 'cancel', task_id: Date.now().toString() }));
  } catch {
    // Ignore socket race; the close handler will reset state.
  }
  statusText.value = '正在取消回复...';
}

function clearHistory() {
  if (sending.value) return;
  messages.value = [];
  streamText.value = '';
  statusText.value = '';
}

function scrollBottom() {
  nextTick(() => {
    if (msgContainer.value) msgContainer.value.scrollTop = msgContainer.value.scrollHeight;
  });
}

function closeWs() {
  if (ws) {
    const socket = ws;
    ws = null;
    socket.onclose = null;
    socket.close();
  }
}

function safeParse(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function characterLabel(ch) {
  const name = String(ch?.name || '未命名').trim();
  const role = String(ch?.role || '').trim();
  return role ? `${name} · ${role}` : name;
}

function messageRoleLabel(role) {
  return role === 'assistant' ? aiDisplayLabel.value : selfDisplayLabel.value;
}

function timeNow() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: min(70vh, 620px);
  min-height: 0;
}

.persona-bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  align-items: end;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}

.persona-field {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.persona-label,
.chat-status,
.input-hint,
.msg-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.persona-actions,
.input-actions,
.input-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-status {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  min-height: 26px;
  align-items: center;
}

.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 2px;
}

.chat-msg {
  margin-bottom: 12px;
  max-width: 84%;
}

.msg-user {
  margin-left: auto;
}

.msg-user .msg-meta {
  text-align: right;
}

.msg-content {
  padding: 9px 12px;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-user .msg-content {
  background: var(--color-primary);
  color: #fff;
  border-radius: 12px 12px 3px 12px;
}

.msg-assistant .msg-content {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-radius: 12px 12px 12px 3px;
}

.cursor {
  animation: blink 1s infinite;
}

.chat-input-row {
  display: grid;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--border-light);
}

.input-actions {
  justify-content: space-between;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

@media (max-width: 760px) {
  .persona-bar {
    grid-template-columns: 1fr;
  }

  .persona-actions,
  .input-actions {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .chat-msg {
    max-width: 94%;
  }
}
</style>
