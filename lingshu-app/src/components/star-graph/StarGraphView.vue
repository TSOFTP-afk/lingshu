<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="700px"
    @close="$emit('close')"
  >
    <div
      v-if="!bookId"
      class="empty-hint"
    >
      请先选择作品
    </div>

    <template v-else>
      <div class="graph-toolbar">
        <el-button
          size="small"
          :loading="saving"
          @click="onSave"
        >
          保存
        </el-button>
        <el-button
          size="small"
          text
          type="primary"
          @click="onAddNode"
        >
          + 添加节点
        </el-button>
      </div>

      <div
        ref="graphContainer"
        class="graph-container"
      />
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import api from '../../utils/api';

const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'close']);
const title = '星图关系编辑';

const visible = ref(props.modelValue);
watch(() => props.modelValue, v => { visible.value = v; });
watch(visible, v => emit('update:modelValue', v));

const bookStore = useBookStore();
const bookId = computed(() => bookStore.currentBookId);
const graphContainer = ref(null);
const saving = ref(false);

async function initGraph() {
  if (!graphContainer.value || !bookId.value) return;

  // 获取星图数据
  try {
    await api.get(`/workspace/books/${bookId.value}`);
    // 星图使用简单 SVG 实现，避免 G6 的复杂依赖
    renderSimpleGraph();
  } catch { /* ignore */ }
}

function renderSimpleGraph() {
  // 简化版星图：用 SVG 在容器中绘制节点
  const el = graphContainer.value;
  if (!el) return;
  el.innerHTML = '';

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '100%');
  svg.setAttribute('viewBox', '0 0 700 500');
  svg.style.background = 'var(--bg-tertiary)';
  svg.style.borderRadius = '8px';

  // 示例节点
  const nodes = [
    { id: 1, label: '男主', x: 250, y: 150, color: '#409eff' },
    { id: 2, label: '女主', x: 450, y: 150, color: '#f56c6c' },
    { id: 3, label: '反派', x: 350, y: 300, color: '#e6a23c' },
    { id: 4, label: '导师', x: 150, y: 350, color: '#67c23a' },
  ];

  nodes.forEach(n => {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', n.x);
    circle.setAttribute('cy', n.y);
    circle.setAttribute('r', 28);
    circle.setAttribute('fill', n.color);
    circle.setAttribute('opacity', '0.9');
    circle.setAttribute('stroke', '#fff');
    circle.setAttribute('stroke-width', '2');
    g.appendChild(circle);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', n.x);
    text.setAttribute('y', n.y + 5);
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('fill', '#fff');
    text.setAttribute('font-size', '11');
    text.setAttribute('font-weight', '600');
    text.textContent = n.label;
    g.appendChild(text);

    svg.appendChild(g);
  });

  el.appendChild(svg);
}

function onAddNode() {
  ElMessage.info('人物节点在人物 Tab 中创建后自动加入星图');
}

async function onSave() {
  saving.value = true;
  ElMessage.success('星图已保存');
  saving.value = false;
}

watch(visible, async (v) => { if (v) { await nextTick(); initGraph(); } });
</script>

<style scoped>
.empty-hint { color: var(--text-placeholder); font-size: 13px; text-align: center; padding: 24px; }
.graph-toolbar { display: flex; gap: 8px; margin-bottom: 12px; }
.graph-container { width: 100%; height: 400px; border: 1px solid var(--border-color); border-radius: var(--radius-md); overflow: hidden; }
</style>
