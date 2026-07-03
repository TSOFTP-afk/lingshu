<template>
  <div class="generate-tab">
    <!-- 顶部标题栏 -->
    <div class="tab-header">
      <span class="tab-title">生成长篇</span>
    </div>

    <!-- 未选中章节空状态 -->
    <el-empty
      v-if="!currentChapterId"
      description="请先在左侧选择章节"
      :image-size="60"
    />

    <template v-else>
      <!-- ===== 上块：本章大纲 ===== -->
      <div class="gen-section gen-section--outline">
        <div class="gen-section-head">
          <span class="gen-section-title">本章大纲</span>
          <el-button
            type="primary"
            size="small"
            plain
            @click="openOutlineDialog"
          >
            <el-icon><EditPen /></el-icon> 编辑大纲
          </el-button>
        </div>
        <div
          class="outline-preview"
          @click="openOutlineDialog"
        >
          {{ outlinePreview || '点击编辑本章大纲…' }}
        </div>
      </div>

      <!-- ===== 生成控制区 ===== -->
      <div class="gen-section gen-section--control">
        <div class="gen-section-head">
          <span class="gen-section-title">生成本章</span>
        </div>
        <div class="gen-fields">
          <!-- 模式选择 -->
          <div class="gen-field">
            <label class="gen-field-label">生成模式</label>
            <el-radio-group
              v-model="genForm.mode"
              size="small"
            >
              <el-radio-button value="draft">
                草稿
              </el-radio-button>
              <el-radio-button value="continue">
                续写
              </el-radio-button>
              <el-radio-button value="polish">
                润色
              </el-radio-button>
            </el-radio-group>
          </div>
          <!-- skill 选择器 -->
          <div class="gen-field">
            <label class="gen-field-label">写作技巧 Skills</label>
            <el-select
              v-model="generationStore.selectedSkillIds"
              multiple
              filterable
              clearable
              placeholder="选择技能（可选）"
              size="small"
              style="width: 100%"
            >
              <el-option
                v-for="sk in generationStore.writingSkills"
                :key="sk.skill_id"
                :label="`${sk.name} · ${sk.category}`"
                :value="sk.skill_id"
              />
            </el-select>
          </div>
          <!-- 生成按钮 -->
          <div class="gen-actions">
            <el-button
              type="primary"
              :loading="generating"
              :disabled="!canGenerate"
              @click="onGenerate"
            >
              {{ generating ? '生成中…' : '开始生成' }}
            </el-button>
            <el-button
              v-if="generating"
              type="danger"
              plain
              size="small"
              @click="onCancel"
            >
              取消
            </el-button>
          </div>
          <!-- 进度条 -->
          <div
            v-if="generating"
            class="gen-progress"
          >
            <el-progress
              :percentage="progress.percent"
              :status="progress.status || ''"
            />
            <div class="gen-progress-msg">
              {{ progress.message }}
            </div>
          </div>
        </div>
      </div>

      <!-- ===== 下块：生成快照 ===== -->
      <div class="gen-section gen-section--snapshots">
        <div class="gen-section-head">
          <span class="gen-section-title">生成快照</span>
          <span
            v-if="snapshots.length"
            class="gen-count"
          >{{ snapshots.length }}</span>
        </div>
        <div class="snapshots-list">
          <div
            v-for="snap in snapshots"
            :key="snap.id"
            class="snap-card"
            :class="[`snap-card--${snap.status}`, { 'snap-card--highlight': snap.id === highlightId }]"
          >
            <div
              class="snap-card-head"
              @click="toggleExpand(snap.id)"
            >
              <span
                class="snap-mode"
                :class="`snap-mode--${snap.mode}`"
              >{{ modeLabel(snap.mode) }}</span>
              <span
                class="snap-status"
                :class="`snap-status--${snap.status}`"
              >{{ statusLabel(snap.status) }}</span>
              <span class="snap-time">{{ formatTime(snap.created_at) }}</span>
              <span class="snap-length">{{ (snap.generated_text || '').length }} 字</span>
              <el-icon
                class="snap-arrow"
                :class="{ 'is-open': expanded.has(snap.id) }"
              >
                <ArrowRight />
              </el-icon>
            </div>
            <div class="snap-outline">
              {{ snapOutlinePreview(snap) }}
            </div>
            <transition name="snap-fold">
              <div
                v-if="expanded.has(snap.id)"
                class="snap-detail"
              >
                <div
                  v-if="snap.generated_text"
                  class="snap-text"
                >
                  {{ snap.generated_text }}
                </div>
                <div
                  v-if="parseSkills(snap.selected_skills_json).length"
                  class="snap-skills"
                >
                  <span class="snap-skills-label">所用 Skills：</span>
                  <span
                    v-for="sk in parseSkills(snap.selected_skills_json)"
                    :key="sk.skill_id || sk.name"
                    class="snap-skill-tag"
                  >
                    {{ sk.name }}
                  </span>
                </div>
                <div class="snap-actions">
                  <el-button
                    v-if="snap.status === 'success' && snap.generated_text"
                    size="small"
                    type="primary"
                    plain
                    @click="onRestore(snap)"
                  >
                    恢复到正文
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    text
                    @click="onDelete(snap)"
                  >
                    删除
                  </el-button>
                </div>
              </div>
            </transition>
          </div>
          <el-empty
            v-if="!snapshots.length"
            description="暂无生成快照"
            :image-size="50"
          />
        </div>
      </div>
    </template>

    <!-- 大纲编辑弹窗 -->
    <el-dialog
      v-model="outlineDialogVisible"
      title="编辑本章大纲"
      width="600px"
      :before-close="onOutlineClose"
    >
      <el-input
        v-model="outlineEdit"
        type="textarea"
        :rows="14"
        placeholder="输入本章大纲…"
        resize="vertical"
      />
      <template #footer>
        <el-button @click="outlineDialogVisible = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="outlineSaving"
          @click="onSaveOutline"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, reactive } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { EditPen, ArrowRight } from '@element-plus/icons-vue';
