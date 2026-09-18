<template>
  <el-dialog
    v-model="visible"
    title="查找"
    width="min(560px, calc(100vw - 24px))"
    top="7vh"
    class="search-dialog"
    :close-on-click-modal="false"
    @opened="onOpened"
    @close="$emit('close')"
  >
    <div class="search-panel">
      <el-input
        ref="queryInputRef"
        v-model="query"
        placeholder="输入查找内容"
        clearable
        @keydown.enter.prevent="onEnter"
        @input="onQueryInput"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>

      <div class="search-options">
        <el-segmented
          v-model="scope"
          :options="scopeOptions"
          size="small"
        />
        <el-checkbox
          v-model="caseSensitive"
          size="small"
        >
          区分大小写
        </el-checkbox>
      </div>

      <div
        v-if="scope === 'current'"
        class="current-tools"
      >
        <div class="match-count">
          {{ currentMatches.length ? activeMatchIndex + 1 : 0 }} / {{ currentMatches.length }}
        </div>
        <el-button-group>
          <el-button
            size="small"
            :icon="ArrowUp"
            :disabled="!currentMatches.length"
            @click="goToPrevious"
          />
          <el-button
            size="small"
            :icon="ArrowDown"
            :disabled="!currentMatches.length"
            @click="goToNext"
          />
        </el-button-group>
      </div>

      <div
        v-if="scope === 'current'"
        class="replace-tools"
      >
        <el-input
          v-model="replacement"
          placeholder="替换为"
          size="small"
          clearable
        />
        <div class="replace-actions">
          <el-button
            size="small"
            :disabled="!currentMatches.length"
            @click="replaceCurrent"
          >
            替换当前
          </el-button>
          <el-button
            size="small"
            :disabled="!currentMatches.length"
            @click="replaceAllCurrent"
          >
            全部替换
          </el-button>
        </div>
      </div>

      <div
        v-if="showStats"
        class="search-stats"
        role="status"
        aria-live="polite"
      >
        <template v-if="scope === 'current'">
          当前章节 {{ currentMatches.length }} 处
        </template>
        <template v-else>
          全书 {{ results.length }} 条结果
        </template>
      </div>

      <div
        class="search-results"
        role="list"
        aria-label="搜索结果列表"
      >
        <template v-if="scope === 'current'">
          <div
            v-for="(match, idx) in visibleCurrentMatches"
            :key="`${match.start}-${idx}`"
            class="search-item"
            :class="{ 'search-item--active': idx === activeMatchIndex }"
            role="listitem"
            :aria-current="idx === activeMatchIndex ? 'true' : undefined"
            tabindex="0"
            @click="goToMatch(idx)"
            @keydown.enter.prevent="goToMatch(idx)"
          >
            <div class="result-field">
              正文 · 第 {{ match.line }} 行
            </div>
            <div class="result-title">
              {{ activeChapter?.title || '当前章节' }}
            </div>
            <div class="result-context">
              <template
                v-for="(part, i) in highlightParts(match.context)"
                :key="i"
              >
                <mark v-if="part.highlight">{{ part.text }}</mark><span v-else>{{ part.text }}</span>
              </template>
            </div>
          </div>
        </template>

        <template v-else>
          <div
            v-for="(result, idx) in results.slice(0, 100)"
            :key="`${result.chapter_id || result.id}-${result.start}-${idx}`"
            class="search-item"
            role="listitem"
            tabindex="0"
            @click="onSelectBookResult(result)"
            @keydown.enter.prevent="onSelectBookResult(result)"
          >
            <div class="result-field">
              {{ result.volume_title ? `${result.volume_title} · ` : '' }}{{ result.fieldLabel || '正文' }}
              <span v-if="result.line">· 第 {{ result.line }} 行</span>
            </div>
            <div class="result-title">
              {{ result.title || '未命名章节' }}
            </div>
            <div class="result-context">
              <template
                v-for="(part, i) in highlightParts(result.context || '')"
                :key="i"
              >
                <mark v-if="part.highlight">{{ part.text }}</mark><span v-else>{{ part.text }}</span>
              </template>
            </div>
          </div>
        </template>

        <el-empty
          v-if="showEmpty"
          description="未找到结果"
          :image-size="50"
        />
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue';
import { ArrowDown, ArrowUp, Search } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { useEventBus } from '../../composables/useEventBus';
import { useBookStore } from '../../stores/book';
import api from '../../utils/api';

