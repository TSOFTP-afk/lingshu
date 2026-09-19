<template>
  <div class="content-editor-wrapper">
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <span
          class="editor-title"
          :title="title"
        >{{ title || '未命名章节' }}</span>
        <el-tag
          v-if="dirty"
          type="warning"
          size="small"
          effect="plain"
        >
          未保存
        </el-tag>
        <el-tag
          v-else
          type="success"
          size="small"
          effect="plain"
        >
          已保存
        </el-tag>
        <el-tag
          v-if="readonly"
          type="info"
          size="small"
          effect="dark"
        >
          展示态
        </el-tag>
      </div>
      <div class="toolbar-right">
        <span class="word-count">正文 {{ wordCount }} 字</span>
        <span class="word-count">大纲 {{ outlineWordCount }} 字</span>
        <span
          class="ai-probability"
          :class="aiProbabilityClass"
        >{{ aiProbabilityText }}</span>
        <el-button
          v-if="readonly"
          type="primary"
          size="small"
          @click="$emit('edit')"
        >
          <el-icon><Edit /></el-icon>
          <span>编辑</span>
        </el-button>
      </div>
    </div>

    <div
      v-if="showActionbar"
      class="chapter-actionbar"
    >
      <el-tooltip
        content="润色当前章节"
        placement="bottom"
      >
        <el-button
          class="action-button"
          :disabled="!hasContent || !auth.isLoggedIn"
          @click="onPolish"
        >
          <el-icon><MagicStick /></el-icon>
          <span>润色</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        content="检测当前章节 AI 生成概率"
        placement="bottom"
      >
        <el-button
          class="action-button"
          :disabled="!hasContent || !auth.isLoggedIn"
          @click="$emit('detect-ai')"
        >
          <el-icon><DataAnalysis /></el-icon>
          <span>AI率检测</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        content="保存当前章节"
        placement="bottom"
      >
        <el-button
          class="action-button primary-action"
          type="primary"
          :disabled="!dirty"
          @click="$emit('save')"
        >
          <el-icon><DocumentChecked /></el-icon>
          <span>保存</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        content="删除所有未保存变动，恢复到最后一次保存"
        placement="bottom"
      >
        <el-button
          class="action-button"
          :disabled="!dirty"
          @click="$emit('revert')"
        >
          <el-icon><RefreshLeft /></el-icon>
          <span>回退</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        content="复制整章正文"
        placement="bottom"
      >
        <el-button
          class="action-button"
          :disabled="!hasContent"
          @click="copyChapter"
        >
          <el-icon><CopyDocument /></el-icon>
          <span>全章复制</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        content="打开 AI 纠错"
        placement="bottom"
      >
        <el-button
          class="action-button"
          :disabled="!hasContent || !auth.isLoggedIn"
          @click="openCorrection"
        >
          <el-icon><EditPen /></el-icon>
          <span>纠错</span>
        </el-button>
      </el-tooltip>
      <el-tooltip
        content="搜索当前作品"
        placement="bottom"
      >
        <el-button
          class="action-button"
          @click="openSearch"
        >
          <el-icon><Search /></el-icon>
          <span>搜索</span>
        </el-button>
      </el-tooltip>
    </div>

    <div class="editor-body">
      <div
        ref="nativeEditorRef"
        class="native-text-editor"
        @click="focus"
      >
        <div
          class="line-marker-layer"
          aria-hidden="true"
          :style="{ transform: `translateY(${-markerScrollTop}px)` }"
        >
          <div class="line-marker-padding-top" />
          <div
            v-for="item in visualLines"
            :key="item.key"
            class="line-marker-row"
          >
            <span class="line-marker">{{ item.number }}</span>
          </div>
        </div>

        <!-- 隐藏的镜像层：用于测量每个逻辑行的视觉行数，与 textarea 共享字体/宽度/软换行规则 -->
        <div
          ref="mirrorRef"
          class="content-mirror"
          aria-hidden="true"
        >
          <div
            v-for="(line, idx) in allLines"
            :key="idx"
            class="mirror-line"
          >{{ line.text || ' ' }}</div>
        </div>

        <textarea
          ref="textareaRef"
          v-model="localContent"
          class="content-textarea"
          :readonly="readonly"
          spellcheck="false"
          autocomplete="off"
          autocorrect="off"
          autocapitalize="off"
          wrap="soft"
          @keydown="onEditorKeydown"
          @scroll="syncMarkerScroll"
        />
      </div>
    </div>

    <el-dialog
      v-model="polishDialogVisible"
      title="选区润色"
      width="880px"
      class="polish-dialog"
      append-to-body
      destroy-on-close
    >
      <div class="polish-dialog-body">
        <section class="polish-column">
          <div class="polish-column-title">
            润色前
          </div>
          <div class="polish-text polish-text--before">
            <span
              v-for="(part, index) in polishDiff.before"
              :key="`before-${index}`"
              :class="{ 'diff-changed': part.changed }"
            >{{ part.text }}</span>
          </div>
        </section>

        <section class="polish-column">
          <div class="polish-column-title">
            <span>润色后</span>
            <el-tag
              v-if="polishLoading"
              size="small"
              type="info"
            >
              生成中
            </el-tag>
          </div>
          <div
            v-loading="polishLoading"
            class="polish-text polish-text--after"
          >
            <template v-if="polishResult">
              <span
                v-for="(part, index) in polishDiff.after"
                :key="`after-${index}`"
                :class="{ 'diff-changed': part.changed }"
              >{{ part.text }}</span>
            </template>
            <span
              v-else
              class="polish-placeholder"
            >等待润色结果...</span>
          </div>
        </section>
      </div>

      <template #footer>
        <el-button @click="polishDialogVisible = false">
          取消
        </el-button>
        <el-button
          :loading="polishLoading"
          @click="requestPolishSelection"
        >
          重新润色
        </el-button>
        <el-button
          type="primary"
          :disabled="polishLoading || !polishResult"
          @click="applyPolishResult"
        >
          应用到正文
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
// 结构：本组件只保留编辑内核（内容双向同步/虚拟行号层/选区与查找替换）；
// AI 润色 → composables/editor/useEditorAiPolish，AI 概率标注 → useEditorAiProbability，
// 写作探针 8 秒防抖轮询 → useEditorProbePolling。共享状态（props/localContent/textareaRef/selectRange）由组件传入。
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import {
  CopyDocument,
  DataAnalysis,
  DocumentChecked,
  Edit,
  EditPen,
  MagicStick,
  RefreshLeft,
  Search,
} from '@element-plus/icons-vue';
import { useEventBus } from '../../composables/useEventBus';
import { useAuthStore } from '../../stores/auth';
import { useEditorAiPolish } from '../../composables/editor/useEditorAiPolish';
import { useEditorAiProbability } from '../../composables/editor/useEditorAiProbability';
import { useEditorProbePolling } from '../../composables/editor/useEditorProbePolling';

