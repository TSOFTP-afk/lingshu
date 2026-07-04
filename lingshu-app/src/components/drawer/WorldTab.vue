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
import { ref, computed, watch, onMounted } from 'vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import { useWorldStore } from '../../stores/world';
import { useEventBus } from '../../composables/useEventBus';
import api from '../../utils/api';
import StructuredTemplateForm from '../common/StructuredTemplateForm.vue';

const bookStore = useBookStore();
const worldStore = useWorldStore();
const bookId = computed(() => bookStore.currentBookId);
const { emit } = useEventBus();

const worldText = ref('');
const worldData = ref({});
const worldSchema = ref([]);
const saving = ref(false);
let _saveTimer = null;

// store 数据变化时（首次加载、WS 写回等）同步到本地编辑状态
watch(() => worldStore.worldText, (v) => { worldText.value = v || ''; });
watch(() => worldStore.worldData, (v) => { worldData.value = v || {}; });
watch(() => worldStore.worldSchema, (v) => { worldSchema.value = v || []; });

async function loadWorld() {
  if (!bookId.value) {
    worldStore.setWorld({ worldText: '', worldData: {}, worldSchema: [] });
    return;
  }
  await worldStore.fetchWorld(bookId.value);
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
    const newWorldText = data.world_text || '';
    const newWorldData = data.world_data || worldData.value || {};
    const newWorldSchema = data.world_schema || worldSchema.value || [];
    // 同步本地编辑状态
    worldText.value = newWorldText;
    worldData.value = newWorldData;
    worldSchema.value = newWorldSchema;
    // 同步 world store，通知其他依赖世界卡的组件
    worldStore.setWorld({
      worldText: newWorldText,
      worldData: newWorldData,
      worldSchema: newWorldSchema,
    });
    // 通知其他组件刷新
    emit('lingshu:world-updated', { bookId: bookId.value, source: 'manual_save' });
    ElMessage.success('世界观已保存');
  } catch { ElMessage.error('保存失败'); }
  finally { saving.value = false; }
}

watch(bookId, loadWorld);
onMounted(() => {
  loadWorld();
});
</script>

<style scoped>
.world-tab { display: flex; flex-direction: column; height: calc(100vh - 130px); padding: 4px 0; }
.tab-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; flex-shrink: 0; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.world-editor { flex: 1; overflow: hidden; }
.world-actions { flex-shrink: 0; margin-top: 8px; padding-top: 8px; }
</style>
