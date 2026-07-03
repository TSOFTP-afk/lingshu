<template>
  <div class="library-panel">
    <div class="panel-header">
      <div class="panel-heading">
        <span class="panel-title">书籍框架</span>
        <span class="panel-count">{{ books.length }} 本 / {{ volumeCount }} 卷 / {{ chapterCount }} 章</span>
      </div>
      <div class="header-actions">
        <el-tooltip
          content="新建作品"
          placement="bottom"
        >
          <el-button
            class="header-action"
            type="primary"
            :icon="CirclePlus"
            @click="openBookEntry"
          />
        </el-tooltip>
        <el-tooltip
          content="导入文稿"
          placement="bottom"
        >
          <el-button
            class="header-action"
            :icon="Upload"
            @click="openImportEntry"
          />
        </el-tooltip>
        <el-tooltip
          content="新建分卷"
          placement="bottom"
        >
          <el-button
            class="header-action"
            :icon="FolderAdd"
            :disabled="!currentBookId"
            @click="$emit('create-volume', currentBookId)"
          />
        </el-tooltip>
        <el-tooltip
          content="新建章节"
          placement="bottom"
        >
          <el-button
            class="header-action"
            :icon="DocumentAdd"
            :disabled="!currentBookId"
            @click="$emit('create-chapter', { bookId: currentBookId })"
          />
        </el-tooltip>
      </div>
    </div>

    <div
      v-loading="loading"
      class="book-list"
    >
      <el-tree
        v-if="treeData.length"
        ref="treeRef"
        :data="treeData"
        node-key="nodeKey"
        :props="{ label: 'title', children: 'children' }"
        highlight-current
        :default-expanded-keys="expandedKeys"
        @node-click="onNodeClick"
        @node-contextmenu="onContextMenu"
      >
        <template #default="{ data }">
          <span
            class="tree-node"
            :class="`tree-node--${data.kind}`"
          >
            <el-icon v-if="data.kind === 'book'"><Notebook /></el-icon>
            <el-icon v-else-if="data.kind === 'volume'"><Folder /></el-icon>
            <el-icon v-else><Document /></el-icon>
            <span class="tree-label">{{ data.title }}</span>
            <el-icon
              v-if="data.kind === 'book' && data.cloudBookId"
              class="tree-cloud-icon"
              title="已同步到云端"
            ><Upload /></el-icon>
            <el-tag
              v-if="data.kind === 'chapter' && data.chapterType && data.chapterType !== '正文'"
              :type="chapterTagType(data.chapterType)"
              size="small"
              effect="plain"
              class="tree-chapter-tag"
            >{{ data.chapterType }}</el-tag>
            <span
              v-if="data.wordCount"
              class="tree-word-count"
            >({{ data.wordCount }}字)</span>
          </span>
        </template>
      </el-tree>

      <el-empty
        v-else
        description="暂无作品"
        :image-size="62"
      >
        <div class="empty-actions">
          <el-button
            type="primary"
            size="small"
            @click="openBookEntry"
          >
            <el-icon><CirclePlus /></el-icon>
            新建
          </el-button>
          <el-button
            size="small"
            @click="openImportEntry"
          >
            <el-icon><Upload /></el-icon>
            导入
          </el-button>
        </div>
      </el-empty>
    </div>

    <!-- 右键菜单 -->
    <div
      v-if="contextMenu.visible"
      class="context-menu"
      :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }"
    >
      <template v-if="contextMenu.kind === 'book'">
        <div
          class="context-item"
          @click="handleContextAction('new-volume')"
        >
          新建分卷
        </div>
        <div
          class="context-item"
          @click="handleContextAction('new-chapter')"
        >
          新建章节
        </div>
        <el-divider style="margin: 4px 0" />
        <el-tooltip
          v-if="!authStore.isLoggedIn"
          content="请先登录"
          placement="right"
          :show-after="0"
        >
          <div class="context-item context-item--disabled">
            上传到云端
          </div>
        </el-tooltip>
        <div
          v-else
          class="context-item"
          @click="handleContextAction('upload-cloud')"
        >
          {{ contextMenu.hasCloudBookId ? '同步到云端' : '上传到云端' }}
        </div>
        <el-divider style="margin: 4px 0" />
        <div
          class="context-item"
          @click="handleContextAction('rename')"
        >
          重命名
        </div>
        <div
          class="context-item context-item--danger"
          @click="handleContextAction('delete')"
        >
          删除
        </div>
      </template>
      <template v-else-if="contextMenu.kind === 'volume'">
        <div
          class="context-item"
          @click="handleContextAction('new-chapter')"
        >
          新建章节
        </div>
        <template v-if="!contextMenu.isVirtual">
          <div
            class="context-item"
            @click="handleContextAction('rename')"
          >
            重命名
          </div>
          <div
            class="context-item context-item--danger"
            @click="handleContextAction('delete')"
          >
            删除
          </div>
        </template>
      </template>
      <template v-else-if="contextMenu.kind === 'chapter'">
        <div
          class="context-item"
          @click="handleContextAction('rename')"
        >
          重命名
        </div>
        <div
          class="context-item"
          @click="handleContextAction('export')"
        >
          导出
        </div>
        <div
          class="context-item context-item--danger"
          @click="handleContextAction('delete')"
        >
          删除
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue';
import {
  CirclePlus,
  Document,
  DocumentAdd,
  Folder,
  FolderAdd,
  Notebook,
  Upload,
} from '@element-plus/icons-vue';
import { useAuthStore } from '../../stores/auth';