const auth = useAuthStore();
const { on, off, emit: busEmit } = useEventBus();

const props = defineProps({
  chapterId: { type: [Number, String, null], default: null },
  content: { type: String, default: '' },
  title: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  showActionbar: { type: Boolean, default: true },
  aiProbability: { type: Number, default: 0 },
  aiProbabilityLevel: { type: String, default: 'none' },
  readonly: { type: Boolean, default: true },
});

const emit = defineEmits(['update:content', 'change', 'save', 'revert', 'detect-ai', 'edit']);

const localContent = ref(props.content);
const applyingExternalContent = ref(false);
const textareaRef = ref(null);
const nativeEditorRef = ref(null);
const mirrorRef = ref(null);

// AI 域（润色/概率标注/探针轮询）：共享状态以 ctx 单一数据源传入，模板引用名不变
const {
  polishDialogVisible,
  polishLoading,
  polishResult,
  polishDiff,
  onPolish,
  requestPolishSelection,
  applyPolishResult,
} = useEditorAiPolish({
  props,
  localContent,
  textareaRef,
  selectRange,
  auth,
});
const { aiProbabilityText, aiProbabilityClass } = useEditorAiProbability({ props });
const { scheduleProbeScan } = useEditorProbePolling({ props });

// 行号层跟随 textarea 滚动（transform: translateY）
const VIRTUAL_LINE_HEIGHT = 24; // 与 --content-line-height 默认值一致
const VIRTUAL_PADDING_Y = 12; // 与 --content-editor-padding-y 默认值一致
const markerScrollTop = ref(0);
let resizeObserver = null;

