<template>
  <el-dialog
    v-model="visible"
    title="作品管理"
    width="620px"
    class="book-entry-dialog"
    :close-on-click-modal="false"
    @close="$emit('close')"
  >
    <div class="mode-switch">
      <el-segmented
        v-model="mode"
        :options="modeOptions"
        block
      />
    </div>

    <section
      v-if="mode === 'create'"
      class="entry-panel"
    >
      <div class="entry-heading">
        <h3>新建作品</h3>
        <p>创建后会自动选中作品，并进入大纲编辑。</p>
      </div>

      <el-form
        label-position="top"
        @submit.prevent
      >
        <el-form-item
          label="作品名称"
          required
        >
          <el-input
            v-model="createTitle"
            placeholder="输入作品名称"
            maxlength="80"
            show-word-limit
            autofocus
            @keydown.enter.prevent="createBook"
          />
        </el-form-item>
      </el-form>
    </section>

    <section
      v-else
      class="entry-panel"
    >
      <div class="entry-heading">
        <h3>导入作品</h3>
        <p>支持 TXT / Markdown / DOCX，导入时会自动识别分卷和章节。</p>
      </div>

      <el-radio-group
        v-model="importTarget"
        class="target-switch"
      >
        <el-radio-button value="new">
          导入为新作品
        </el-radio-button>
        <el-radio-button
          value="current"
          :disabled="!currentBookId"
        >
          追加到当前作品
        </el-radio-button>
      </el-radio-group>

      <div
        v-if="importTarget === 'current' && currentBookId"
        class="current-target"
      >
        当前作品：{{ currentBookTitle || `#${currentBookId}` }}
      </div>

      <el-steps
        :active="step"
        finish-status="success"
        align-center
        class="import-steps"
      >
        <el-step title="选择文件" />
        <el-step title="确认导入" />
        <el-step title="完成" />
      </el-steps>

      <div
        v-if="step === 0"
        class="import-step"
      >
        <el-upload
          ref="uploadRef"
          drag
          :auto-upload="false"
          :limit="1"
          accept=".txt,.md,.docx"
          :on-change="onFileChange"
          :on-remove="onFileRemove"
        >
          <el-icon class="el-icon--upload">
            <UploadFilled />
          </el-icon>
          <div class="el-upload__text">
            拖拽文件到此处或 <em>点击选择</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              最大 50MB，导入后会刷新左侧书籍框架。
            </div>
          </template>
        </el-upload>
      </div>

      <div
        v-if="step === 1"
        class="import-step"
      >
        <el-descriptions
          :column="2"
          border
          size="small"
        >
          <el-descriptions-item label="文件名">
            {{ fileInfo.name }}
          </el-descriptions-item>
          <el-descriptions-item label="大小">
            {{ formatSize(fileInfo.size) }}
          </el-descriptions-item>
          <el-descriptions-item label="导入方式">
            {{ importTarget === 'current' ? '追加到当前作品' : '创建新作品' }}
          </el-descriptions-item>
          <el-descriptions-item
            v-if="importTarget === 'current'"
            label="目标作品"
          >
            {{ currentBookTitle || `#${currentBookId}` }}
          </el-descriptions-item>
          <el-descriptions-item
            v-if="importTarget === 'new'"
            label="书名"
          >
            <el-input
              v-model="bookTitle"
              size="small"
              placeholder="留空则使用文件名"
            />
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div
        v-if="step === 2"
        class="import-step import-result"
      >
        <el-result
          v-if="importResult"
          icon="success"
          title="导入完成"
        >
          <template #sub-title>
            <p>
              {{ importResult.stats?.volume_count || 0 }} 卷 /
              {{ importResult.stats?.chapter_count || 0 }} 章 /
              {{ importResult.stats?.total_chars || 0 }} 字
            </p>
          </template>
        </el-result>
        <el-result
          v-else
          icon="error"
          title="导入失败"
        >
          <template #sub-title>
            <p>{{ importError }}</p>
          </template>
        </el-result>
      </div>
    </section>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onCancel">
          取消
        </el-button>

        <template v-if="mode === 'create'">
          <el-button
            type="primary"
            :loading="creating"
            @click="createBook"
          >
            创建作品
          </el-button>
        </template>

        <template v-else>
          <el-button
            v-if="step === 1"
            @click="step = 0"
          >
            上一步
          </el-button>
          <el-button
            v-if="step === 0"
            type="primary"
            :disabled="!selectedFile"
            @click="step = 1"
          >
            下一步
          </el-button>
          <el-button
            v-if="step === 1"
            type="primary"
            :loading="importing"
            @click="doImport"
          >
            {{ importing ? '导入中...' : '开始导入' }}
          </el-button>
          <el-button
            v-if="step === 2"
            type="primary"
            @click="onDone"
          >
            完成
          </el-button>
        </template>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { UploadFilled } from '@element-plus/icons-vue';
