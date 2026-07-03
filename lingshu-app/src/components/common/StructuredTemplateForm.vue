<template>
  <div class="structured-template-form">
    <el-empty
      v-if="!schema.length"
      :description="emptyText"
      :image-size="54"
    />

    <template v-else>
      <section
        v-for="section in schema"
        :key="section.id || section.title"
        class="template-section"
      >
        <header class="section-header">
          <span>{{ section.title || '未命名分组' }}</span>
        </header>

        <div class="section-fields">
          <template
            v-for="item in itemsForSection(section)"
            :key="item.id"
          >
            <div
              v-if="item.type === 'checkbox'"
              class="field field--checkbox"
            >
              <el-checkbox
                :model-value="fieldFor(item).checked"
                @change="checked => setChecked(item, checked)"
              >
                {{ item.label }}
              </el-checkbox>
            </div>

            <div
              v-else-if="item.type === 'checkbox_text'"
              class="field field--checkbox-text"
            >
              <el-checkbox
                :model-value="fieldFor(item).checked"
                @change="checked => setChecked(item, checked)"
              >
                {{ item.label }}
              </el-checkbox>
              <el-input
                :model-value="fieldFor(item).value"
                size="small"
                :disabled="!fieldFor(item).checked"
                placeholder="自定义"
                @input="value => setValue(item, value)"
              />
            </div>

            <div
              v-else-if="item.type === 'select'"
              class="field field--options"
            >
              <div class="field-label">
                {{ item.label }}
              </div>
              <div class="option-grid">
                <el-checkbox
                  v-for="option in normalizedOptions(item)"
                  :key="option.value"
                  :model-value="fieldFor(item).value === option.value"
                  @change="checked => setSelect(item, option.value, checked)"
                >
                  {{ option.label }}
                </el-checkbox>
              </div>
            </div>

            <el-form-item
              v-else-if="item.type === 'multiline'"
              class="field field--wide"
              :label="item.label"
            >
              <el-input
                :model-value="fieldFor(item).value"
                type="textarea"
                :rows="textareaRows(item)"
                :placeholder="item.placeholder || ''"
                resize="vertical"
                @input="value => setValue(item, value)"
              />
            </el-form-item>

            <el-form-item
              v-else
              class="field"
              :label="item.label"
            >
              <el-input
                :model-value="fieldFor(item).value"
                size="small"
                @input="value => setValue(item, value)"
              />
            </el-form-item>
          </template>
        </div>
      </section>

      <section
        v-if="hasSupplementsField()"
        class="template-section template-section--supplements"
      >
        <header class="section-header section-header--with-action">
          <span>补充设定</span>
          <el-button
            size="small"
            text
            type="primary"
            :icon="Plus"
            @click="addSupplement"
          >
            添加
          </el-button>
        </header>

        <div
          v-if="form.supplements.length"
          class="supplements-list"
        >
          <article
            v-for="(supplement, index) in form.supplements"
            :key="supplement.uid || index"
            class="supplement-item"
          >
            <div class="supplement-title-row">
              <el-input
                :model-value="supplement.title || defaultSupplementTitle(index)"
                size="small"
                :placeholder="defaultSupplementTitle(index)"
                @input="value => setSupplementTitle(index, value)"
              />
              <el-button
                size="small"
                text
                type="danger"
                :icon="Delete"
                @click="removeSupplement(index)"
              />
            </div>
            <el-input
              :model-value="supplement.content"
              type="textarea"
              :rows="4"
              :placeholder="defaultSupplementTitle(index)"
              resize="vertical"
              @input="value => setSupplementContent(index, value)"
            />
          </article>
        </div>

        <el-button
          v-else
          class="supplement-empty-action"
          size="small"
          type="primary"
          plain
          :icon="Plus"
          @click="addSupplement"
        >
          添加补充设定
        </el-button>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue';
import { Delete, Plus } from '@element-plus/icons-vue';

const props = defineProps({
  schema: { type: Array, default: () => [] },
  modelValue: { type: Object, default: () => ({}) },
  emptyText: { type: String, default: '暂无可编辑选项' },
});

const emit = defineEmits(['update:modelValue', 'change']);

const form = ref(normalizeForm(props.modelValue, props.schema));

watch(
  () => [props.modelValue, props.schema],
  () => {
    form.value = normalizeForm(props.modelValue, props.schema);
  },
  { deep: true },
);

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function schemaItems(schema) {
  return (schema || []).flatMap(section => Array.isArray(section.items) ? section.items : []);
}

function isSupplementsField(item) {
  return String(item?.id || '') === 'supplemental_settings';
}

function itemsForSection(section) {
  return (Array.isArray(section?.items) ? section.items : []).filter(item => !isSupplementsField(item));
}

function hasSupplementsFieldInSchema(schema) {
  return schemaItems(schema).some(isSupplementsField);
}

function hasSupplementsField() {
  return hasSupplementsFieldInSchema(props.schema);
}

function defaultField(item) {
  const type = String(item?.type || 'text');
  if (type === 'checkbox') return { checked: false };
  if (type === 'checkbox_text') return { checked: false, value: '' };
  return { value: '' };
}

