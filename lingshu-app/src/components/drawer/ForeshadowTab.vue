<template>
  <div class="foreshadow-tab">
    <!-- 顶部工具栏 -->
    <div class="tab-header">
      <span class="tab-title">伏笔</span>
      <div class="tab-header-actions">
        <el-select
          v-model="statusFilter"
          size="small"
          placeholder="全部"
          style="width: 100px"
          @change="onFilterChange"
        >
          <el-option label="全部" value="" />
          <el-option label="待回收" value="pending" />
          <el-option label="已回收" value="resolved" />
          <el-option label="已废弃" value="abandoned" />
        </el-select>
        <el-button
          size="small"
          text
          type="primary"
          :loading="syncing"
          @click="onSync"
        >
          从分析同步
        </el-button>
        <el-button
          size="small"
          text
          type="primary"
          @click="onCreate"
        >
          + 新增
        </el-button>
      </div>
    </div>

    <!-- 列表 -->
    <div
      v-if="store.loading"
      class="foreshadow-loading"
    >
      <el-skeleton :rows="4" />
    </div>

    <div
      v-else-if="filteredItems.length"
      class="foreshadow-list"
    >
      <div
        v-for="item in filteredItems"
        :key="item.id"
        class="foreshadow-item"
        :class="{ 'foreshadow-item--expanded': expandedId === item.id }"
      >
        <!-- 折叠态：列表项 -->
        <div
          class="foreshadow-item-summary"
          @click="toggleExpand(item.id)"
        >
          <div class="foreshadow-item-main">
            <el-tag
              :type="statusTagType(item.status)"
              size="small"
              effect="plain"
            >
              {{ statusLabel(item.status) }}
            </el-tag>
            <el-tag
              :type="priorityTagType(item.priority)"
              size="small"
              effect="plain"
            >
              {{ priorityLabel(item.priority) }}
            </el-tag>
            <el-tag
              v-if="item.source === 'auto'"
              size="small"
              type="info"
              effect="plain"
            >
              自动
            </el-tag>
            <span class="foreshadow-item-text">{{ item.description }}</span>
          </div>
          <div class="foreshadow-item-meta">
            <span v-if="item.setup_chapter_title">埋设：{{ item.setup_chapter_title }}</span>
            <span v-if="item.payoff_chapter_title">回收：{{ item.payoff_chapter_title }}</span>
          </div>
        </div>

        <!-- 展开态：编辑表单 -->
        <div
          v-if="expandedId === item.id"
          class="foreshadow-item-edit"
        >
          <el-form
            label-position="top"
            size="small"
          >
            <el-form-item label="描述">
              <el-input
                v-model="editForm.description"
                type="textarea"
                :rows="3"
              />
            </el-form-item>
            <el-form-item label="状态">
              <el-radio-group v-model="editForm.status">
                <el-radio value="pending">待回收</el-radio>
                <el-radio value="resolved">已回收</el-radio>
                <el-radio value="abandoned">已废弃</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="优先级">
              <el-radio-group v-model="editForm.priority">
                <el-radio value="high">高</el-radio>
                <el-radio value="medium">中</el-radio>
                <el-radio value="low">低</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="埋设章节">
              <el-input
                v-model.number="editForm.setup_chapter_id"
                placeholder="章节 ID（可空）"
                clearable
              />
            </el-form-item>
            <el-form-item label="回收章节">
              <el-input
                v-model.number="editForm.payoff_chapter_id"
                placeholder="章节 ID（可空）"
                clearable
              />
            </el-form-item>
            <el-form-item label="回收说明">
              <el-input
                v-model="editForm.resolution_note"
                type="textarea"
                :rows="2"
                placeholder="伏笔回收的说明（可空）"
              />
            </el-form-item>
            <div class="foreshadow-item-actions">
              <el-button
                size="small"
                type="primary"
                :loading="saving"
                @click="onSave(item.id)"
              >
                保存
              </el-button>
              <el-button
                size="small"
                @click="expandedId = null"
              >
                取消
              </el-button>
              <el-popconfirm
                title="确定删除此伏笔？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm="onDelete(item.id)"
              >
                <template #reference>
                  <el-button
                    size="small"
                    type="danger"
                    text
                  >
                    删除
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </el-form>
        </div>
      </div>
    </div>

    <el-empty
      v-else
      description="暂无伏笔，点击「从分析同步」或「新增」"
      :image-size="60"
    />

    <!-- 新增弹窗 -->
    <el-dialog
      v-model="createDialogVisible"
      title="新增伏笔"
      width="500px"
    >
      <el-form
        label-position="top"
        size="small"
      >
        <el-form-item label="描述" required>
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="4"
            placeholder="描述这个伏笔的内容（必填）"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="createForm.status">
            <el-radio value="pending">待回收</el-radio>
            <el-radio value="resolved">已回收</el-radio>
            <el-radio value="abandoned">已废弃</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="优先级">
          <el-radio-group v-model="createForm.priority">
            <el-radio value="high">高</el-radio>
            <el-radio value="medium">中</el-radio>
            <el-radio value="low">低</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="creating"
          @click="onCreateSubmit"
        >
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import { useForeshadowStore } from '../../stores/foreshadow';

