<template>
  <div class="outline-editor">
    <div class="outline-toolbar">
      <span class="outline-label">{{ label }}</span>
    </div>

    <!-- 结构化显示层：选项用复选框，保存时同步到原 outline_text 字段 -->
    <div class="outline-body">
      <StructuredTemplateForm
        v-model="localOutlineData"
        :schema="outlineSchema"
        empty-text="暂无书籍级选项"
        @change="onChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue';
import StructuredTemplateForm from '../common/StructuredTemplateForm.vue';

const props = defineProps({
  outline: { type: String, default: '' },
  outlineData: { type: Object, default: () => ({}) },
  outlineSchema: { type: Array, default: () => [] },
  label: { type: String, default: '书籍大纲' },
});

const emit = defineEmits(['update:outline', 'update:outlineData', 'change']);

const localOutlineData = ref(clone(props.outlineData));

watch(() => props.outlineData, (val) => {
  localOutlineData.value = clone(val);
}, { deep: true });

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function onChange(value) {
  localOutlineData.value = clone(value);
  emit('update:outlineData', localOutlineData.value);
  emit('change');
}
</script>

<style scoped>
.outline-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

.outline-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  padding: 0 12px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.outline-label {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.outline-body {
  flex: 1;
  overflow: hidden;
}
</style>
