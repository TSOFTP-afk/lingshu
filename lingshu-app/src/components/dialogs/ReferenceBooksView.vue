<template>
  <el-dialog
    v-model="visible"
    title="参考书库"
    width="940px"
    class="reference-dialog"
    @open="loadData"
    @close="$emit('close')"
  >
    <div class="reference-shell">
      <section class="reference-toolbar">
        <el-upload
          ref="uploadRef"
          :auto-upload="false"
          :limit="1"
          accept=".txt,.md,.markdown,.docx"
          :show-file-list="false"
          :on-change="onFileChange"
        >
          <el-button
            type="primary"
            :icon="Upload"
          >
            导入参考书
          </el-button>
        </el-upload>
        <el-input
          v-model="importForm.title"
          placeholder="参考书标题，留空使用文件名"
        />
        <el-select
          v-model="importForm.role"
          class="role-select"
        >
          <el-option
            v-for="role in roleOptions"
            :key="role.value"
            :label="role.label"
            :value="role.value"
          />
        </el-select>
        <el-button
          :loading="importing"
          :disabled="!selectedFile"
          @click="importReference"
        >
          {{ bookId ? '导入并绑定' : '仅导入' }}
        </el-button>
        <el-button
          :icon="Refresh"
          @click="loadData"
        >
          刷新
        </el-button>
      </section>

      <section class="reference-bind">
        <el-select
          v-model="bindSourceId"
          filterable
          placeholder="绑定已有参考书到当前作品"
          :disabled="!bookId"
        >
          <el-option
            v-for="item in bindableReferences"
            :key="item.id"
            :label="item.title"
            :value="item.id"
          />
        </el-select>
        <el-select
          v-model="bindRole"
          class="role-select"
          :disabled="!bookId"
        >
          <el-option
            v-for="role in roleOptions"
            :key="role.value"
            :label="role.label"
            :value="role.value"
          />
        </el-select>
        <el-button
          :disabled="!bookId || !bindSourceId"
          @click="bindReference"
        >
          绑定
        </el-button>
        <span
          v-if="!bookId"
          class="hint"
        >选择作品后可绑定参考书并注入 AI 上下文。</span>
      </section>

      <div class="reference-grid">
        <section class="reference-list">
          <el-table
            v-loading="loading"
            :data="displayRows"
            size="small"
            height="360"
            highlight-current-row
            @row-click="selectReference"
          >
            <el-table-column
              label="名称"
              min-width="150"
            >
              <template #default="{ row }">
                {{ referenceTitle(row) }}
              </template>
            </el-table-column>
            <el-table-column
              label="用途"
              width="132"
            >
              <template #default="{ row }">
                <el-select
                  v-if="bookId && row.source_id"
                  v-model="row.role"
                  size="small"
                  @change="value => updateReference(row, { role: value })"
                >
                  <el-option
                    v-for="role in roleOptions"
                    :key="role.value"
                    :label="role.label"
                    :value="role.value"
                  />
                </el-select>
                <el-tag
                  v-else
                  size="small"
                  effect="plain"
                >
                  全局
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column
              label="启用"
              width="70"
            >
              <template #default="{ row }">
                <el-switch
                  v-if="bookId && row.source_id"
                  v-model="row.enabledBool"
                  size="small"
                  @change="value => updateReference(row, { enabled: value })"
                />
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column
              label="操作"
              width="78"
            >
              <template #default="{ row }">
                <el-button
                  v-if="bookId && row.source_id"
                  size="small"
                  text
                  type="danger"
                  @click.stop="unbindReference(row)"
                >
                  解绑
                </el-button>
                <el-button
                  v-else-if="bookId"
                  size="small"
                  text
                  @click.stop="bindSpecific(row)"
                >
                  绑定
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section class="reference-detail">
          <div class="detail-title">
            {{ selectedRef ? referenceTitle(selectedRef) : '参考书详情' }}
          </div>
          <div
            v-if="selectedRef"
            class="detail-meta"
          >
            <el-tag
              size="small"
              effect="plain"
            >
              {{ roleLabel(selectedRef.role) }}
            </el-tag>
            <span>{{ selectedRef.source_author || selectedRef.author || '未填写作者' }}</span>
          </div>

          <el-tabs
            v-model="detailTab"
            class="detail-tabs"
          >
            <el-tab-pane
              label="上下文"
              name="context"
            >
              <pre class="text-preview">{{ context || '当前作品暂无启用参考书上下文。' }}</pre>
            </el-tab-pane>
            <el-tab-pane
              label="摘要"
              name="summary"
            >
              <pre class="text-preview">{{ selectedSummary }}</pre>
            </el-tab-pane>
            <el-tab-pane
              label="分段"
              name="segments"
            >
              <div
                v-if="segments.length"
                class="segment-list"
              >
                <article
                  v-for="segment in segments"
                  :key="segment.id"
                  class="segment-item"
                >
                  <strong>{{ segment.title || `第 ${segment.segment_index} 段` }}</strong>
                  <p>{{ segment.summary || segment.content }}</p>
                </article>
              </div>
              <el-empty
                v-else
                description="暂无分段"
                :image-size="60"
              />
            </el-tab-pane>
          </el-tabs>
        </section>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">
        关闭
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Refresh, Upload } from '@element-plus/icons-vue';
import { useBookStore } from '../../stores/book';
import api from '../../utils/api';

