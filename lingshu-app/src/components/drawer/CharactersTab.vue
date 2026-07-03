<template>
  <div class="characters-tab">
    <!-- 顶部标题栏 -->
    <div class="tab-header">
      <span class="tab-title">人物卡</span>
      <div class="tab-header-actions">
        <el-tooltip
          v-if="chapterId"
          :content="chapterFilterEnabled ? '当前仅显示本章出场人物，点击切换为全部' : '当前显示全部人物，点击切换为本章出场'"
          placement="bottom"
        >
          <el-switch
            v-model="chapterFilterEnabled"
            inline-prompt
            active-text="本章"
            inactive-text="全部"
            size="small"
          />
        </el-tooltip>
        <el-button
          size="small"
          text
          type="primary"
          :disabled="!bookId"
          @click="onCreate"
        >
          + 新建
        </el-button>
      </div>
    </div>

    <!-- 人物列表 -->
    <div
      v-if="displayedCharacters.length"
      class="char-list"
    >
      <div
        v-for="ch in displayedCharacters"
        :key="ch.id"
        class="char-item"
        :class="{ 'char-item--active': selectedId === ch.id }"
        @click="onSelect(ch)"
      >
        <div
          class="char-avatar"
          :style="avatarStyle(ch)"
        >
          {{ (ch.name || '?')[0] }}
        </div>
        <div class="char-info">
          <div class="char-name">
            {{ ch.name || '未命名' }}
          </div>
          <div class="char-role">
            {{ ch.role || '未设定' }}
          </div>
        </div>
        <div
          v-if="ch.total_change_score"
          class="char-score-badge"
        >
          +{{ ch.total_change_score }}
        </div>
      </div>
    </div>
    <el-empty
      v-else
      :description="chapterFilterEnabled && chapterId ? '本章暂无出场人物' : '暂无人物卡'"
      :image-size="50"
    />

    <!-- 详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      width="900px"
      top="6vh"
      :before-close="onDetailClose"
      class="character-dialog"
      :show-close="false"
      align-center
      destroy-on-close
    >
      <template #header>
        <div
          v-if="selectedChar"
          class="dialog-header"
        >
          <div
            class="dialog-avatar"
            :style="avatarStyle(selectedChar)"
          >
            {{ (selectedChar.name || '?')[0] }}
          </div>
          <div class="dialog-header-info">
            <div class="dialog-header-line">
              <el-input
                v-model="editForm.name"
                size="default"
                placeholder="姓名"
                class="name-input"
              />
              <el-input
                v-model="editForm.role"
                size="default"
                placeholder="角色定位"
                class="role-input"
              />
            </div>
            <div class="dialog-header-meta">
              <span class="meta-tag meta-tag--score">
                <span class="meta-tag-icon">⚡</span>
                经验值 +{{ currentStateMachine?.total_change_score || 0 }}
              </span>
              <span
                v-if="currentStateMachine?.current_desire_state"
                class="meta-tag"
              >
                星座 · {{ desireStateLabel(currentStateMachine.current_desire_state) }}
              </span>
              <span
                v-if="currentStateMachine?.current_fate_state"
                class="meta-tag"
              >
                命理 · {{ fateStateLabel(currentStateMachine.current_fate_state) }}
              </span>
              <span
                v-if="currentStateMachine?.current_friction && currentStateMachine.current_friction !== 'none'"
                class="meta-tag meta-tag--friction"
              >
                内耗 · {{ frictionLabel(currentStateMachine.current_friction) }}
              </span>
            </div>
          </div>
          <el-button
            class="dialog-close"
            text
            circle
            @click="onDetailClose(() => detailVisible = false)"
          >
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </template>

      <template v-if="selectedChar">
        <el-tabs
          v-model="activeTab"
          class="sm-tabs"
        >
          <!-- 标签1：状态机 -->
          <el-tab-pane name="state">
            <template #label>
              <span class="tab-label">状态机</span>
            </template>
            <div class="sm-sections">
              <div
                v-for="(section, key) in stateMachineSchema"
                :key="key"
                class="sm-section"
                :class="`sm-section--${key}`"
              >
                <div
                  class="sm-section-head"
                  @click="toggleSection(key)"
                >
                  <span class="sm-section-axis">{{ axisTag(key) }}</span>
                  <span class="sm-section-title">{{ section.title }}</span>
                  <el-icon class="sm-section-arrow" :class="{ 'is-open': openSections.has(key) }">
                    <ArrowRight />
                  </el-icon>
                </div>
                <transition name="section-fold">
                  <div v-show="openSections.has(key)" class="sm-fields">
                    <div
                      v-for="field in section.fields"
                      :key="field.id"
                      class="sm-field"
                      :class="{ 'sm-field--inline': field.type === 'text' || field.type === 'select' }"
                    >
                      <label class="sm-field-label">{{ field.label }}</label>
                      <el-input
                        v-if="field.type === 'text'"
                        v-model="smEditForm[field.id]"
                        size="small"
                        :placeholder="`输入${field.label}`"
                      />
                      <el-input
                        v-else-if="field.type === 'multiline'"
                        v-model="smEditForm[field.id]"
                        type="textarea"
                        :rows="2"
                        size="small"
                        :placeholder="`描述${field.label}`"
                        resize="none"
                      />
                      <el-select
                        v-else-if="field.type === 'select'"
                        v-model="smEditForm[field.id]"
                        size="small"
                        clearable
                        :placeholder="`选择${field.label}`"
                        style="width: 100%"
                      >
                        <el-option
                          v-for="opt in (field.options || [])"
                          :key="opt"
                          :label="optionLabel(field.id, opt)"
                          :value="opt"
                        />
                      </el-select>
                    </div>
                  </div>
                </transition>
              </div>
            </div>

            <!-- 兼容表单折叠区 -->
            <details class="legacy-form-section">
              <summary class="legacy-form-summary">
                <el-icon><FolderOpened /></el-icon>
                兼容表单（旧数据视图）
              </summary>
              <div class="legacy-form-body">
                <StructuredTemplateForm
                  v-model="editForm.profile_data"
                  :schema="activeProfileSchema"
                  empty-text="暂无旧表单数据"
                />
              </div>
            </details>
          </el-tab-pane>

          <!-- 标签2：循环日志 -->
          <el-tab-pane name="cycles">
            <template #label>
              <span class="tab-label">
                循环日志
                <span
                  v-if="cycles.length"
                  class="tab-count"
                >{{ cycles.length }}</span>
              </span>
            </template>
            <div class="cycles-list">
              <div
                v-for="cycle in cycles"
                :key="cycle.id"
                class="cycle-item"
                :class="`cycle-item--${cycle.cycle_type}`"
              >
                <div
                  class="cycle-header"
                  @click="toggleCycleExpand(cycle.id)"
                >
                  <span class="cycle-code">{{ cycle.cycle_code }}</span>
                  <span
                    class="cycle-badge"
                    :class="cycleBadgeClass(cycle.cycle_type)"
                  >
                    {{ cycleTypeLabel(cycle.cycle_type) }}
                  </span>
                  <span
                    v-if="cycle.feedback_intensity"
                    class="cycle-intensity"
                  >
                    {{ intensityLabel(cycle.feedback_intensity) }}
                  </span>
                  <span class="cycle-score">+{{ cycle.change_score }}</span>
                  <span class="cycle-cumulative">累计 {{ cycle.cumulative_score }}</span>
                  <el-icon
                    v-if="cycle.cycle_type !== 'micro'"
                    class="cycle-arrow"
                    :class="{ 'is-open': expandedCycles.has(cycle.id) }"
                  >
                    <ArrowRight />
                  </el-icon>
                </div>
                <div class="cycle-feedback">
                  {{ cycle.world_feedback || '无反馈摘要' }}
                </div>
                <transition name="cycle-fold">
                  <div
                    v-if="expandedCycles.has(cycle.id) && cycle.cycle_type !== 'micro'"
                    class="cycle-detail"
                  >
                    <div
                      v-if="cycle.triggered_desire"
                      class="cycle-row"
                    >
                      <span class="cycle-row-label">触发欲望</span>
                      <span>{{ cycle.triggered_desire }}</span>
                    </div>
                    <div
                      v-if="cycle.belief_filtered_strategy"
                      class="cycle-row"
                    >
                      <span class="cycle-row-label">策略</span>
                      <span>{{ cycle.belief_filtered_strategy }}</span>
                    </div>
                    <div
                      v-if="cycle.action_taken"
                      class="cycle-row"
                    >
                      <span class="cycle-row-label">行动</span>
                      <span>{{ cycle.action_taken }}</span>
                    </div>
                    <div
                      v-if="cycle.mbti_change"
                      class="cycle-row"
                    >
                      <span class="cycle-row-label">MBTI迭代</span>
                      <span>{{ cycle.mbti_change }}</span>
                    </div>
                    <div
                      v-if="cycle.star_state"
                      class="cycle-row"
                    >
                      <span class="cycle-row-label">星座状态</span>
                      <span>{{ cycle.star_state }}</span>
                    </div>
                    <div
                      v-if="cycle.fate_state"
                      class="cycle-row"
                    >
                      <span class="cycle-row-label">命理状态</span>
                      <span>{{ cycle.fate_state }}</span>
                    </div>
                  </div>
                </transition>
              </div>
              <el-empty
                v-if="!cycles.length"
                description="暂无循环日志"
                :image-size="60"
              />
            </div>
          </el-tab-pane>

          <!-- 标签3：快照存档 -->
          <el-tab-pane name="snapshots">
            <template #label>
              <span class="tab-label">
                快照存档
                <span
                  v-if="snapshots.length"
                  class="tab-count"
                >{{ snapshots.length }}</span>
              </span>
            </template>
            <div class="snapshots-timeline">
              <div
                v-for="(snap, idx) in snapshots"
                :key="snap.id"
                class="snapshot-node"
                :class="{ 'snapshot-node--first': idx === 0 }"
              >
                <div class="snapshot-dot">
                  <span class="snapshot-dot-inner">{{ snap.snapshot_no }}</span>
                </div>
                <div class="snapshot-content">
                  <div class="snapshot-header">
                    <span class="snapshot-trigger">{{ snapshotTriggerLabel(snap.trigger_type) }}</span>
                    <span
                      v-if="snap.trigger_detail"
                      class="snapshot-detail-tag"
                    >{{ snap.trigger_detail }}</span>
                    <span class="snapshot-score">经验值 {{ snap.total_score_at_snapshot }}</span>
                  </div>
                  <div
                    v-if="snap.phase_dilemma"
                    class="snapshot-dilemma"
                  >
                    {{ snap.phase_dilemma }}
                  </div>
                  <div
                    v-if="snap.phase_change_summary"
                    class="snapshot-summary"
                  >
                    {{ snap.phase_change_summary }}
                  </div>
                  <div
                    v-if="snap.micro_cycle_summary"
                    class="snapshot-micro"
                  >
                    微循环：{{ snap.micro_cycle_summary }}
                  </div>
                </div>
              </div>
              <el-empty
                v-if="!snapshots.length"
                description="暂无快照存档 · 累计经验值每跨 10 门槛自动存档"
                :image-size="60"
              />
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>

      <template #footer>
        <div class="dialog-footer">
          <el-button
            type="danger"
            size="default"
            plain
            :disabled="!selectedId"
            @click="onDelete"
          >
            删除人物
          </el-button>
          <div class="dialog-footer-right">
            <el-button
              size="default"
              @click="onDetailClose(() => detailVisible = false)"
            >
              取消
            </el-button>
            <el-button
              type="primary"
              size="default"
              :loading="saving"
              @click="onSave"
            >
              保存
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, reactive } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Close, ArrowRight, FolderOpened } from '@element-plus/icons-vue';
import { useBookStore } from '../../stores/book';
import { useCharacterStore } from '../../stores/character';
import { useEventBus } from '../../composables/useEventBus';
import api from '../../utils/api';
import StructuredTemplateForm from '../common/StructuredTemplateForm.vue';

