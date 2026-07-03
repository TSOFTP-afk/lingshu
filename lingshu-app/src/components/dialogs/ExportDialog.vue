<template>
  <el-dialog
    v-model="visible"
    title="导出"
    width="460px"
    @close="$emit('close')"
  >
    <el-form
      :model="form"
      label-width="80px"
      size="small"
    >
      <el-form-item label="导出范围">
        <el-radio-group v-model="form.scope">
          <el-radio value="book">
            整本书
          </el-radio>
          <el-radio value="chapter">
            当前章节
          </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="格式">
        <el-radio-group v-model="form.format">
          <el-radio-button value="txt">
            TXT
          </el-radio-button>
          <el-radio-button value="md">
            Markdown
          </el-radio-button>
          <el-radio-button value="docx">
            DOCX
          </el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">
        取消
      </el-button>
      <el-button
        type="primary"
        :loading="exporting"
        @click="onExport"
      >
        {{ exporting ? '导出中...' : '导出下载' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed } from 'vue';
import { ElMessage } from 'element-plus';
import { useBookStore } from '../../stores/book';
import api from '../../utils/api';

const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'close']);

const visible = ref(props.modelValue);
watch(() => props.modelValue, v => { visible.value = v; });
watch(visible, v => emit('update:modelValue', v));

const bookStore = useBookStore();
const exporting = ref(false);

const form = ref({ scope: 'book', format: 'txt' });
const bookId = computed(() => bookStore.currentBookId);
const chapterId = computed(() => bookStore.activeChapterId);

async function onExport() {
  try {
    exporting.value = true;
    const isBook = form.value.scope === 'book' || !chapterId.value;
    const id = isBook ? bookId.value : chapterId.value;
    const path = `/workspace/${isBook ? `books/${id}` : `chapters/${id}`}/export?fmt=${form.value.format}`;
    const { data } = await api.get(path, { responseType: 'blob', timeout: 60000 });
    const blob = new Blob([data]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${isBook ? (bookStore.currentBook?.title || 'book') : 'chapter'}.${form.value.format}`;
    a.click();
    URL.revokeObjectURL(url);
    ElMessage.success('导出完成');
    visible.value = false;
  } catch { ElMessage.error('导出失败'); }
  finally { exporting.value = false; }
}
</script>