const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'close']);

const visible = ref(props.modelValue);
watch(() => props.modelValue, v => { visible.value = v; });
watch(visible, v => emit('update:modelValue', v));

const bookStore = useBookStore();
const bookId = computed(() => bookStore.currentBookId);

const roleOptions = [
  { value: 'style_reference', label: '文风参考' },
  { value: 'canon_reference', label: '设定参考' },
  { value: 'structure_reference', label: '结构参考' },
  { value: 'avoid_reference', label: '规避参考' },
];

const loading = ref(false);
const importing = ref(false);
const refs = ref([]);
const allRefs = ref([]);
const context = ref('');
const selectedRef = ref(null);
const segments = ref([]);
const detailTab = ref('context');
const uploadRef = ref(null);
const selectedFile = ref(null);
const bindSourceId = ref(null);
const bindRole = ref('style_reference');
const importForm = ref({ title: '', role: 'style_reference' });

const displayRows = computed(() => {
  if (bookId.value) return refs.value;
  return allRefs.value;
});

const boundSourceIds = computed(() => new Set(refs.value.map(item => Number(item.source_id))));
const bindableReferences = computed(() =>
  allRefs.value.filter(item => !boundSourceIds.value.has(Number(item.id))),
);

const selectedSummary = computed(() => {
  if (!selectedRef.value) return '请选择一条参考书。';
  return selectedRef.value.summary || selectedRef.value.notes || selectedRef.value.rights_note || '暂无摘要。';
});

watch(bookId, () => {
  if (visible.value) loadData();
});

async function loadData() {
  loading.value = true;
  try {
    const [{ data: allData }, bookData] = await Promise.all([
      api.get('/workspace/references'),
      bookId.value ? api.get(`/workspace/books/${bookId.value}/references`) : Promise.resolve({ data: { items: [], context: '' } }),
    ]);
    allRefs.value = (allData.items || []).map(item => ({ ...item }));
    refs.value = (bookData.data.items || []).map(item => ({
      ...item,
      enabledBool: Boolean(item.enabled),
    }));
    context.value = bookData.data.context || '';
    selectedRef.value = displayRows.value[0] || null;
    await loadSegmentsForSelected();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '加载参考书失败');
  } finally {
    loading.value = false;
  }
}

function onFileChange(file) {
  selectedFile.value = file.raw;
  if (!importForm.value.title) {
    importForm.value.title = (file.name || '').replace(/\.[^.]+$/, '');
  }
}