import { useBookStore } from '../../stores/book';
import { useGenerationStore } from '../../stores/generation';
import { useAuthStore } from '../../stores/auth';
import { useEventBus } from '../../composables/useEventBus';
import api, { buildWsUrl, sendWsAuth } from '../../utils/api';

const bookStore = useBookStore();
const auth = useAuthStore();
const generationStore = useGenerationStore();
const { emit } = useEventBus();

// 当前章节：bookStore.activeChapterId 为当前激活章节 id，
// activeTab 持有编辑器内实时正文与标题，chapterDetail 通过接口获取大纲
const currentChapterId = computed(() => bookStore.activeChapterId);
const activeTab = computed(() => (currentChapterId.value ? bookStore.getChapterTab(currentChapterId.value) : null));
const chapterDetail = ref(null);

const genForm = reactive({ mode: 'draft' });
const generating = ref(false);
const progress = reactive({ percent: 0, message: '', status: '' });
const generatingText = ref('');

// 大纲弹窗
const outlineDialogVisible = ref(false);
const outlineEdit = ref('');
const outlineSaving = ref(false);

// 快照展开与高亮
const expanded = ref(new Set());
const highlightId = ref(null);

const snapshots = computed(() => generationStore.snapshots);
const outlinePreview = computed(() => (chapterDetail.value?.outline || '').slice(0, 120));
const canGenerate = computed(() => !generating.value && !!currentChapterId.value && auth.isLoggedIn);

// WebSocket
let ws = null;
let currentTaskId = null;

async function loadChapterDetail(chapterId) {
  if (!chapterId) {
    chapterDetail.value = null;
    return;
  }
  try {
    const { data } = await api.get(`/workspace/chapters/${chapterId}`);
    chapterDetail.value = data;
  } catch {
    chapterDetail.value = null;
  }
}

function connectWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  ws = new WebSocket(buildWsUrl('/ws/generation'));
  ws.onopen = () => { sendWsAuth(ws); };
  ws.onmessage = onWSMessage;
  ws.onclose = () => { ws = null; };
  ws.onerror = () => { ElMessage.error('WebSocket 连接失败'); };
}

function closeWs() {
  if (ws) {
    try { ws.close(); } catch { /* ignore */ }
    ws = null;
  }
}

function onWSMessage(ev) {
  let msg;
  try { msg = JSON.parse(ev.data); } catch { return; }
  if (msg.task_id !== currentTaskId) return;
  if (msg.type === 'progress') {
    progress.percent = msg.payload.percent || 0;
    progress.message = msg.payload.message || '';
  } else if (msg.type === 'chunk') {
    generatingText.value += msg.payload.text || '';
    progress.percent = msg.payload.percent || 100;
    progress.message = '生成中…';
    progress.status = 'success';
  } else if (msg.type === 'result') {
    generating.value = false;
    const status = msg.payload.status || 'success';
    const succeeded = status === 'success' || status === 'ok';
    if (succeeded) {
      ElMessage.success('生成完成');
      generationStore.fetchSnapshots(currentChapterId.value).then(() => {
        if (snapshots.value.length) {
          highlightId.value = snapshots.value[0].id;
          setTimeout(() => { highlightId.value = null; }, 2000);
        }
      });
    } else {
      ElMessage.warning(`生成${status === 'cancelled' ? '已取消' : '失败'}`);
      generationStore.fetchSnapshots(currentChapterId.value);
    }
    progress.percent = 100;
    progress.status = succeeded ? 'success' : 'exception';
    closeWs();
  } else if (msg.type === 'error') {
    ElMessage.error(msg.payload?.message || '生成失败');
    generating.value = false;
    closeWs();
  }
}

