<template>
  <div class="shortcuts-tab">
    <div class="tab-header">
      <span class="tab-title">快捷键</span>
    </div>

    <p class="hint">
      格式：Ctrl+D = '张三'。这里记录书籍级快捷插入项。
    </p>

    <div class="shortcuts-list">
      <div
        v-for="(item, idx) in shortcuts"
        :key="idx"
        class="shortcut-item"
      >
        <el-tag
          size="small"
          effect="plain"
        >
          {{ item.key }}
        </el-tag>
        <span class="shortcut-value">{{ item.value }}</span>
        <el-button
          size="small"
          text
          type="danger"
          @click="onRemove(idx)"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
      <div
        v-if="!shortcuts.length"
        class="empty-hint"
      >
        暂无快捷键条目
      </div>
    </div>

    <div class="add-row">
      <el-input
        v-model="newKey"
        placeholder="快捷键，如 Ctrl+D"
        size="small"
        style="width: 138px"
      />
      <el-input
        v-model="newValue"
        placeholder="插入内容，如 张三"
        size="small"
      />
      <el-button
        size="small"
        :disabled="!newKey || !newValue"
        @click="onAdd"
      >
        新增
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { Delete } from '@element-plus/icons-vue';

const shortcuts = ref([]);
const newKey = ref('');
const newValue = ref('');

function onAdd() {
  if (!newKey.value.trim() || !newValue.value.trim()) return;
  shortcuts.value.push({ key: newKey.value.trim(), value: newValue.value.trim() });
  newKey.value = '';
  newValue.value = '';
}

function onRemove(idx) {
  shortcuts.value.splice(idx, 1);
}
</script>

<style scoped>
.shortcuts-tab { padding: 4px 0; }
.tab-header { margin-bottom: 8px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.hint { font-size: 11px; color: var(--text-placeholder); margin-bottom: 12px; line-height: 1.5; }
.shortcut-item { display: flex; align-items: center; gap: 6px; padding: 4px 0; }
.shortcut-value { font-size: 13px; color: var(--text-primary); flex: 1; }
.empty-hint { font-size: 12px; color: var(--text-placeholder); padding: 12px 0; }
.add-row { display: flex; gap: 6px; margin-top: 12px; }
</style>