const bookStore = useBookStore();
const characterStore = useCharacterStore();
const bookId = computed(() => bookStore.currentBookId);
const chapterId = computed(() => bookStore.activeChapterId);
const { on, off } = useEventBus();

// 现有状态
const characters = computed(() => characterStore.characters);

// 章节人物过滤：默认仅展示当前章节出场人物（按 appear_count 降序）
const chapterFilterEnabled = ref(true);
const appearingCharacters = ref([]);
const displayedCharacters = computed(() => {
  if (!chapterFilterEnabled.value || !chapterId.value || appearingCharacters.value.length === 0) {
    return characters.value;
  }
  // 按 appear_count 降序排列
  const sortedIds = appearingCharacters.value
    .slice()
    .sort((a, b) => (b.appear_count || 0) - (a.appear_count || 0))
    .map(a => Number(a.character_id));
  return sortedIds
    .map(id => characters.value.find(c => Number(c.id) === id))
    .filter(Boolean);
});
const characterSchemas = computed(() => characterStore.characterSchemas);
const selectedId = ref(null);
const selectedChar = ref(null);
const detailVisible = ref(false);
const saving = ref(false);

// 新增状态
const activeTab = ref('state');
const openSections = ref(new Set(['static_attrs', 'desire', 'mbti', 'fate', 'belief', 'snapshot']));
const expandedCycles = ref(new Set());
const currentStateMachine = computed(() => characterStore.currentStateMachine);
const cycles = computed(() => [...characterStore.cycles].reverse());
const snapshots = computed(() => characterStore.snapshots);