async function onGenerate() {
  if (!auth.requireAiAccess()) return;
  if (!currentChapterId.value) {
    ElMessage.warning('请先在左侧选择章节');
    return;
  }
  if (!canGenerate.value) return;

  generating.value = true;
  generatingText.value = '';
  progress.percent = 0;
  progress.message = '连接中…';
  progress.status = '';
  currentTaskId = `gen-${Date.now()}`;

  // 转 selected_skills 为带 instruction_text 的结构
  let selectedSkills = [];
  if (generationStore.selectedSkillIds.length) {
    try {
      selectedSkills = await generationStore.toSelectedSkills(generationStore.selectedSkillIds);
    } catch {
      selectedSkills = [];
    }
  }

  // 组装 payload：必须含 selected_skills 与 chapter_id（WS 收到 result 时用 chapter_id 落快照）
  const payload = {
    type: 'generate',
    task_id: currentTaskId,
    payload: {
      mode: genForm.mode,
      book_title: bookStore.currentBook?.title || '',
      chapter_title: activeTab.value?.title || chapterDetail.value?.title || '',
      outline: chapterDetail.value?.outline || '',
      current_content: activeTab.value?.content || '',
      selected_skills: selectedSkills,
      chapter_id: currentChapterId.value,
    },
  };

  connectWS();
  const send = () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    } else {
      setTimeout(send, 200);
    }
  };
  send();
}

function onCancel() {
  if (ws && ws.readyState === WebSocket.OPEN && currentTaskId) {
    ws.send(JSON.stringify({ type: 'cancel', task_id: currentTaskId }));
  }
  generating.value = false;
  closeWs();
}

// 大纲弹窗
function openOutlineDialog() {
  outlineEdit.value = chapterDetail.value?.outline || '';
  outlineDialogVisible.value = true;
}
function onOutlineClose(done) { done(); }
async function onSaveOutline() {
  if (!currentChapterId.value) return;
  outlineSaving.value = true;
  try {
    await api.patch(`/workspace/chapters/${currentChapterId.value}`, { outline: outlineEdit.value });
    await loadChapterDetail(currentChapterId.value);
    ElMessage.success('大纲已保存');
    outlineDialogVisible.value = false;
  } catch {
    ElMessage.error('保存失败');
  } finally {
    outlineSaving.value = false;
  }
}

// 快照操作
function toggleExpand(id) {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expanded.value = next;
}

async function onRestore(snap) {
  try {
    await ElMessageBox.confirm(
      '确定将此快照内容恢复到章节正文？当前正文将备份到章节快照。',
      '确认恢复',
      { type: 'warning' },
    );
    await generationStore.restoreSnapshot(snap.id);
    ElMessage.success('已恢复到正文');
    // 刷新章节详情并将新正文同步到编辑器 tab
    await loadChapterDetail(currentChapterId.value);
    const newContent = chapterDetail.value?.content || '';
    if (currentChapterId.value) {
      bookStore.setTabContent(currentChapterId.value, newContent, { dirty: false, savedContent: newContent });
    }
    emit('lingshu:chapter-content-updated', { chapterId: currentChapterId.value });
    await generationStore.fetchSnapshots(currentChapterId.value);
  } catch { /* cancelled */ }
}

async function onDelete(snap) {
  try {
    await ElMessageBox.confirm('确定删除此生成快照？', '确认删除', { type: 'warning' });
    await generationStore.deleteSnapshot(snap.id);
    ElMessage.success('已删除');
    generationStore.fetchSnapshots(currentChapterId.value);
  } catch { /* cancelled */ }
}