async function importReference() {
  if (!selectedFile.value) return;
  importing.value = true;
  try {
    const form = new FormData();
    form.append('file', selectedFile.value);
    if (bookId.value) form.append('book_id', String(bookId.value));
    form.append('title', importForm.value.title || '');
    form.append('role', importForm.value.role);
    const { data } = await api.post('/workspace/references/import-file', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });
    ElMessage.success(bookId.value ? '参考书已导入并绑定' : '参考书已导入');
    uploadRef.value?.clearFiles?.();
    selectedFile.value = null;
    importForm.value.title = '';
    await loadData();
    selectedRef.value = refs.value.find(item => Number(item.source_id) === Number(data.source_id)) || selectedRef.value;
    await loadSegmentsForSelected();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '导入参考书失败');
  } finally {
    importing.value = false;
  }
}

async function bindReference() {
  if (!bookId.value || !bindSourceId.value) return;
  await bindSpecific({ id: bindSourceId.value }, bindRole.value);
  bindSourceId.value = null;
}

async function bindSpecific(row, role = bindRole.value) {
  if (!bookId.value) return;
  try {
    await api.post(`/workspace/books/${bookId.value}/references/${row.id}`, { role });
    ElMessage.success('参考书已绑定');
    await loadData();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '绑定失败');
  }
}

async function updateReference(row, patch) {
  if (!bookId.value || !row.source_id) return;
  try {
    await api.patch(`/workspace/books/${bookId.value}/references/${row.source_id}`, patch);
    await loadData();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '更新失败');
  }
}

async function unbindReference(row) {
  if (!bookId.value || !row.source_id) return;
  try {
    await ElMessageBox.confirm('确定从当前作品解绑这本参考书吗？', '解绑参考书', { type: 'warning' });
    await api.delete(`/workspace/books/${bookId.value}/references/${row.source_id}`);
    ElMessage.success('已解绑');
    await loadData();
  } catch {
    // cancelled
  }
}

async function selectReference(row) {
  selectedRef.value = row;
  detailTab.value = 'summary';
  await loadSegmentsForSelected();
}

async function loadSegmentsForSelected() {
  segments.value = [];
  if (!bookId.value || !selectedRef.value?.source_id) return;
  try {
    const { data } = await api.get(`/workspace/books/${bookId.value}/references/${selectedRef.value.source_id}/segments`);
    segments.value = data.items || [];
  } catch {
    segments.value = [];
  }
}

function referenceTitle(row) {
  return row?.source_title || row?.title || '未命名参考书';
}

function roleLabel(role) {
  return roleOptions.find(item => item.value === role)?.label || '参考书';
}
</script>

<style scoped>
.reference-shell {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reference-toolbar,
.reference-bind {
  display: grid;
  grid-template-columns: auto minmax(180px, 1fr) 132px auto auto;
  align-items: center;
  gap: 8px;
}

.reference-bind {
  grid-template-columns: minmax(240px, 1fr) 132px auto minmax(120px, 1fr);
}

.role-select {
  width: 132px;
}

.hint {
  color: var(--text-placeholder);
  font-size: 12px;
}

.reference-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(280px, 0.92fr);
  gap: 12px;
  min-height: 380px;
}

.reference-list,
.reference-detail {
  min-width: 0;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  overflow: hidden;
}

.reference-detail {
  padding: 12px;
}

.detail-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}

.detail-tabs {
  margin-top: 8px;
}

.text-preview {
  height: 246px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 10px;
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
  color: var(--text-regular);
  font-size: 12px;
  line-height: 1.65;
  font-family: inherit;
}

.segment-list {
  height: 246px;
  overflow: auto;
}

.segment-item {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-light);
}

.segment-item strong {
  font-size: 12px;
  color: var(--text-primary);
}

.segment-item p {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}
</style>