// 表单
const editForm = ref({ name: '', role: '', profile_text: '', profile_data: {} });
const smEditForm = reactive({}); // 状态机字段编辑表单

// 状态机 Schema（前端定义，与后端 STATE_MACHINE_SCHEMA 一致）
const stateMachineSchema = {
  static_attrs: { title: '静态属性', fields: [
    { id: 'alias', label: '别名/称号', type: 'text' },
    { id: 'age', label: '年龄', type: 'text' },
    { id: 'gender', label: '性别', type: 'text' },
    { id: 'appearance_keywords', label: '外貌关键词', type: 'text' },
    { id: 'signature_feature', label: '标志性特征', type: 'text' },
    { id: 'identity_occupation', label: '身份/职业', type: 'text' },
  ]},
  desire: { title: '轴1：星座——欲望层', fields: [
    { id: 'desire_text', label: '终极欲望', type: 'multiline' },
    { id: 'desire_origin', label: '情感引力源', type: 'multiline' },
    { id: 'desire_anchor', label: '关系锚点', type: 'text' },
    { id: 'desire_extreme', label: '欲望极端形态', type: 'multiline' },
    { id: 'desire_fear_mirror', label: '恐惧镜像', type: 'multiline' },
  ]},
  mbti: { title: '轴2：MBTI——认知层', fields: [
    { id: 'mbti_type', label: 'MBTI类型', type: 'text' },
    { id: 'mbti_i_e', label: 'I/E', type: 'select', options: ['', 'I', 'E'] },
    { id: 'mbti_n_s', label: 'N/S', type: 'select', options: ['', 'N', 'S'] },
    { id: 'mbti_t_f', label: 'T/F', type: 'select', options: ['', 'T', 'F'] },
    { id: 'mbti_j_p', label: 'J/P', type: 'select', options: ['', 'J', 'P'] },
    { id: 'mbti_strategy', label: '策略原型', type: 'text' },
    { id: 'mbti_advantage', label: '认知优势', type: 'multiline' },
    { id: 'mbti_blindspot', label: '认知盲点', type: 'multiline' },
  ]},
  fate: { title: '轴3：命理——边界层', fields: [
    { id: 'fate_type', label: '命理类型', type: 'select', options: ['', 'paradox', 'inertial', 'decay'] },
    { id: 'fate_content', label: '命理内容', type: 'multiline' },
    { id: 'fate_trigger', label: '触发条件', type: 'multiline' },
    { id: 'fate_target', label: '反噬方向', type: 'text' },
    { id: 'fate_limit', label: '反噬极限', type: 'multiline' },
  ]},
  belief: { title: '价值观筛选器', fields: [
    { id: 'belief_core', label: '根本信条', type: 'multiline' },
    { id: 'belief_origin', label: '信条来源', type: 'multiline' },
    { id: 'belief_alignment', label: '一致性', type: 'select', options: ['', 'aligned', 'partial', 'conflict'] },
    { id: 'belief_sacrifice', label: '可牺牲项', type: 'multiline' },
    { id: 'belief_taboo', label: '不可触碰项', type: 'multiline' },
  ]},
  snapshot: { title: '运行态快照', fields: [
    { id: 'current_desire_state', label: '星座现状', type: 'select', options: ['original', 'shifted', 'reshaped'] },
    { id: 'current_mbti_state', label: 'MBTI现状', type: 'text' },
    { id: 'current_fate_state', label: '命理状态', type: 'select', options: ['dormant', 'active', 'fulfilled'] },
    { id: 'current_belief_state', label: '核心信条状态', type: 'select', options: ['stable', 'loosening', 'rebuilt'] },
    { id: 'current_friction', label: '内耗水平', type: 'select', options: ['none', 'low', 'medium', 'high', 'resolved'] },
    { id: 'current_dilemma', label: '当前困境', type: 'multiline' },
  ]},
};