// 辅助
function modeLabel(m) {
  return { draft: '草稿', continue: '续写', polish: '润色' }[m] || m;
}
function statusLabel(s) {
  return { success: '成功', failed: '失败', cancelled: '取消' }[s] || s;
}
function snapOutlinePreview(snap) {
  const text = snap.outline || '';
  if (!text) return '无大纲';
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}
function formatTime(t) {
  if (!t) return '';
  const d = new Date(String(t).replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
function parseSkills(json) {
  try { return JSON.parse(json || '[]'); } catch { return []; }
}

// 监听章节切换
watch(currentChapterId, (id) => {
  if (id) {
    loadChapterDetail(id);
    generationStore.fetchSnapshots(id);
  } else {
    chapterDetail.value = null;
    generationStore.clearSnapshots();
  }
});

onMounted(() => {
  generationStore.fetchWritingSkills();
  if (currentChapterId.value) {
    loadChapterDetail(currentChapterId.value);
    generationStore.fetchSnapshots(currentChapterId.value);
  }
});

onUnmounted(() => {
  closeWs();
});
</script>

<style scoped>
.generate-tab { padding: 4px 0; }
.tab-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }

.gen-section {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-light);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.gen-section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.gen-section-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.gen-count {
  font-size: 10px;
  background: var(--bg-hover);
  color: var(--text-secondary);
  padding: 1px 6px;
  border-radius: 8px;
}

/* 大纲预览 */
.outline-preview {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  padding: 10px 12px;
  background: var(--bg-hover);
  border-radius: 6px;
  cursor: pointer;
  min-height: 40px;
  border: 1px dashed var(--border-light);
}
.outline-preview:hover { border-color: var(--accent-primary, #409eff); }

/* 生成控制 */
.gen-fields { display: flex; flex-direction: column; gap: 12px; }
.gen-field { display: flex; flex-direction: column; gap: 5px; }
.gen-field-label { font-size: 11px; color: var(--text-secondary); font-weight: 500; }
.gen-actions { display: flex; gap: 8px; }
.gen-progress { margin-top: 4px; }
.gen-progress-msg { font-size: 11px; color: var(--text-placeholder); margin-top: 4px; }

/* 快照列表 */
.snapshots-list { display: flex; flex-direction: column; gap: 8px; }
.snap-card {
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 10px 12px;
  transition: all 0.3s;
}
.snap-card:hover { box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04); }
.snap-card--success { border-left: 3px solid #67c23a; }
.snap-card--failed { border-left: 3px solid #f56c6c; }
.snap-card--cancelled { border-left: 3px solid #909399; }
.snap-card--highlight { animation: snap-highlight 2s ease; }
@keyframes snap-highlight {
  0% { background: rgba(64, 158, 255, 0.15); }
  100% { background: transparent; }
}
.snap-card-head { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 12px; }
.snap-mode { font-size: 10px; padding: 1px 8px; border-radius: 8px; font-weight: 600; }
.snap-mode--draft { background: rgba(64, 158, 255, 0.12); color: #409eff; }
.snap-mode--continue { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
.snap-mode--polish { background: rgba(230, 162, 60, 0.12); color: #e6a23c; }
.snap-status { font-size: 10px; padding: 1px 6px; border-radius: 8px; }
.snap-status--success { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
.snap-status--failed { background: rgba(245, 108, 108, 0.12); color: #f56c6c; }
.snap-status--cancelled { background: rgba(144, 147, 153, 0.12); color: #909399; }
.snap-time { font-size: 11px; color: var(--text-placeholder); }
.snap-length { font-size: 11px; color: var(--text-secondary); margin-left: auto; }
.snap-arrow { font-size: 11px; color: var(--text-placeholder); transition: transform 0.2s; }
.snap-arrow.is-open { transform: rotate(90deg); }
.snap-outline { font-size: 11px; color: var(--text-secondary); margin-top: 6px; line-height: 1.5; }
.snap-detail { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border-light); }
.snap-text {
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.7;
  max-height: 300px;
  overflow-y: auto;
  padding: 8px 10px;
  background: var(--bg-hover);
  border-radius: 4px;
  white-space: pre-wrap;
}
.snap-skills { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.snap-skills-label { font-size: 11px; color: var(--text-placeholder); }
.snap-skill-tag { font-size: 10px; padding: 1px 6px; border-radius: 6px; background: rgba(142, 113, 221, 0.12); color: #8e71dd; }
.snap-actions { margin-top: 10px; display: flex; gap: 8px; }

.snap-fold-enter-active,
.snap-fold-leave-active { transition: all 0.2s ease; overflow: hidden; }
.snap-fold-enter-from,
.snap-fold-leave-to { opacity: 0; max-height: 0; }
</style>