function normalizeForm(value, schema) {
  const next = clone(value);
  next.fields = next.fields && typeof next.fields === 'object' ? next.fields : {};
  for (const item of schemaItems(schema)) {
    const id = String(item.id || '');
    if (!id) continue;
    const current = next.fields[id] && typeof next.fields[id] === 'object' ? next.fields[id] : {};
    next.fields[id] = { ...defaultField(item), ...current };
  }
  if (!Array.isArray(next.supplements)) next.supplements = [];
  next.supplements = next.supplements
    .filter(item => item && typeof item === 'object')
    .map((item, index) => ({
      uid: item.uid || `supplement-${Date.now()}-${index}`,
      title: String(item.title || defaultSupplementTitle(index)),
      content: String(item.content || ''),
    }));
  if (hasSupplementsFieldInSchema(schema)) {
    const legacyContent = String(next.fields?.supplemental_settings?.value || '').trim();
    if (legacyContent && !next.supplements.some(item => String(item.content || '').trim() === legacyContent)) {
      next.supplements.unshift({
        uid: `supplement-${Date.now()}-legacy`,
        title: defaultSupplementTitle(0),
        content: legacyContent,
      });
    }
    if (next.fields?.supplemental_settings) {
      next.fields.supplemental_settings.value = '';
    }
  }
  return next;
}

function fieldFor(item) {
  const id = String(item.id || '');
  if (!form.value.fields) form.value.fields = {};
  if (!form.value.fields[id]) form.value.fields[id] = defaultField(item);
  return form.value.fields[id];
}

function emitForm() {
  const next = clone(form.value);
  emit('update:modelValue', next);
  emit('change', next);
}

function setChecked(item, checked) {
  fieldFor(item).checked = Boolean(checked);
  emitForm();
}

function setValue(item, value) {
  fieldFor(item).value = value;
  emitForm();
}

function setSelect(item, value, checked) {
  fieldFor(item).value = checked ? value : '';
  emitForm();
}

function defaultSupplementTitle(index) {
  return `补充设定 ${Number(index) + 1}`;
}

function ensureSupplements() {
  if (!Array.isArray(form.value.supplements)) form.value.supplements = [];
}

function addSupplement() {
  ensureSupplements();
  const index = form.value.supplements.length;
  form.value.supplements.push({
    uid: `supplement-${Date.now()}-${index}`,
    title: defaultSupplementTitle(index),
    content: '',
  });
  emitForm();
}

function setSupplementTitle(index, value) {
  ensureSupplements();
  const supplement = form.value.supplements[index];
  if (!supplement) return;
  supplement.title = value || defaultSupplementTitle(index);
  emitForm();
}

function setSupplementContent(index, value) {
  ensureSupplements();
  const supplement = form.value.supplements[index];
  if (!supplement) return;
  supplement.content = value;
  emitForm();
}

function removeSupplement(index) {
  ensureSupplements();
  form.value.supplements.splice(index, 1);
  form.value.supplements.forEach((supplement, idx) => {
    if (!String(supplement.title || '').trim()) {
      supplement.title = defaultSupplementTitle(idx);
    }
  });
  emitForm();
}

function normalizedOptions(item) {
  return (item.options || []).map((option) => {
    if (option && typeof option === 'object') {
      return {
        value: String(option.value ?? option.id ?? option.label ?? ''),
        label: String(option.label ?? option.name ?? option.value ?? ''),
      };
    }
    return { value: String(option), label: String(option) };
  }).filter(option => option.value || option.label);
}

function textareaRows(item) {
  const lineCount = String(item.placeholder || '').split('\n').length;
  return Math.min(10, Math.max(4, lineCount));
}
</script>

<style scoped>
.structured-template-form {
  height: 100%;
  overflow: auto;
  padding: 12px;
  background: var(--bg-primary);
}

.template-section {
  padding: 10px 0 12px;
  border-bottom: 1px solid var(--border-light);
}

.template-section:first-of-type {
  padding-top: 0;
}

.template-section:last-of-type {
  border-bottom: none;
}

.section-header {
  display: flex;
  align-items: center;
  min-height: 24px;
  margin-bottom: 8px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
}

.section-header--with-action {
  justify-content: space-between;
  gap: 8px;
}

.section-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
}

.field {
  min-width: 0;
}

.field--wide,
.field--options {
  grid-column: 1 / -1;
}

.field--checkbox {
  min-height: 28px;
  display: flex;
  align-items: center;
}

.field--checkbox-text {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: max-content minmax(120px, 1fr);
  align-items: center;
  gap: 8px;
}

.field-label {
  margin-bottom: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.option-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
  gap: 4px 10px;
  padding: 8px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
}

.template-section--supplements {
  padding-top: 12px;
}

.supplements-list {
  display: grid;
  gap: 10px;
}

.supplement-item {
  display: grid;
  gap: 6px;
  padding: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
}

.supplement-title-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 32px;
  align-items: center;
  gap: 6px;
}

.supplement-empty-action {
  width: 100%;
}

.structured-template-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.structured-template-form :deep(.el-form-item__label) {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.3;
  padding-bottom: 4px;
}

.structured-template-form :deep(.el-checkbox) {
  min-width: 0;
  height: auto;
  margin-right: 0;
  white-space: normal;
}

.structured-template-form :deep(.el-checkbox__label) {
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

@media (max-width: 820px) {
  .section-fields {
    grid-template-columns: 1fr;
  }
}
</style>