import api from '../../utils/api';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  initialMode: { type: String, default: 'create' },
  currentBookId: { type: [Number, null], default: null },
  currentBookTitle: { type: String, default: '' },
});

const emit = defineEmits(['update:modelValue', 'close', 'created', 'imported']);

const modeOptions = [
  { label: '新建作品', value: 'create' },
  { label: '导入作品', value: 'import' },
];

const visible = ref(props.modelValue);
const mode = ref(props.initialMode);
const createTitle = ref('');
const creating = ref(false);

const uploadRef = ref(null);
const step = ref(0);
const selectedFile = ref(null);
const fileInfo = ref({ name: '', size: 0 });
const bookTitle = ref('');
const importing = ref(false);
const importResult = ref(null);
const importError = ref('');
const importTarget = ref(props.currentBookId ? 'current' : 'new');

watch(() => props.modelValue, (v) => { visible.value = v; });
watch(visible, (v) => { emit('update:modelValue', v); });
watch(() => props.initialMode, (v) => {
  if (v === 'create' || v === 'import') mode.value = v;
});
watch(() => props.currentBookId, (bookId) => {
  if (!bookId && importTarget.value === 'current') importTarget.value = 'new';
});
watch(visible, (v) => {
  if (!v) return;
  mode.value = props.initialMode === 'import' ? 'import' : 'create';
  resetState();
});

function resetState() {
  createTitle.value = '';
  step.value = 0;
  selectedFile.value = null;
  fileInfo.value = { name: '', size: 0 };
  bookTitle.value = '';
  importResult.value = null;
  importError.value = '';
  importTarget.value = props.currentBookId ? 'current' : 'new';
  nextTick(() => uploadRef.value?.clearFiles?.());
}

async function createBook() {
  const title = createTitle.value.trim();
  if (!title) {
    ElMessage.warning('请输入作品名称');
    return;
  }

  creating.value = true;
  try {
    const { data } = await api.post('/workspace/books', { title });
    emit('created', data.item);
    ElMessage.success('作品已创建');
    visible.value = false;
    emit('close');
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '创建失败');
  } finally {
    creating.value = false;
  }
}

function onFileChange(file) {
  selectedFile.value = file.raw;
  fileInfo.value = { name: file.name, size: file.size || 0 };
}

function onFileRemove() {
  selectedFile.value = null;
  fileInfo.value = { name: '', size: 0 };
}

function formatSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB'];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return `${size.toFixed(1)} ${units[i]}`;
}

async function doImport() {
  if (!selectedFile.value) return;
  importing.value = true;
  importError.value = '';

  try {
    const form = new FormData();
    form.append('file', selectedFile.value);

    let url = '/workspace/import-file';
    if (importTarget.value === 'current' && props.currentBookId) {
      url = `/workspace/books/${props.currentBookId}/import-file`;
    } else if (bookTitle.value.trim()) {
      url += `?title=${encodeURIComponent(bookTitle.value.trim())}`;
    }

    // 读取导入分卷开关
    const volumeEnabled = localStorage.getItem('lingshu:import:volumeEnabled');
    const sep = url.includes('?') ? '&' : '?';
    url += `${sep}skip_volumes=${volumeEnabled === 'false'}`;

    const { data } = await api.post(url, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });

    importResult.value = data;
    step.value = 2;
    emit('imported', data);
  } catch (e) {
    importError.value = e.response?.data?.detail || e.message || '导入失败';
    step.value = 2;
    importResult.value = null;
  } finally {
    importing.value = false;
  }
}

function onCancel() {
  visible.value = false;
  emit('close');
}

function onDone() {
  visible.value = false;
  emit('close');
}
</script>

<style scoped>
.mode-switch {
  margin-bottom: 18px;
}

.entry-panel {
  min-height: 308px;
}

.entry-heading {
  margin-bottom: 16px;
}

.entry-heading h3 {
  margin: 0;
  font-size: 18px;
  line-height: 1.3;
  color: var(--text-primary);
  letter-spacing: 0;
}

.entry-heading p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.target-switch {
  margin-bottom: 10px;
}

.current-target {
  margin-bottom: 14px;
  padding: 8px 10px;
  border-radius: 7px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-light);
  font-size: 13px;
}

.import-steps {
  margin: 14px 0 20px;
}

.import-step {
  min-height: 150px;
}

.import-result {
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