const activeProfileSchema = computed(() => {
  const key = isProtagonistRole(editForm.value.role) ? 'protagonist' : 'supporting';
  return characterSchemas.value[key] || selectedChar.value?.profile_schema || [];
});

// 选中人物时加载状态机数据
async function onSelect(ch) {
  selectedId.value = ch.id;
  selectedChar.value = ch;
  editForm.value = {
    name: ch.name || '',
    role: ch.role || '',
    profile_text: ch.profile_text || '',
    profile_data: clone(ch.profile_data || {}),
  };
  activeTab.value = 'state';
  expandedCycles.value = new Set();
  openSections.value = new Set(['static_attrs', 'desire', 'mbti', 'fate', 'belief', 'snapshot']);
  detailVisible.value = true;
  // 加载状态机数据
  await characterStore.fetchStateMachine(ch.id);
  await characterStore.fetchCycles(ch.id);
  await characterStore.fetchSnapshots(ch.id);
  // 填充 smEditForm
  syncSmEditForm();
}

function syncSmEditForm() {
  const sm = currentStateMachine.value;
  if (!sm) return;
  // 清空旧值
  Object.keys(smEditForm).forEach(k => delete smEditForm[k]);
  // 填充新值
  for (const section of Object.values(stateMachineSchema)) {
    for (const field of section.fields) {
      smEditForm[field.id] = sm[field.id] ?? '';
    }
  }
}

