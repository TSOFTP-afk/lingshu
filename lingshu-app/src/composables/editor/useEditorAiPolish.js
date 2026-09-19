// ContentEditor 域拆分：AI 润色（选区润色对话框状态 + 润色 API + 内联 diff + 应用回正文）
// ctx 为组件构造的共享上下文：props/localContent/textareaRef/selectRange/auth 均为组件单一数据源，禁止复制。
// 纯搬移自 src/components/workspace/ContentEditor.vue，业务逻辑未改动。
import { ref, computed, nextTick } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';

export function useEditorAiPolish(ctx) {
  const { props, localContent, textareaRef, selectRange, auth } = ctx;

  const polishDialogVisible = ref(false);
  const polishLoading = ref(false);
  const polishOriginal = ref('');
  const polishResult = ref('');
  const polishRange = ref({ start: 0, end: 0 });

  const polishDiff = computed(() => buildInlineDiff(polishOriginal.value, polishResult.value));

  async function onPolish() {
    if (!auth.requireAiAccess()) return;
    if (!props.chapterId) {
      ElMessage.warning('请先打开一个章节');
      return;
    }
    const selection = getSelectedRange();
    if (!selection || !selection.text.trim()) {
      ElMessage.warning('请先选中需要润色的正文');
      return;
    }
    polishOriginal.value = selection.text;
    polishResult.value = '';
    polishRange.value = { start: selection.start, end: selection.end };
    polishDialogVisible.value = true;
    await requestPolishSelection();
  }

  async function requestPolishSelection() {
    if (!props.chapterId || !polishOriginal.value.trim()) return;
    polishLoading.value = true;
    polishResult.value = '';
    try {
      const { data } = await api.post(`/workspace/chapters/${props.chapterId}/polish-selection`, {
        text: polishOriginal.value,
      });
      polishResult.value = String(data.polished || '').trim();
      if (!polishResult.value) {
        ElMessage.warning('润色结果为空');
      }
    } catch (e) {
      ElMessage.error(e.response?.data?.detail || e.message || '润色失败');
    } finally {
      polishLoading.value = false;
    }
  }

  function applyPolishResult() {
    if (!polishResult.value) return;
    const { start, end } = polishRange.value;
    const currentSelection = localContent.value.slice(start, end);
    if (currentSelection !== polishOriginal.value) {
      ElMessage.warning('正文已发生变化，请重新选中文本后润色');
      polishDialogVisible.value = false;
      return;
    }
    localContent.value = `${localContent.value.slice(0, start)}${polishResult.value}${localContent.value.slice(end)}`;
    polishDialogVisible.value = false;
    nextTick(() => selectRange(start, start + polishResult.value.length));
    ElMessage.success('已应用润色结果');
  }

  function getSelectedRange() {
    const textarea = textareaRef.value;
    if (!textarea) return null;
    const start = Math.min(textarea.selectionStart, textarea.selectionEnd);
    const end = Math.max(textarea.selectionStart, textarea.selectionEnd);
    if (end <= start) return null;
    return {
      start,
      end,
      text: localContent.value.slice(start, end),
    };
  }

  function buildInlineDiff(before, after) {
    if (!after) {
      return {
        before: [{ text: before || '', changed: false }],
        after: [],
      };
    }
    if (before === after) {
      return {
        before: [{ text: before, changed: false }],
        after: [{ text: after, changed: false }],
      };
    }

    const beforeChars = Array.from(before || '');
    const afterChars = Array.from(after || '');
    let start = 0;
    while (
      start < beforeChars.length &&
      start < afterChars.length &&
      beforeChars[start] === afterChars[start]
    ) {
      start += 1;
    }

    let beforeEnd = beforeChars.length - 1;
    let afterEnd = afterChars.length - 1;
    while (
      beforeEnd >= start &&
      afterEnd >= start &&
      beforeChars[beforeEnd] === afterChars[afterEnd]
    ) {
      beforeEnd -= 1;
      afterEnd -= 1;
    }

    return {
      before: compactDiffParts([
        { text: beforeChars.slice(0, start).join(''), changed: false },
        { text: beforeChars.slice(start, beforeEnd + 1).join(''), changed: true },
        { text: beforeChars.slice(beforeEnd + 1).join(''), changed: false },
      ]),
      after: compactDiffParts([
        { text: afterChars.slice(0, start).join(''), changed: false },
        { text: afterChars.slice(start, afterEnd + 1).join(''), changed: true },
        { text: afterChars.slice(afterEnd + 1).join(''), changed: false },
      ]),
    };
  }

  function compactDiffParts(parts) {
    return parts.filter((part) => part.text);
  }

  return {
    polishDialogVisible,
    polishLoading,
    polishOriginal,
    polishResult,
    polishRange,
    polishDiff,
    onPolish,
    requestPolishSelection,
    applyPolishResult,
  };
}
