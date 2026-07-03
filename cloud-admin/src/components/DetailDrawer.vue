<template>
  <el-drawer v-model="detailVisible" :title="drawerTitle" size="700px">
    <!-- 用户详情 + 快速编辑 -->
    <section v-if="activeSection === 'users' && selected" class="edit-block">
      <h3>快速编辑</h3>
      <el-form label-position="top">
        <el-form-item label="作者权限">
          <el-switch v-model="editForm.is_author" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="管理员权限">
          <el-switch v-model="editForm.is_admin" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="账号状态">
          <el-select v-model="editForm.status">
            <el-option label="active" value="active" />
            <el-option label="disabled" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="saving" @click="saveUserEdit">保存修改</el-button>
    </section>

    <section v-if="activeSection === 'users' && selected" class="usage-block">
      <h3>用量汇总</h3>
      <div class="usage-grid">
        <div>
          <span>在线时长</span>
          <strong>{{ formatDuration(selected.usage_summary?.online_seconds ?? selected.online_seconds) }}</strong>
        </div>
        <div>
          <span>分析次数</span>
          <strong>{{ formatNumber(selected.usage_summary?.analysis_count ?? selected.analysis_count) }}</strong>
        </div>
        <div>
          <span>AI Token</span>
          <strong>{{ formatNumber(selected.usage_summary?.ai_total_tokens ?? selected.ai_total_tokens) }}</strong>
        </div>
        <div>
          <span>总输入字数</span>
          <strong>{{ formatNumber(selected.usage_summary?.total_input_chars ?? selected.total_input_chars) }}</strong>
        </div>
        <div>
          <span>全本作品</span>
          <strong>{{ formatNumber(selected.usage_summary?.fulltext_book_count ?? selected.fulltext_book_count) }}</strong>
        </div>
        <div>
          <span>全本文字</span>
          <strong>{{ formatNumber(selected.usage_summary?.fulltext_char_count ?? selected.fulltext_char_count) }}</strong>
        </div>
      </div>
    </section>

    <section v-if="activeSection === 'users' && selected?.online_sessions?.length" class="usage-block">
      <h3>最近在线会话</h3>
      <el-table :data="selected.online_sessions" size="small" stripe>
        <el-table-column prop="status" label="状态" min-width="110" />
        <el-table-column prop="login_at" label="登录时间" min-width="170" />
        <el-table-column prop="logout_at" label="结束时间" min-width="170" />
        <el-table-column label="在线时长" min-width="120">
          <template #default="{ row }">{{ formatDuration(row.online_seconds) }}</template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="activeSection === 'users' && selected?.analysis_runs?.length" class="usage-block">
      <h3>最近分析记录</h3>
      <el-table :data="selected.analysis_runs" size="small" stripe>
        <el-table-column prop="analysis_mode" label="模式" min-width="150" />
        <el-table-column prop="input_chars" label="输入字数" min-width="110">
          <template #default="{ row }">{{ formatNumber(row.input_chars) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" min-width="100" />
        <el-table-column prop="created_at" label="时间" min-width="170" />
      </el-table>
    </section>

    <section v-if="activeSection === 'users' && selected?.ai_usage_events?.length" class="usage-block">
      <h3>最近 AI 用量</h3>
      <el-table :data="selected.ai_usage_events" size="small" stripe>
        <el-table-column prop="feature" label="功能" min-width="150" />
        <el-table-column prop="model" label="模型" min-width="150" />
        <el-table-column prop="total_tokens" label="Token" min-width="100">
          <template #default="{ row }">{{ formatNumber(row.total_tokens) }}</template>
        </el-table-column>
        <el-table-column prop="input_chars" label="输入字数" min-width="110">
          <template #default="{ row }">{{ formatNumber(row.input_chars) }}</template>
        </el-table-column>
        <el-table-column prop="token_source" label="来源" min-width="110" />
      </el-table>
    </section>

    <!-- 配额编辑 -->
    <section v-if="activeSection === 'quotas' && selected" class="edit-block">
      <h3>调整配额</h3>
      <el-form label-position="top">
        <el-form-item label="会员等级">
          <el-select v-model="editForm.tier">
            <el-option label="免费版" value="free" />
            <el-option label="基础版" value="basic" />
            <el-option label="专业版" value="pro" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="saving" @click="saveQuotaEdit">保存配额</el-button>
    </section>

    <section class="raw-block">
      <h3>完整字段</h3>
      <pre class="raw-json">{{ selectedJson }}</pre>
    </section>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useApi, type Row } from '../composables/useApi';