watch(currentStateMachine, syncSmEditForm, { deep: true });

async function onSave() {
  if (!selectedId.value) return;
  saving.value = true;
  try {
    // 1. 保存基础信息
    await api.patch(`/workspace/characters/${selectedId.value}`, {
      name: editForm.value.name,
      role: editForm.value.role,
      profile_data: editForm.value.profile_data || {},
    });
    // 2. 保存状态机字段
    const smPayload = {};
    for (const section of Object.values(stateMachineSchema)) {
      for (const field of section.fields) {
        smPayload[field.id] = smEditForm[field.id] ?? '';
      }
    }
    await characterStore.updateStateMachine(selectedId.value, smPayload);
    ElMessage.success('已保存');
    await loadCharacters();
    const updated = characters.value.find(c => c.id === selectedId.value);
    if (updated) selectedChar.value = updated;
  } catch { ElMessage.error('保存失败'); }
  finally { saving.value = false; }
}

async function loadCharacters() {
  if (!bookId.value) { return; }
  await characterStore.fetchCharacters(bookId.value);
}

// 标签切换时按需加载数据
watch(activeTab, (tab) => {
  if (!selectedId.value) return;
  if (tab === 'cycles') characterStore.fetchCycles(selectedId.value);
  if (tab === 'snapshots') characterStore.fetchSnapshots(selectedId.value);
});

