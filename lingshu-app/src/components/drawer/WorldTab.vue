<template>
  <div class="world-tab">
    <div class="tab-header">
      <span class="tab-title">世界观</span>
    </div>

    <!-- 结构化显示层：选项用复选框，保存时同步到原 world_text 字段 -->
    <div class="world-editor">
      <StructuredTemplateForm
        v-model="worldData"
        :schema="worldSchema"
        empty-text="暂无世界观选项"
        @change="onChange"
      />
    </div>

    <div class="world-actions">
      <el-button
        type="primary"
        size="small"
        :loading="saving"
        :disabled="!bookId"
        @click="onSave"
      >
        保存
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import { useEventBus } from '../../composables/useEventBus';
import api from '../../utils/api';
import StructuredTemplateForm from '../common/StructuredTemplateForm.vue';

const bookStore = useBookStore();
const bookId = computed(() => bookStore.currentBookId);
const { on, off } = useEventBus();

const worldText = ref('');
const worldData = ref({});
const worldSchema = ref([]);
const saving = ref(false);
let _saveTimer = null;

async function loadWorld() {
  if (!bookId.value) {
    worldText.value = '';
    worldData.value = {};
    worldSchema.value = [];
    return;
  }
  try {
    const { data } = await api.get(`/workspace/books/${bookId.value}/world`);
    worldText.value = data.world_text || '';
    worldData.value = data.world_data || {};
    worldSchema.value = data.world_schema || [];
  } catch {
    worldText.value = '';
    worldData.value = {};
    worldSchema.value = [];
  }
}

function onChange() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(onSave, 5000);
}

async function onSave() {
  if (!bookId.value) return;
  saving.value = true;
  try {
    const { data } = await api.put(`/workspace/books/${bookId.value}/world`, {
      world_data: worldData.value || {},
    });
    worldText.value = data.world_text || '';
    worldData.value = data.world_data || worldData.value || {};
    worldSchema.value = data.world_schema || worldSchema.value || [];
    ElMessage.success('世界观已保存');
  } catch { ElMessage.error('保存失败'); }
  finally { saving.value = false; }
}

watch(bookId, loadWorld);
onMounted(() => {
  loadWorld();
  // 监听写回完成事件，自动刷新世界观
  on('lingshu:world-updated', handleWritebackCompleted);
  on('lingshu:writeback-completed', handleWritebackCompleted);
});
onUnmounted(() => {
  off('lingshu:world-updated', handleWritebackCompleted);
  off('lingshu:writeback-completed', handleWritebackCompleted);
});

function handleWritebackCompleted(payload) {
  // 仅当事件涉及当前书籍时刷新
  if (!payload || !bookId.value) return;
  if (payload.bookId && Number(payload.bookId) !== Number(bookId.value)) return;
  // 写回目标是 world_entry 或批量写回时刷新
  if (payload.writebackTarget && payload.writebackTarget !== 'world_entry') return;
  loadWorld();
}
</script>

<style scoped>
.world-tab { display: flex; flex-direction: column; height: calc(100vh - 130px); padding: 4px 0; }
.tab-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; flex-shrink: 0; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.world-editor { flex: 1; overflow: hidden; }
.world-actions { flex-shrink: 0; margin-top: 8px; padding-top: 8px; }
</style>