const bookStore = useBookStore();
const store = useForeshadowStore();

const bookId = computed(() => bookStore.currentBookId);
const statusFilter = ref('');
const expandedId = ref(null);
const saving = ref(false);
const syncing = ref(false);

// 新增弹窗状态
const createDialogVisible = ref(false);
const creating = ref(false);
const createForm = reactive({
  description: '',
  status: 'pending',
  priority: 'medium',
});

// 编辑表单
const editForm = reactive({
  description: '',
  status: 'pending',
  priority: 'medium',
  setup_chapter_id: null,
  payoff_chapter_id: null,
  resolution_note: '',
});

const filteredItems = computed(() => store.items);

watch(bookId, () => {
  store.load(bookId.value);
}, { immediate: true });

function onFilterChange() {
  store.load(bookId.value, { status: statusFilter.value || undefined });
}

function toggleExpand(id) {
  if (expandedId.value === id) {
    expandedId.value = null;
    return;
  }
  const item = store.items.find(it => it.id === id);
  if (!item) return;
  editForm.description = item.description;
  editForm.status = item.status;
  editForm.priority = item.priority;
  editForm.setup_chapter_id = item.setup_chapter_id;
  editForm.payoff_chapter_id = item.payoff_chapter_id;
  editForm.resolution_note = item.resolution_note;
  expandedId.value = id;
}

async function onSave(id) {
  if (!editForm.description.trim()) {
    ElMessage.warning('描述不能为空');
    return;
  }
  saving.value = true;
  try {
    await store.update(id, {
      description: editForm.description.trim(),
      status: editForm.status,
      priority: editForm.priority,
      setup_chapter_id: editForm.setup_chapter_id || null,
      payoff_chapter_id: editForm.payoff_chapter_id || null,
      resolution_note: editForm.resolution_note,
    });
    ElMessage.success('已保存');
    expandedId.value = null;
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败');
  } finally {
    saving.value = false;
  }
}

async function onDelete(id) {
  try {
    await store.remove(id);
    ElMessage.success('已删除');
    if (expandedId.value === id) expandedId.value = null;
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败');
  }
}

function onCreate() {
  createForm.description = '';
  createForm.status = 'pending';
  createForm.priority = 'medium';
  createDialogVisible.value = true;
}

async function onCreateSubmit() {
  if (!createForm.description.trim()) {
    ElMessage.warning('描述不能为空');
    return;
  }
  creating.value = true;
  try {
    await store.create(bookId.value, {
      description: createForm.description.trim(),
      status: createForm.status,
      priority: createForm.priority,
    });
    ElMessage.success('已创建');
    createDialogVisible.value = false;
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败');
  } finally {
    creating.value = false;
  }
}

async function onSync() {
  syncing.value = true;
  try {
    await store.syncFromAnalysis(bookId.value);
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '同步失败');
  } finally {
    syncing.value = false;
  }
}

function statusLabel(s) {
  return { pending: '待回收', resolved: '已回收', abandoned: '已废弃' }[s] || s;
}
function statusTagType(s) {
  return { pending: 'warning', resolved: 'success', abandoned: 'info' }[s] || '';
}
function priorityLabel(p) {
  return { high: '高', medium: '中', low: '低' }[p] || p;
}
function priorityTagType(p) {
  return { high: 'danger', medium: 'warning', low: 'info' }[p] || '';
}
</script>

<style scoped>
.foreshadow-tab {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px;
}
.tab-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.tab-title {
  font-size: 14px;
  font-weight: 600;
}
.tab-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.foreshadow-loading {
  padding: 12px;
}
.foreshadow-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.foreshadow-item {
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: var(--bg-primary);
  overflow: hidden;
}
.foreshadow-item--expanded {
  border-color: var(--el-color-primary-light-5);
}
.foreshadow-item-summary {
  padding: 8px 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.foreshadow-item-summary:hover {
  background: var(--bg-secondary);
}
.foreshadow-item-main {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.foreshadow-item-text {
  font-size: 13px;
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.foreshadow-item-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}
.foreshadow-item-edit {
  padding: 10px 12px;
  border-top: 1px solid var(--border-light);
  background: var(--bg-secondary);
}
.foreshadow-item-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