watch(() => props.content, (val) => {
  if (val !== localContent.value) {
    applyingExternalContent.value = true;
    localContent.value = val;
    nextTick(() => {
      applyingExternalContent.value = false;
      syncMarkerScroll();
    });
  }
});

watch(localContent, (val) => {
  if (applyingExternalContent.value) return;
  emit('update:content', val);
  emit('change', val);
  nextTick(syncMarkerScroll);
  scheduleProbeScan();
});

const editorLines = computed(() => (localContent.value || '').split('\n'));
const totalLineCount = computed(() => editorLines.value.length);

const allLines = computed(() => {
  const lines = editorLines.value;
  return lines.map((text, index) => ({ index, number: index + 1, text }));
});

// 视觉行号：每个逻辑行根据软换行展开成 N 个视觉行，每行 24px
// 通过镜像层测量每个逻辑行的高度，除以行高得到视觉行数
const visualLines = ref([]);

function recomputeVisualLines() {
  const mirror = mirrorRef.value;
  if (!mirror) {
    // 兜底：mirror 未就绪时按每行 1 个视觉行
    visualLines.value = allLines.value.map((line) => ({ key: line.index, number: line.number }));
    return;
  }
  const lineEls = mirror.querySelectorAll('.mirror-line');
  const lineHeight = VIRTUAL_LINE_HEIGHT;
  const result = [];
  let visualNumber = 1;
  lineEls.forEach((el) => {
    const h = el.getBoundingClientRect().height;
    const count = Math.max(1, Math.round(h / lineHeight));
    for (let i = 0; i < count; i += 1) {
      // 仅该逻辑行的第一视觉行显示行号，其余空——但用户要求每行连续编号
      // 这里改为：每个视觉行都编一个连续号
      result.push({ key: `${result.length}`, number: visualNumber });
      visualNumber += 1;
    }
  });
  visualLines.value = result;
}

// 监听内容变化、容器宽度变化时重新计算视觉行
watch([allLines], () => {
  nextTick(recomputeVisualLines);
}, { flush: 'post' });

const wordCount = computed(() => {
  const text = localContent.value || '';
  return text.replace(/\s/g, '').length;
});

const outlineWordCount = computed(() => 0);
const hasContent = computed(() => Boolean((localContent.value || '').trim()));

function onEditorKeydown(event) {
  const key = event.key.toLowerCase();
  if ((event.ctrlKey || event.metaKey) && key === 's') {
    event.preventDefault();
    emit('save');
    return;
  }
  if ((event.ctrlKey || event.metaKey) && key === 'f') {
    event.preventDefault();
    openSearch();
  }
}

async function copyChapter() {
  try {
    await navigator.clipboard.writeText(localContent.value || '');
    ElMessage.success('整章正文已复制');
  } catch {
    ElMessage.error('复制失败');
  }
}

function openCorrection() {
  if (!auth.requireAiAccess()) return;
  busEmit('lingshu:open-correction', {
    text: localContent.value || '',
  });
}

function openSearch() {
  busEmit('lingshu:open-search', {
    query: selectedSearchText(),
  });
}

function selectedSearchText() {
  const textarea = textareaRef.value;
  if (!textarea) return '';
  const selected = localContent.value.slice(textarea.selectionStart, textarea.selectionEnd).trim();
  return selected && !selected.includes('\n') ? selected : '';
}

function onChapterFind(event) {
  const detail = event || {};
  if (!isForThisChapter(detail.chapterId)) return;
  let start = Number(detail.start);
  let end = Number(detail.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
    const range = findRange(String(detail.query || ''), detail.direction || 'next', Boolean(detail.caseSensitive));
    if (!range) return;
    start = range.start;
    end = range.end;
  }
  selectRange(start, end);
}