const props = defineProps({
  modelValue: Boolean,
  seed: { type: Object, default: () => ({}) },
});
const emit = defineEmits(['update:modelValue', 'close']);

const scopeOptions = [
  { label: '当前章节', value: 'current' },
  { label: '全书', value: 'book' },
];

const visible = ref(props.modelValue);
const queryInputRef = ref(null);
const query = ref('');
const replacement = ref('');
const scope = ref('current');
const caseSensitive = ref(false);
const results = ref([]);
const searched = ref(false);
const searching = ref(false);
const activeMatchIndex = ref(-1);

const bookStore = useBookStore();
const eventBus = useEventBus();
const activeChapter = computed(() => bookStore.activeChapterId ? bookStore.getChapterTab(bookStore.activeChapterId) : null);

let timer = null;

watch(() => props.modelValue, (value) => {
  visible.value = value;
});

watch(visible, (value) => {
  emit('update:modelValue', value);
});

watch(() => props.seed, (seed) => {
  if (!seed || !visible.value) return;
  applySeed(seed);
});

watch([caseSensitive, scope], () => {
  activeMatchIndex.value = -1;
  if (scope.value === 'book') debounceSearch();
  else if (currentMatches.value.length) goToMatch(0);
});

const currentMatches = computed(() => {
  if (!query.value.trim() || !activeChapter.value?.content) return [];
  return collectMatches(activeChapter.value.content, query.value, caseSensitive.value, 1000);
});

const visibleCurrentMatches = computed(() => currentMatches.value.slice(0, 100));

const showStats = computed(() => {
  if (!query.value.trim()) return false;
  return scope.value === 'current' ? true : searched.value || results.value.length > 0;
});

const showEmpty = computed(() => {
  if (!query.value.trim()) return false;
  if (scope.value === 'current') return visible.value && currentMatches.value.length === 0;
  return searched.value && !results.value.length && !searching.value;
});

function onOpened() {
  nextTick(() => {
    queryInputRef.value?.focus?.();
    applySeed(props.seed);
    if (scope.value === 'current' && currentMatches.value.length) goToMatch(0);
  });
}

function applySeed(seed) {
  const seedQuery = String(seed?.query || '').trim();
  if (seedQuery) query.value = seedQuery;
}

function onQueryInput() {
  activeMatchIndex.value = -1;
  if (scope.value === 'book') debounceSearch();
  else if (currentMatches.value.length) {
    nextTick(() => goToMatch(0));
  }
}

function onEnter(event) {
  if (scope.value === 'current') {
    if (event.shiftKey) goToPrevious();
    else goToNext();
    return;
  }
  if (results.value.length) onSelectBookResult(results.value[0]);
  else onSearch();
}

function debounceSearch() {
  clearTimeout(timer);
  timer = setTimeout(onSearch, 300);
}

async function onSearch() {
  const text = query.value.trim();
  if (scope.value !== 'book') return;
  if (!text) {
    results.value = [];
    searched.value = false;
    return;
  }
  if (!bookStore.currentBookId) {
    results.value = [];
    searched.value = true;
    ElMessage.warning('请先选择作品');
    return;
  }
  searched.value = true;
  searching.value = true;
  try {
    const { data } = await api.get(`/workspace/books/${bookStore.currentBookId}/search`, {
      params: { q: text, limit: 200, case_sensitive: caseSensitive.value },
    });
    results.value = data.items || [];
  } catch {
    results.value = [];
  } finally {
    searching.value = false;
  }
}

function goToPrevious() {
  if (!currentMatches.value.length) return;
  const nextIndex = activeMatchIndex.value <= 0 ? currentMatches.value.length - 1 : activeMatchIndex.value - 1;
  goToMatch(nextIndex);
}

function goToNext() {
  if (!currentMatches.value.length) return;
  const nextIndex = activeMatchIndex.value < 0 ? 0 : (activeMatchIndex.value + 1) % currentMatches.value.length;
  goToMatch(nextIndex);
}