const authStore = useAuthStore();

const props = defineProps({
  books: { type: Array, default: () => [] },
  currentBookId: { type: [Number, null], default: null },
  loading: { type: Boolean, default: false },
});

const emit = defineEmits([
  'select',
  'create',
  'import',
  'create-volume',
  'create-chapter',
  'delete',
  'rename',
  'export-chapter',
  'upload-cloud',
]);

const treeRef = ref(null);

// 右键菜单状态
const contextMenu = ref({
  visible: false, x: 0, y: 0,
  kind: '', nodeKey: '', nodeId: null,
});

// 树数据构建
const treeData = computed(() =>
  props.books.map(b => ({
    kind: 'book',
    nodeKey: `book-${b.id}`,
    title: b.title || '未命名',
    bookId: b.id,
    cloudBookId: b.cloud_book_id || null,
    wordCount: b.word_count || 0,
    children: (b.volumes || []).map(v => ({
      kind: 'volume',
      nodeKey: v.id === null || v.id === undefined ? `volume-unassigned-${b.id}` : `volume-${v.id}`,
      title: v.title || '正文',
      volumeId: v.id,
      isVirtual: Boolean(v.is_virtual),
      bookId: b.id,
      children: (v.chapters || []).map(c => ({
        kind: 'chapter',
        nodeKey: `chapter-${c.id}`,
        title: c.title || `章节 #${c.id}`,
        chapterId: c.id,
        bookId: b.id,
        wordCount: c.word_count || 0,
        chapterType: c.chapter_type || '正文',
      })),
    })),
  })),
);

// 使用 accumulated set 追踪展开的节点 key，避免数据刷新时重复展开
const expandedKeys = ref([]);

function collectAllKeys(nodes) {
  const keys = [];
  for (const node of nodes) {
    keys.push(node.nodeKey);
    if (node.children?.length) {
      keys.push(...collectAllKeys(node.children));
    }
  }
  return keys;
}

watch(treeData, (nodes) => {
  const allKeys = collectAllKeys(nodes);
  const allKeysSet = new Set(allKeys);
  const existing = new Set(expandedKeys.value.filter(key => allKeysSet.has(key)));
  let added = false;
  for (const key of allKeys) {
    if (!existing.has(key)) {
      existing.add(key);
      added = true;
    }
  }
  if (added || existing.size !== expandedKeys.value.length) {
    expandedKeys.value = [...existing];
  }
}, { immediate: true });

const volumeCount = computed(() =>
  props.books.reduce((sum, book) =>
    sum + (book.volumes || []).filter(volume => !volume.is_virtual).length, 0),
);

const chapterCount = computed(() =>
  props.books.reduce((sum, book) =>
    sum + (book.volumes || []).reduce((volumeSum, volume) =>
      volumeSum + (volume.chapters || []).length, 0), 0),
);

function openBookEntry() {
  emit('create');
}

function openImportEntry() {
  emit('import');
}

function chapterTagType(type) {
  if (type === '番外') return 'warning';
  if (type === '作者的话') return 'info';
  return '';
}

function onNodeClick(data) {
  hideContextMenu();
  if (data.kind === 'book') {
    emit('select', { kind: 'book', id: data.bookId, title: data.title });
  } else if (data.kind === 'volume') {
    emit('select', { kind: 'volume', id: data.volumeId, bookId: data.bookId, title: data.title, isVirtual: Boolean(data.isVirtual) });
  } else if (data.kind === 'chapter') {
    emit('select', { kind: 'chapter', id: data.chapterId, bookId: data.bookId, title: data.title });
  }
}

