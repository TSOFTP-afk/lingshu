<template>
  <el-dialog
    :model-value="visible"
    title="上传卡片到社区"
    width="500px"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <el-form
      label-position="top"
      @submit.prevent
    >
      <!-- 步骤1：选择书籍 -->
      <el-form-item
        label="选择书籍"
        required
      >
        <el-select
          v-model="form.source_book_id"
          placeholder="请选择书籍"
          filterable
          :loading="loadingBooks"
          style="width: 100%"
          @change="onBookChange"
        >
          <el-option
            v-for="book in books"
            :key="book.id"
            :label="book.title"
            :value="book.id"
          />
        </el-select>
      </el-form-item>

      <!-- 步骤2：选择卡片类型 -->
      <el-form-item
        label="卡片类型"
        required
      >
        <el-radio-group
          v-model="form.card_type"
          :disabled="!form.source_book_id"
          @change="onTypeChange"
        >
          <el-radio value="world">
            世界卡
          </el-radio>
          <el-radio value="character">
            人物卡
          </el-radio>
        </el-radio-group>
      </el-form-item>

      <!-- 步骤3：选择卡片 -->
      <el-form-item
        v-if="form.card_type"
        label="选择卡片"
        required
      >
        <div
          v-if="form.card_type === 'world'"
          class="world-hint"
        >
          世界卡为整本世界观，将直接上传该书的当前世界观
        </div>
        <el-select
          v-else
          v-model="form.source_card_id"
          placeholder="请选择人物"
          filterable
          :loading="loadingCharacters"
          :disabled="!form.source_book_id"
          style="width: 100%"
        >
          <el-option
            v-for="char in characters"
            :key="char.id"
            :label="char.name"
            :value="char.id"
          />
        </el-select>
      </el-form-item>

      <!-- 步骤4：卡片介绍 -->
      <el-form-item
        label="卡片介绍"
        required
      >
        <el-input
          v-model="form.intro"
          type="textarea"
          :rows="2"
          maxlength="100"
          show-word-limit
          placeholder="一句话介绍这张卡片（必填，最多100字）"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="onCancel">
        取消
      </el-button>
      <el-button
        type="primary"
        :loading="submitting"
        @click="onSubmit"
      >
        上传
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';
import { useCommunityStore } from '../../stores/community';

const props = defineProps({
  visible: { type: Boolean, default: false },
});

const emit = defineEmits(['update:visible', 'success']);

const communityStore = useCommunityStore();

const form = reactive({
  source_book_id: null,
  card_type: '',
  source_card_id: null,
  intro: '',
});

const books = ref([]);
const characters = ref([]);
const loadingBooks = ref(false);
const loadingCharacters = ref(false);
const submitting = ref(false);

function resetForm() {
  form.source_book_id = null;
  form.card_type = '';
  form.source_card_id = null;
  form.intro = '';
  characters.value = [];
}

async function fetchBooks() {
  loadingBooks.value = true;
  try {
    const { data } = await api.get('/workspace/books');
    books.value = data.items || [];
  } catch {
    books.value = [];
  } finally {
    loadingBooks.value = false;
  }
}

async function fetchCharacters(bookId) {
  if (!bookId) {
    characters.value = [];
    return;
  }
  loadingCharacters.value = true;
  try {
    const { data } = await api.get(`/workspace/books/${bookId}/characters`);
    characters.value = data.items || [];
  } catch {
    characters.value = [];
  } finally {
    loadingCharacters.value = false;
  }
}

function onBookChange() {
  form.card_type = '';
  form.source_card_id = null;
  characters.value = [];
}

function onTypeChange(value) {
  form.source_card_id = null;
  if (value === 'world') {
    form.source_card_id = 0;
  } else if (value === 'character' && form.source_book_id) {
    fetchCharacters(form.source_book_id);
  }
}

function onCancel() {
  emit('update:visible', false);
}

async function onSubmit() {
  if (!form.source_book_id) {
    ElMessage.warning('请选择书籍');
    return;
  }
  if (!form.card_type) {
    ElMessage.warning('请选择卡片类型');
    return;
  }
  if (form.card_type === 'character' && form.source_card_id == null) {
    ElMessage.warning('请选择人物');
    return;
  }
  if (!form.intro.trim()) {
    ElMessage.warning('请输入卡片介绍');
    return;
  }

  submitting.value = true;
  try {
    await communityStore.uploadCard({
      card_type: form.card_type,
      source_book_id: form.source_book_id,
      source_card_id: form.source_card_id,
      intro: form.intro.trim(),
    });
    ElMessage.success('上传成功');
    emit('success');
    emit('update:visible', false);
    resetForm();
  } catch (e) {
    const msg = e?.message || '';
    if (msg.includes('已上传')) {
      ElMessage.warning(msg);
    } else {
      ElMessage.error(msg || '上传失败');
    }
  } finally {
    submitting.value = false;
  }
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      fetchBooks();
    } else {
      resetForm();
    }
  },
);
</script>

<style scoped>
.world-hint {
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--bg-hover, #f5f7fa);
  border: 1px solid var(--border-light, #ebeef5);
  color: var(--text-secondary, #606266);
  font-size: 12px;
  line-height: 1.6;
}
</style>