function goToMatch(index) {
  const match = currentMatches.value[index];
  if (!match || !activeChapter.value) return;
  activeMatchIndex.value = index;
  eventBus.emit('lingshu:chapter-find', {
    chapterId: activeChapter.value.id,
    query: query.value,
    start: match.start,
    end: match.end,
    caseSensitive: caseSensitive.value,
  });
}

function replaceCurrent() {
  const match = currentMatches.value[activeMatchIndex.value];
  if (!match || !activeChapter.value) return;
  eventBus.emit('lingshu:chapter-replace', {
    chapterId: activeChapter.value.id,
    query: query.value,
    replacement: replacement.value,
    start: match.start,
    end: match.end,
    caseSensitive: caseSensitive.value,
    all: false,
  });
  nextTick(() => {
    if (currentMatches.value.length) goToMatch(Math.min(activeMatchIndex.value, currentMatches.value.length - 1));
  });
}

function replaceAllCurrent() {
  if (!activeChapter.value || !currentMatches.value.length) return;
  eventBus.emit('lingshu:chapter-replace', {
    chapterId: activeChapter.value.id,
    query: query.value,
    replacement: replacement.value,
    caseSensitive: caseSensitive.value,
    all: true,
  });
  activeMatchIndex.value = -1;
}

function onSelectBookResult(result) {
  const chapterId = Number(result.chapter_id || result.id);
  if (!chapterId) return;
  eventBus.emit('lingshu:open-chapter-search-result', {
    bookId: Number(result.book_id || bookStore.currentBookId),
    chapterId,
    query: query.value,
    start: result.start,
    end: result.end,
    caseSensitive: caseSensitive.value,
  });
  visible.value = false;
}

function collectMatches(text, needle, caseSensitiveValue, limit = 1000) {
  const source = String(text || '');
  const rawNeedle = String(needle || '');
  if (!rawNeedle) return [];
  const haystack = caseSensitiveValue ? source : source.toLowerCase();
  const target = caseSensitiveValue ? rawNeedle : rawNeedle.toLowerCase();
  const matches = [];
  let start = 0;
  while (matches.length < limit) {
    const index = haystack.indexOf(target, start);
    if (index < 0) break;
    const end = index + rawNeedle.length;
    matches.push({
      start: index,
      end,
      line: source.slice(0, index).split('\n').length,
      context: buildContext(source, index, end),
    });
    start = Math.max(end, index + 1);
  }
  return matches;
}

function buildContext(text, start, end) {
  const from = Math.max(0, start - 80);
  const to = Math.min(text.length, end + 120);
  return text.slice(from, to).replace(/\n/g, ' ');
}

function highlightParts(text) {
  const raw = String(text || '');
  if (!raw || !query.value) return [{ text: raw, highlight: false }];
  const escapedQuery = escapeRegExp(query.value);
  const flags = caseSensitive.value ? 'g' : 'gi';
  const regex = new RegExp(`(${escapedQuery})`, flags);
  const parts = [];
  let lastIndex = 0;
  let match;
  while ((match = regex.exec(raw)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ text: raw.slice(lastIndex, match.index), highlight: false });
    }
    parts.push({ text: match[1], highlight: true });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < raw.length) {
    parts.push({ text: raw.slice(lastIndex), highlight: false });
  }
  return parts;
}

function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
</script>

<style scoped>
.search-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: min(68vh, 620px);
  min-height: 0;
}

.search-dialog :deep(.el-dialog__body) {
  padding-top: 0;
}

.search-options,
.current-tools,
.replace-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.replace-tools {
  display: grid;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 7px;
  background: var(--bg-secondary);
}

.match-count,
.search-stats {
  font-size: 12px;
  color: var(--text-secondary);
}

.search-results {
  flex: 1;
  min-height: 0;
  overflow: auto;
  border-top: 1px solid var(--border-light);
}

.search-item {
  padding: 9px 0;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
}

.search-item:hover,
.search-item--active {
  background: var(--bg-hover);
  margin: 0 -12px;
  padding: 9px 12px;
}

.result-field {
  font-size: 10px;
  color: var(--color-primary);
  font-weight: 600;
}

.result-title {
  font-size: 12px;
  color: var(--text-primary);
  margin: 2px 0;
  font-weight: 600;
}

.result-context {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  word-break: break-word;
}

.result-context :deep(mark) {
  background: #fff3a0;
  color: inherit;
  padding: 0 2px;
  border-radius: 2px;
}
</style>