function onContextMenu(event, data) {
  contextMenu.value = {
    visible: true,
    x: event.clientX,
    y: event.clientY,
    kind: data.kind,
    nodeKey: data.nodeKey,
    nodeId: data.kind === 'book' ? data.bookId : data.kind === 'volume' ? data.volumeId : data.chapterId,
    bookId: data.bookId,
    isVirtual: Boolean(data.isVirtual),
    hasCloudBookId: Boolean(data.cloudBookId),
  };
}

function hideContextMenu() {
  contextMenu.value.visible = false;
}

function jumpToChapter(chapterId) {
  const key = `chapter-${chapterId}`;
  treeRef.value?.setCurrentKey(key);
  nextTick(() => {
    const node = document.querySelector(`.library-panel .el-tree-node[data-key="${key}"]`);
    if (!node) return;
    node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
}

function jumpToBook(bookId) {
  const key = `book-${bookId}`;
  treeRef.value?.setCurrentKey(key);
  nextTick(() => {
    const node = document.querySelector(`.library-panel .el-tree-node[data-key="${key}"]`);
    if (!node) return;
    node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
}

defineExpose({ jumpToChapter, jumpToBook });

function handleContextAction(action) {
  const { kind, nodeId, bookId, isVirtual } = contextMenu.value;
  hideContextMenu();
  switch (action) {
    case 'new-volume':
      if (kind === 'book') emit('create-volume', nodeId);
      break;
    case 'new-chapter':
      emit('create-chapter', {
        bookId: kind === 'book' ? nodeId : bookId,
        volumeId: kind === 'volume' && !isVirtual ? nodeId : null,
      });
      break;
    case 'upload-cloud':
      if (kind === 'book' && nodeId && typeof nodeId === 'number' && nodeId > 0) {
        emit('upload-cloud', nodeId);
      }
      break;
    case 'rename':
      emit('rename', { kind, id: nodeId });
      break;
    case 'delete':
      emit('delete', { kind, id: nodeId, bookId });
      break;
    case 'export':
      emit('export-chapter', nodeId);
      break;
  }
}

function closeMenuOnClick() {
  if (contextMenu.value.visible) hideContextMenu();
}

onMounted(() => document.addEventListener('click', closeMenuOnClick));
onUnmounted(() => document.removeEventListener('click', closeMenuOnClick));
</script>

<style scoped>
.library-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, var(--bg-secondary), var(--bg-tertiary));
  border-right: 1px solid var(--border-color);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-height: 54px;
  padding: 10px 18px 8px 12px;
  border-bottom: 1px solid var(--border-light);
}

.panel-heading {
  display: none;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.panel-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0;
}

.panel-count {
  color: var(--text-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.header-action {
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 7px;
  margin-left: 0;
}

.book-list {
  flex: 1;
  overflow: auto;
  padding: 6px 6px 10px;
}

.book-list :deep(.el-tree-node__content) {
  height: 30px;
  padding-right: 8px;
  border-radius: 6px;
}

.book-list :deep(.el-tree) {
  background: transparent;
}

.book-list :deep(.el-tree-node__content:hover) {
  background: var(--bg-hover);
}

.book-list :deep(.el-tree--highlight-current .el-tree-node.is-current > .el-tree-node__content) {
  background: var(--bg-active);
  color: var(--color-primary);
}

.empty-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  font-size: var(--font-size-sm);
  user-select: none;
}

.tree-node--book .tree-label {
  font-weight: 600;
  font-size: var(--font-size-base);
}

.tree-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-word-count {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  margin-left: auto;
  flex-shrink: 0;
}

.tree-chapter-tag {
  font-size: 10px;
  height: 18px;
  line-height: 16px;
  padding: 0 4px;
  border-radius: 3px;
  flex-shrink: 0;
}

.context-menu {
  position: fixed;
  z-index: 1000;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  padding: 4px 0;
  min-width: 140px;
}

.context-item {
  padding: 6px 16px;
  font-size: var(--font-size-sm);
  cursor: pointer;
  color: var(--text-primary);
}

.context-item:hover {
  background: var(--bg-hover);
}

.context-item--danger {
  color: var(--color-danger);
}

.context-item--danger:hover {
  background: rgba(245, 108, 108, 0.08);
}

.context-item--disabled {
  color: var(--text-placeholder);
  cursor: not-allowed;
}

.context-item--disabled:hover {
  background: transparent;
}

.tree-cloud-icon {
  color: var(--color-primary);
  font-size: 12px;
  flex-shrink: 0;
  opacity: 0.7;
}
</style>