function onChapterReplace(event) {
  const detail = event || {};
  if (!isForThisChapter(detail.chapterId)) return;
  const query = String(detail.query || '');
  if (!query) return;
  const replacement = String(detail.replacement ?? '');
  const caseSensitive = Boolean(detail.caseSensitive);
  const text = localContent.value || '';

  if (detail.all) {
    const nextText = text.replace(new RegExp(escapeRegExp(query), caseSensitive ? 'g' : 'gi'), replacement);
    if (nextText === text) return;
    localContent.value = nextText;
    nextTick(() => selectRange(0, 0));
    return;
  }

  let start = Number(detail.start);
  let end = Number(detail.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
    const range = findRange(query, 'next', caseSensitive);
    if (!range) return;
    start = range.start;
    end = range.end;
  }

  const current = text.slice(start, end);
  const matches = caseSensitive ? current === query : current.toLowerCase() === query.toLowerCase();
  if (!matches) return;
  localContent.value = `${text.slice(0, start)}${replacement}${text.slice(end)}`;
  nextTick(() => selectRange(start, start + replacement.length));
}

function findRange(query, direction = 'next', caseSensitive = false) {
  const needle = String(query || '');
  if (!needle) return null;
  const text = localContent.value || '';
  const source = caseSensitive ? text : text.toLowerCase();
  const target = caseSensitive ? needle : needle.toLowerCase();
  const textarea = textareaRef.value;
  const cursor = textarea ? (direction === 'prev' ? textarea.selectionStart : textarea.selectionEnd) : 0;
  let start = direction === 'prev'
    ? source.lastIndexOf(target, Math.max(0, cursor - 1))
    : source.indexOf(target, cursor);
  if (start < 0) {
    start = direction === 'prev' ? source.lastIndexOf(target) : source.indexOf(target);
  }
  if (start < 0) return null;
  return { start, end: start + needle.length };
}

function selectRange(start, end) {
  const textarea = textareaRef.value;
  if (!textarea) return;
  const safeStart = Math.max(0, Math.min(start, localContent.value.length));
  const safeEnd = Math.max(safeStart, Math.min(end, localContent.value.length));
  textarea.focus();
  textarea.setSelectionRange(safeStart, safeEnd);
  scrollSelectionIntoView(safeStart);
}

function scrollSelectionIntoView(start) {
  const textarea = textareaRef.value;
  if (!textarea) return;
  const line = localContent.value.slice(0, start).split('\n').length;
  textarea.scrollTop = Math.max(0, (line - 4) * 24);
  syncMarkerScroll();
}

function isForThisChapter(chapterId) {
  return !chapterId || Number(chapterId) === Number(props.chapterId);
}

function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function syncMarkerScroll() {
  const textarea = textareaRef.value;
  if (!textarea) return;
  // 行号层通过 transform: translateY(-scrollTop) 跟随 textarea 滚动
  markerScrollTop.value = textarea.scrollTop;
}

function focus() {
  textareaRef.value?.focus?.();
}

onMounted(() => {
  on('lingshu:chapter-find', onChapterFind);
  on('lingshu:chapter-replace', onChapterReplace);
  nextTick(() => {
    recomputeVisualLines();
    syncMarkerScroll();
  });
  // 监听编辑器容器尺寸变化（拖拽分隔条、窗口缩放），重新计算视觉行
  if (typeof ResizeObserver !== 'undefined' && nativeEditorRef.value) {
    resizeObserver = new ResizeObserver(() => {
      recomputeVisualLines();
      syncMarkerScroll();
    });
    resizeObserver.observe(nativeEditorRef.value);
  }
});

onUnmounted(() => {
  off('lingshu:chapter-find', onChapterFind);
  off('lingshu:chapter-replace', onChapterReplace);
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
});

defineExpose({
  wordCount,
  focus,
  onPolish,
  copyChapter,
  openCorrection,
  openSearch,
});
</script>

<style scoped>
.content-editor-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-primary);
}

.editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding: 0 20px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
  gap: 8px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.editor-title {
  font-size: var(--font-size-base);
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.word-count {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  padding: 0 3px;
}

.ai-probability {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid currentColor;
  font-size: var(--font-size-xs);
  font-weight: 700;
  white-space: nowrap;
}

.ai-probability--unknown {
  color: var(--text-placeholder);
  background: var(--bg-secondary);
}

.ai-probability--danger {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.10);
}

.ai-probability--warning {
  color: #b7791f;
  background: rgba(245, 158, 11, 0.14);
}