type SectionKey = 'users' | 'devices' | 'sync' | 'quotas' | 'audits' | 'settings';

const props = defineProps<{
  token: string;
  activeSection: SectionKey;
}>();

const emit = defineEmits<{
  'refresh-required': [];
}>();

const { apiGet, apiPatch, formatNumber, formatDuration } = useApi(ref(props.token));

const detailVisible = ref(false);
const selected = ref<Row | null>(null);
const editForm = reactive<Row>({});
const saving = ref(false);

const drawerTitle = computed(() => (selected.value ? `${props.activeSection === 'users' ? '用户管理' : props.activeSection === 'quotas' ? '配额与计费' : '详情'} #${selected.value.id || ''}` : '详情'));
const selectedJson = computed(() => JSON.stringify(selected.value || {}, null, 2));

function prepareUserEditForm() {
  Object.keys(editForm).forEach((key) => delete editForm[key]);
  if (!selected.value) return;
  Object.assign(editForm, {
    is_author: Number(selected.value.is_author || 0),
    is_admin: Number(selected.value.is_admin || 0),
    status: selected.value.status || 'active',
  });
}

function prepareQuotaEditForm() {
  Object.keys(editForm).forEach((key) => delete editForm[key]);
  if (!selected.value) return;
  Object.assign(editForm, {
    tier: selected.value.tier || 'free',
  });
}

async function open(row: Row) {
  try {
    if (props.activeSection === 'users') {
      selected.value = await apiGet(`/admin/users/${row.id}`);
      prepareUserEditForm();
    } else if (props.activeSection === 'quotas') {
      selected.value = { ...row };
      prepareQuotaEditForm();
    } else {
      selected.value = { ...row };
    }
    detailVisible.value = true;
  } catch {
    ElMessage.error('读取详情失败');
  }
}

async function openQuotaEdit(row: Row) {
  selected.value = { ...row };
  prepareUserEditForm();
  detailVisible.value = true;
}

async function saveUserEdit() {
  if (!selected.value) return;
  saving.value = true;
  try {
    selected.value = (await apiPatch(`/admin/users/${selected.value.id}`, editForm)).item;
    prepareUserEditForm();
    emit('refresh-required');
    ElMessage.success('已保存');
  } catch {
    ElMessage.error('保存失败');
  } finally {
    saving.value = false;
  }
}

async function saveQuotaEdit() {
  if (!selected.value) return;
  saving.value = true;
  try {
    await apiPatch(`/admin/users/${selected.value.user_id || selected.value.id}`, editForm);
    ElMessage.success('配额已保存');
    detailVisible.value = false;
    emit('refresh-required');
  } catch {
    ElMessage.error('保存失败');
  } finally {
    saving.value = false;
  }
}

defineExpose({ open, openQuotaEdit });
</script>

<style scoped>
.edit-block {
  padding-bottom: 24px;
  border-bottom: 1px solid #d8e5ef;
}

.usage-block {
  padding: 22px 0;
  border-bottom: 1px solid #d8e5ef;
}

.usage-block h3 {
  margin-bottom: 14px;
}

.usage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.usage-grid div {
  padding: 12px;
  border: 1px solid #d8e5ef;
  border-radius: 6px;
  background: #f7fafc;
}

.usage-grid span,
.usage-grid strong {
  display: block;
}

.usage-grid span {
  color: #617a91;
  font-size: 13px;
}

.usage-grid strong {
  margin-top: 6px;
  font-size: 18px;
}

.raw-block {
  padding-top: 22px;
}

.raw-json {
  max-height: 420px;
  overflow: auto;
  padding: 14px;
  border-radius: 6px;
  background: #0d2234;
  color: #d8efff;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
