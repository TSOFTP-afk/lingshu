/**
 * 自动保存 composable — 防抖保存 + 脏状态追踪
 *
 * 对应 Qt 模块: app_editor.py → _on_editor_changed / word_timer
 */
import { ref, onUnmounted } from 'vue';

export function useAutoSave(saveFn, options = {}) {
  const { interval = 3000, enabled = true } = options;

  const dirty = ref(false);
  const saving = ref(false);
  const lastSaved = ref(null);
  let timer = null;

  function markDirty() {
    dirty.value = true;
  }

  function markClean() {
    dirty.value = false;
    lastSaved.value = new Date();
  }

  async function save() {
    if (!dirty.value || saving.value) return;
    saving.value = true;
    try {
      await saveFn();
      markClean();
    } finally {
      saving.value = false;
    }
  }

  // 防抖自动保存
  function scheduleAutoSave() {
    if (!enabled || !dirty.value) return;
    clearTimeout(timer);
    timer = setTimeout(() => save(), interval);
  }

  // 关闭时停止
  onUnmounted(() => {
    clearTimeout(timer);
  });

  return { dirty, saving, lastSaved, markDirty, markClean, save, scheduleAutoSave };
}


/**
 * 字数统计 composable
 *
 * 对应 Qt 模块: app_editor.py → _update_word_count / count_text_characters
 */
import { computed } from 'vue';

export function useWordCount(textRef) {
  const wordCount = computed(() => {
    const text = textRef.value || '';
    return text.replace(/\s/g, '').length;
  });

  return { wordCount };
}
