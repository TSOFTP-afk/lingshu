<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    fullscreen
    class="chapter-edit-dialog"
    :close-on-click-modal="false"
    :before-close="handleBeforeClose"
    append-to-body
    destroy-on-close
  >
    <template #header>
      <div class="dialog-header">
        <span class="dialog-title">{{ dialogTitle }}</span>
        <el-tag
          v-if="dirty"
          type="warning"
          size="small"
        >
          未保存
        </el-tag>
        <el-tag
          v-else
          type="success"
          size="small"
        >
          已保存
        </el-tag>
        <span class="dialog-word-count">{{ wordCount }} 字</span>
      </div>
    </template>

    <div class="dialog-body">
      <ContentEditor
        :key="`edit-${chapterId}`"
        ref="editorRef"
        :chapter-id="chapterId"
        :content="content"
        :title="title"
        :dirty="dirty"
        :show-actionbar="false"
        :readonly="false"
        :ai-probability="aiProbability"
        :ai-probability-level="aiProbabilityLevel"
        @update:content="$emit('update:content', $event)"
        @change="$emit('change', $event)"
        @save="$emit('save')"
        @revert="$emit('revert')"
        @detect-ai="$emit('detect-ai')"
      />
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button
          :disabled="!dirty"
          @click="$emit('revert')"
        >
          回退
        </el-button>
        <el-button
          type="primary"
          :disabled="!dirty"
          @click="onSave"
        >
          保存
        </el-button>
        <el-button @click="handleClose">
          关闭
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import ContentEditor from './ContentEditor.vue';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  chapterId: { type: [Number, String, null], default: null },
  content: { type: String, default: '' },
  title: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  aiProbability: { type: Number, default: 0 },
  aiProbabilityLevel: { type: String, default: 'none' },
});

const emit = defineEmits([
  'update:modelValue',
  'update:content',
  'change',
  'save',
  'revert',
  'detect-ai',
]);

const editorRef = ref(null);

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
});

const dialogTitle = computed(() => `编辑 · ${props.title || '未命名章节'}`);

const wordCount = computed(() => {
  const text = props.content || '';
  return text.replace(/\s/g, '').length;
});

function onSave() {
  emit('save');
}

function handleClose() {
  if (props.dirty) {
    ElMessageBox.confirm('当前章节有未保存的修改，确定关闭？', '提示', {
      confirmButtonText: '关闭且不保存',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
      .then(() => {
        visible.value = false;
      })
      .catch(() => {});
    return;
  }
  visible.value = false;
}

function handleBeforeClose(done) {
  if (props.dirty) {
    ElMessageBox.confirm('当前章节有未保存的修改，确定关闭？', '提示', {
      confirmButtonText: '关闭且不保存',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
      .then(() => done())
      .catch(() => {});
    return;
  }
  done();
}

defineExpose({
  editorRef,
});
</script>

<style scoped>
.dialog-header {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 100%;
}

.dialog-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  max-width: 60vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dialog-word-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-secondary);
}

.dialog-body {
  height: calc(100vh - 110px);
  overflow: hidden;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

:deep(.chapter-edit-dialog .el-dialog__body) {
  padding: 0;
}

:deep(.chapter-edit-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
}

:deep(.chapter-edit-dialog .el-dialog__footer) {
  padding: 10px 20px;
  border-top: 1px solid var(--border-color);
}
</style>