.ai-probability--success {
  color: #15803d;
  background: rgba(34, 197, 94, 0.12);
}

.chapter-actionbar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  min-height: 62px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--border-light);
  background: linear-gradient(180deg, var(--bg-primary), var(--bg-secondary));
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.chapter-actionbar::-webkit-scrollbar {
  display: none;
}

.action-button {
  height: 34px;
  min-width: 84px;
  padding: 0 16px;
  border-radius: 6px;
  font-weight: 700;
}

.primary-action {
  min-width: 102px;
}

@media (max-width: 980px) {
  .chapter-actionbar {
    justify-content: flex-start;
    gap: 8px;
  }

  .action-button {
    min-width: 72px;
    padding: 0 10px;
  }
}

.editor-body {
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  display: flex;
}

.native-text-editor {
  --content-font-size: var(--editor-font-size, 15px);
  --content-line-height: var(--editor-line-height, 24px);
  --content-gutter-width: 78px;
  --content-editor-padding-y: 12px;
  --content-editor-padding-right: 14px;
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--bg-primary);
}

.line-marker-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: var(--content-gutter-width);
  display: flex;
  flex-direction: column;
  color: #0c6f88;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
  font-size: var(--content-font-size);
  line-height: var(--content-line-height);
  pointer-events: none;
  user-select: none;
  will-change: transform;
  /* 外层 native-text-editor 负责裁剪溢出内容 */
}

.line-marker-padding-top {
  height: var(--content-editor-padding-y);
  flex-shrink: 0;
}

.line-marker-row {
  display: block;
  height: var(--content-line-height);
}

.line-marker {
  display: block;
  box-sizing: border-box;
  width: 100%;
  height: var(--content-line-height);
  padding-right: 18px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  line-height: var(--content-line-height);
}

/* 隐藏镜像层：与 textarea 共享字体/宽度/软换行规则，用于测量视觉行数 */
.content-mirror {
  position: absolute;
  top: 0;
  left: 0;
  width: calc(100% - var(--content-gutter-width) - var(--content-editor-padding-right));
  padding-top: var(--content-editor-padding-y);
  padding-bottom: var(--content-editor-padding-y);
  visibility: hidden;
  pointer-events: none;
  z-index: -1;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
  font-size: var(--content-font-size);
  line-height: var(--content-line-height);
}

.mirror-line {
  white-space: pre-wrap;
  overflow-wrap: break-word;
  word-break: break-all;
  min-height: var(--content-line-height);
}

.content-textarea {
  position: absolute;
  inset: 0;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  resize: none;
  border: 0;
  outline: none;
  padding: var(--content-editor-padding-y) var(--content-editor-padding-right) var(--content-editor-padding-y) var(--content-gutter-width);
  color: var(--text-primary);
  background: transparent;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
  font-size: var(--content-font-size);
  line-height: var(--content-line-height);
  letter-spacing: 0;
  overflow: auto;
}

.content-textarea::selection {
  background: rgba(22, 163, 156, 0.22);
}

/* 展示态：只读，光标与背景微调 */
.content-textarea:read-only {
  cursor: default;
  background: color-mix(in srgb, var(--bg-secondary) 30%, transparent);
}

.content-textarea::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.content-textarea::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 5px;
}

.content-textarea::-webkit-scrollbar-track {
  background: var(--bg-secondary);
}

:global(.polish-dialog .el-dialog__body) {
  padding-top: 6px;
}

.polish-dialog-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}

.polish-column {
  min-width: 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
  overflow: hidden;
}

.polish-column-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 38px;
  padding: 0 12px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-light);
}

.polish-text {
  min-height: 260px;
  max-height: 52vh;
  overflow: auto;
  padding: 12px 14px;
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.9;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.polish-text--before .diff-changed {
  color: #c2410c;
  background: rgba(248, 113, 113, 0.12);
  text-decoration: line-through;
  text-decoration-thickness: 1px;
}

.polish-text--after .diff-changed {
  color: #dc2626;
  background: rgba(248, 113, 113, 0.14);
  font-weight: 700;
}

.polish-placeholder {
  color: var(--text-placeholder);
}

@media (max-width: 860px) {
  .polish-dialog-body {
    grid-template-columns: 1fr;
  }
}
</style>