// 分段折叠
function toggleSection(key) {
  const next = new Set(openSections.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  openSections.value = next;
}

// 辅助函数
function axisTag(key) {
  return { static_attrs: '静', desire: '欲', mbti: '知', fate: '命', belief: '信', snapshot: '态' }[key] || key;
}

function optionLabel(fieldId, opt) {
  const labels = {
    fate_type: { paradox: '悖论型', inertial: '惯性型', decay: '衰变型' },
    belief_alignment: { aligned: '高度一致', partial: '部分矛盾', conflict: '根本冲突' },
    current_desire_state: { original: '原文', shifted: '偏移', reshaped: '重塑' },
    current_fate_state: { dormant: '未触发', active: '持续施加中', fulfilled: '已应验' },
    current_belief_state: { stable: '稳固', loosening: '松动', rebuilt: '崩塌后重建' },
    current_friction: { none: '无', low: '低', medium: '中', high: '高', resolved: '已决' },
  };
  if (!opt) return '未设定';
  return labels[fieldId]?.[opt] || opt;
}

function desireStateLabel(s) { return { original: '原文', shifted: '偏移', reshaped: '重塑' }[s] || s; }
function fateStateLabel(s) { return { dormant: '未触发', active: '持续中', fulfilled: '已应验' }[s] || s; }
function frictionLabel(s) { return { none: '无', low: '低', medium: '中', high: '高', resolved: '已决' }[s] || s; }

function cycleTypeLabel(t) { return { micro: '微', main: '主', heavy: '重' }[t] || t; }
function cycleBadgeClass(t) { return { micro: 'cycle-badge--micro', main: 'cycle-badge--main', heavy: 'cycle-badge--heavy' }[t] || ''; }
function intensityLabel(i) { return { light: '轻度', medium: '中度', heavy: '重度', existential: '存在论级' }[i] || i; }
function snapshotTriggerLabel(t) { return { threshold: '增值门槛', heavy_cycle: '重循环触发', manual: '手动存档' }[t] || t; }

function toggleCycleExpand(id) {
  const next = new Set(expandedCycles.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedCycles.value = next;
}

function onDetailClose(done) {
  characterStore.clearStateMachine();
  done();
}

function avatarStyle(ch) {
  const colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#8e71dd', '#36cfc9'];
  const idx = (ch.id || 0) % colors.length;
  return { backgroundColor: colors[idx] };
}

async function onCreate() {
  if (!bookId.value) return;
  try {
    const { value: name } = await ElMessageBox.prompt('人物名称', '新建人物', {
      confirmButtonText: '创建', inputPattern: /\S+/, inputErrorMessage: '名称不能为空',
    });
    if (!name) return;
    const { data } = await api.post(`/workspace/books/${bookId.value}/characters`, { name });
    await loadCharacters();
    const newChar = characters.value.find(c => c.id === data.item.id);
    if (newChar) onSelect(newChar);
  } catch { /* cancelled */ }
}

async function onDelete() {
  if (!selectedId.value) return;
  try {
    await ElMessageBox.confirm('确定删除此人物？相关状态机、循环日志、快照存档将一并删除。', '确认删除', { type: 'warning' });
    await api.delete(`/workspace/characters/${selectedId.value}`);
    ElMessage.success('已删除');
    detailVisible.value = false;
    selectedId.value = null;
    selectedChar.value = null;
    characterStore.clearStateMachine();
    await loadCharacters();
  } catch { /* cancelled */ }
}

watch(bookId, loadCharacters);
watch([bookId, chapterId], loadAppearingCharacters);
onMounted(() => {
  loadCharacters();
  loadAppearingCharacters();
  // 监听写回完成事件，自动刷新人物列表
  on('lingshu:characters-updated', handleWritebackCompleted);
  on('lingshu:writeback-completed', handleWritebackCompleted);
  // 探针扫描完成后也刷新章节人物
  on('lingshu:probe-scan-completed', handleProbeScanCompleted);
});
onUnmounted(() => {
  off('lingshu:characters-updated', handleWritebackCompleted);
  off('lingshu:writeback-completed', handleWritebackCompleted);
  off('lingshu:probe-scan-completed', handleProbeScanCompleted);
});

async function loadAppearingCharacters() {
  if (!bookId.value || !chapterId.value) {
    appearingCharacters.value = [];
    return;
  }
  try {
    const { data } = await api.get(
      `/workspace/books/${bookId.value}/chapters/${chapterId.value}/appearing-characters`,
    );
    appearingCharacters.value = data.items || [];
  } catch (e) {
    appearingCharacters.value = [];
  }
}

function handleProbeScanCompleted(payload) {
  if (!payload || !bookId.value) return;
  if (Number(payload.book_id) !== Number(bookId.value)) return;
  loadAppearingCharacters();
}

function handleWritebackCompleted(payload) {
  // 仅当事件涉及当前书籍时刷新
  if (!payload || !bookId.value) return;
  if (payload.bookId && Number(payload.bookId) !== Number(bookId.value)) return;
  // 写回目标是 character 或批量写回时刷新
  if (payload.writebackTarget && payload.writebackTarget !== 'character') return;
  loadCharacters();
}

function isProtagonistRole(role) {
  return ['主角', '男主', '女主', '主人公', '主视角'].some(token => String(role || '').includes(token));
}

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}
</script>

<style scoped>
.characters-tab { padding: 4px 0; }
.tab-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.tab-header-actions { display: flex; align-items: center; gap: 8px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }

/* 列表 */
.char-item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-sm); cursor: pointer; transition: all var(--transition-fast); position: relative; margin-bottom: 4px; }
.char-item:hover { background: var(--bg-hover); transform: translateX(2px); }
.char-item--active { background: var(--bg-active); }
.char-avatar { width: 34px; height: 34px; border-radius: 50%; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 600; flex-shrink: 0; box-shadow: 0 2px 6px rgba(0,0,0,0.12); }
.char-name { font-size: 13px; color: var(--text-primary); font-weight: 500; }
.char-role { font-size: 11px; color: var(--text-placeholder); margin-top: 2px; }
.char-score-badge { position: absolute; right: 10px; top: 10px; font-size: 10px; color: #e6a23c; font-weight: 600; background: rgba(230, 162, 60, 0.12); padding: 1px 6px; border-radius: 8px; }

/* ===== 弹窗 ===== */
:deep(.character-dialog) { border-radius: 14px; overflow: hidden; box-shadow: 0 16px 48px rgba(0,0,0,0.18); }
:deep(.character-dialog .el-dialog__header) { padding: 0; margin: 0; border-bottom: 1px solid var(--border-light); }
:deep(.character-dialog .el-dialog__headerbtn) { display: none; }
:deep(.character-dialog .el-dialog__body) { padding: 0 20px; max-height: 62vh; overflow-y: auto; }
:deep(.character-dialog .el-dialog__footer) { padding: 12px 20px; border-top: 1px solid var(--border-light); }

/* 弹窗顶部人物卡 */
.dialog-header { display: flex; align-items: center; gap: 14px; padding: 16px 20px; background: linear-gradient(135deg, rgba(64,158,255,0.06), rgba(142,113,221,0.05)); }
.dialog-avatar { width: 52px; height: 52px; border-radius: 50%; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 600; flex-shrink: 0; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.dialog-header-info { flex: 1; min-width: 0; }
.dialog-header-line { display: flex; gap: 10px; margin-bottom: 8px; }
.dialog-header-line .name-input { width: 160px; }
.dialog-header-line .role-input { width: 140px; }
.dialog-header-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.meta-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: var(--bg-hover); color: var(--text-secondary); display: inline-flex; align-items: center; gap: 3px; }
.meta-tag--score { background: rgba(230, 162, 60, 0.12); color: #e6a23c; font-weight: 600; }
.meta-tag--friction { background: rgba(245, 108, 108, 0.12); color: #f56c6c; }
.meta-tag-icon { font-size: 10px; }
.dialog-close { flex-shrink: 0; }

/* 标签页 */
.sm-tabs { margin-top: 4px; }
:deep(.sm-tabs .el-tabs__header) { margin: 0 0 12px; }
:deep(.sm-tabs .el-tabs__nav-wrap::after) { height: 1px; }
.tab-label { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; }
.tab-count { font-size: 10px; background: var(--bg-hover); color: var(--text-secondary); padding: 0 6px; border-radius: 8px; min-width: 16px; text-align: center; }

/* ===== 状态机分段卡片 ===== */
.sm-sections { display: flex; flex-direction: column; gap: 10px; }
.sm-section { background: var(--bg-card, #fff); border: 1px solid var(--border-light); border-radius: 10px; overflow: hidden; transition: box-shadow var(--transition-fast); }
.sm-section:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
.sm-section--desire { border-left: 3px solid #e6a23c; }
.sm-section--mbti { border-left: 3px solid #409eff; }
.sm-section--fate { border-left: 3px solid #8e71dd; }
.sm-section--belief { border-left: 3px solid #67c23a; }
.sm-section--snapshot { border-left: 3px solid #909399; }
.sm-section--static_attrs { border-left: 3px solid #8b6f47; }

.sm-section-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; cursor: pointer; user-select: none; transition: background var(--transition-fast); }
.sm-section-head:hover { background: var(--bg-hover); }
.sm-section-axis { width: 22px; height: 22px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: #fff; flex-shrink: 0; }
.sm-section--desire .sm-section-axis { background: #e6a23c; }
.sm-section--mbti .sm-section-axis { background: #409eff; }
.sm-section--fate .sm-section-axis { background: #8e71dd; }
.sm-section--belief .sm-section-axis { background: #67c23a; }
.sm-section--snapshot .sm-section-axis { background: #909399; }
.sm-section--static_attrs .sm-section-axis { background: #8b6f47; }
.sm-section-title { flex: 1; font-size: 13px; font-weight: 600; color: var(--text-primary); }
.sm-section-arrow { font-size: 12px; color: var(--text-placeholder); transition: transform var(--transition-fast); }
.sm-section-arrow.is-open { transform: rotate(90deg); }

.sm-fields { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; border-top: 1px solid var(--border-light); }
.sm-field { display: flex; flex-direction: column; gap: 5px; }
.sm-field--inline { flex-direction: row; align-items: center; gap: 10px; }
.sm-field--inline .sm-field-label { width: 80px; flex-shrink: 0; }
.sm-field--inline .el-input, .sm-field--inline .el-select { flex: 1; }
.sm-field-label { font-size: 11px; color: var(--text-secondary); font-weight: 500; }

/* 兼容表单 */
.legacy-form-section { margin-top: 14px; border: 1px dashed var(--border-light); border-radius: 8px; overflow: hidden; }
.legacy-form-summary { display: flex; align-items: center; gap: 6px; padding: 8px 12px; font-size: 12px; color: var(--text-placeholder); cursor: pointer; user-select: none; }
.legacy-form-summary:hover { background: var(--bg-hover); }
.legacy-form-body { padding: 8px 12px 12px; border-top: 1px dashed var(--border-light); }

/* ===== 循环日志 ===== */
.cycles-list { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; }
.cycle-item { background: var(--bg-card, #fff); border: 1px solid var(--border-light); border-radius: 8px; padding: 10px 12px; transition: box-shadow var(--transition-fast); }
.cycle-item:hover { box-shadow: 0 2px 6px rgba(0,0,0,0.04); }
.cycle-item--heavy { border-left: 3px solid #f56c6c; }
.cycle-item--main { border-left: 3px solid #409eff; }
.cycle-item--micro { border-left: 3px solid #c0c4cc; }
.cycle-header { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 12px; }
.cycle-code { font-weight: 600; color: var(--text-primary); min-width: 44px; font-family: 'JetBrains Mono', Consolas, monospace; }
.cycle-badge { font-size: 10px; padding: 1px 8px; border-radius: 8px; font-weight: 600; }
.cycle-badge--micro { background: rgba(192, 196, 204, 0.18); color: #909399; }
.cycle-badge--main { background: rgba(64, 158, 255, 0.12); color: #409eff; }
.cycle-badge--heavy { background: rgba(245, 108, 108, 0.12); color: #f56c6c; }
.cycle-intensity { font-size: 11px; color: var(--text-secondary); }
.cycle-score { font-size: 12px; font-weight: 700; color: #e6a23c; }
.cycle-cumulative { font-size: 11px; color: var(--text-placeholder); margin-left: auto; }
.cycle-arrow { font-size: 11px; color: var(--text-placeholder); transition: transform var(--transition-fast); }
.cycle-arrow.is-open { transform: rotate(90deg); }
.cycle-feedback { font-size: 12px; color: var(--text-secondary); margin-top: 8px; line-height: 1.6; padding: 6px 8px; background: var(--bg-hover); border-radius: 4px; }
.cycle-detail { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border-light); display: flex; flex-direction: column; gap: 6px; }
.cycle-row { display: flex; gap: 10px; font-size: 11px; line-height: 1.5; }
.cycle-row-label { color: var(--text-placeholder); min-width: 64px; flex-shrink: 0; font-weight: 500; }

/* ===== 快照存档时间线 ===== */
.snapshots-timeline { position: relative; padding-left: 22px; padding-top: 4px; }
.snapshots-timeline::before { content: ''; position: absolute; left: 11px; top: 8px; bottom: 8px; width: 2px; background: linear-gradient(to bottom, #409eff, var(--border-light)); border-radius: 1px; }
.snapshot-node { position: relative; padding: 0 0 18px 18px; }
.snapshot-dot { position: absolute; left: -18px; top: 2px; width: 24px; height: 24px; border-radius: 50%; background: #fff; border: 2px solid #409eff; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 6px rgba(64,158,255,0.2); z-index: 1; }
.snapshot-dot-inner { font-size: 10px; font-weight: 700; color: #409eff; }
.snapshot-node--first .snapshot-dot { background: #409eff; }
.snapshot-node--first .snapshot-dot-inner { color: #fff; }
.snapshot-content { background: var(--bg-card, #fff); border: 1px solid var(--border-light); border-radius: 8px; padding: 10px 12px; }
.snapshot-header { display: flex; align-items: center; gap: 8px; font-size: 12px; flex-wrap: wrap; }
.snapshot-trigger { font-size: 11px; padding: 2px 8px; border-radius: 8px; background: rgba(64, 158, 255, 0.12); color: #409eff; font-weight: 600; }
.snapshot-detail-tag { font-size: 10px; padding: 1px 6px; border-radius: 6px; background: var(--bg-hover); color: var(--text-secondary); }
.snapshot-score { font-size: 11px; color: #e6a23c; font-weight: 600; margin-left: auto; }
.snapshot-dilemma { font-size: 12px; color: var(--text-primary); margin-top: 6px; font-weight: 500; line-height: 1.5; }
.snapshot-summary { font-size: 11px; color: var(--text-secondary); margin-top: 4px; line-height: 1.6; }
.snapshot-micro { font-size: 10px; color: var(--text-placeholder); margin-top: 4px; padding-top: 4px; border-top: 1px dashed var(--border-light); }

/* 弹窗底部 */
.dialog-footer { display: flex; align-items: center; justify-content: space-between; }
.dialog-footer-right { display: flex; gap: 8px; }

/* 折叠动画 */
.section-fold-enter-active, .section-fold-leave-active { transition: all 0.2s ease; overflow: hidden; }
.section-fold-enter-from, .section-fold-leave-to { opacity: 0; max-height: 0; }
.cycle-fold-enter-active, .cycle-fold-leave-active { transition: all 0.2s ease; overflow: hidden; }
.cycle-fold-enter-from, .cycle-fold-leave-to { opacity: 0; max-height: 0; }
</style>
