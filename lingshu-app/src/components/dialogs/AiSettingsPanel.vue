<template>
  <el-dialog
    v-model="visible"
    title="AI 设置"
    width="880px"
    class="ai-settings-dialog"
    :close-on-click-modal="false"
    @open="loadSettings"
    @close="$emit('close')"
  >
    <div
      v-if="!auth.isLoggedIn"
      class="ai-login-gate"
    >
      <el-empty
        description="AI 设置需要登录后使用"
        :image-size="64"
      >
        <el-button
          type="primary"
          @click="useEventBus().emit('lingshu:open-login')"
        >
          登录
        </el-button>
      </el-empty>
    </div>
    <div
      v-else
      class="ai-settings"
    >
      <section class="profile-template">
        <div class="section-title">
          通用模板
        </div>
        <el-form
          :model="templateProfile"
          label-position="top"
          size="small"
          class="template-grid"
        >
          <el-form-item label="启用远程">
            <el-switch v-model="templateProfile.remote_enabled" />
          </el-form-item>
          <el-form-item label="模型厂商">
            <el-select
              v-model="templateProfile.provider"
              class="model-select"
              filterable
              placeholder="选择模型服务商"
              @change="applyProviderPreset(templateProfile)"
            >
              <el-option
                v-for="provider in MODEL_PROVIDERS"
                :key="provider.value"
                :label="provider.label"
                :value="provider.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="templateProfile.api_key"
              type="password"
              show-password
              placeholder="sk-..."
            />
          </el-form-item>
          <el-form-item label="Base URL">
            <el-input
              v-model="templateProfile.base_url"
              placeholder="https://api.openai.com/v1"
            />
          </el-form-item>
          <el-form-item label="模型">
            <el-select
              v-model="templateProfile.model"
              class="model-select"
              filterable
              allow-create
              default-first-option
              placeholder="选择或输入模型"
              @change="applyModelPreset(templateProfile)"
            >
              <el-option
                v-for="preset in modelPresetsForProvider(templateProfile.provider)"
                :key="preset.value"
                :label="preset.label"
                :value="preset.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="思考模式">
            <el-switch
              v-model="templateProfile.thinking_enabled"
              active-text="开"
              inactive-text="关"
            />
          </el-form-item>
          <el-form-item
            v-if="templateProfile.thinking_enabled"
            label="思考预算"
          >
            <el-input-number
              v-model="templateProfile.thinking_budget_tokens"
              :min="1024"
              :max="200000"
              :step="1024"
            />
          </el-form-item>
        </el-form>
        <div class="template-actions">
          <el-button @click="copyTemplateToAll">
            复制模板到全部用途
          </el-button>
          <el-button @click="triggerImport">
            导入配置
          </el-button>
          <input
            ref="importInput"
            class="hidden-file"
            type="file"
            accept=".json,application/json"
            @change="onImportConfig"
          >
        </div>
      </section>

      <section class="purpose-editor">
        <el-tabs
          v-model="activePurpose"
          tab-position="left"
          class="purpose-tabs"
        >
          <el-tab-pane
            v-for="purpose in purposeList"
            :key="purpose.key"
            :name="purpose.key"
            :label="purpose.label"
          >
            <div
              v-if="activeProfile"
              class="purpose-pane"
            >
              <div class="purpose-heading">
                <div>
                  <h3>{{ purpose.label }}</h3>
                  <p>{{ purpose.description }}</p>
                </div>
                <el-tag
                  :type="activeProfile.remote_enabled ? 'success' : 'info'"
                  effect="plain"
                >
                  {{ activeProfile.remote_enabled ? '已启用' : '未启用' }}
                </el-tag>
              </div>

              <el-form
                :model="activeProfile"
                label-width="92px"
                size="small"
                class="purpose-form"
              >
                <el-form-item label="启用远程">
                  <el-switch v-model="activeProfile.remote_enabled" />
                </el-form-item>
                <el-form-item label="API Key">
                  <el-input
                    v-model="activeProfile.api_key"
                    type="password"
                    show-password
                    placeholder="sk-..."
                  />
                </el-form-item>
                <el-form-item label="Base URL">
                  <el-input
                    v-model="activeProfile.base_url"
                    placeholder="https://api.openai.com/v1"
                  />
                </el-form-item>
                <el-form-item label="模型">
                  <el-select
                    v-model="activeProfile.model"
                    class="model-select"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="选择或输入模型"
                    @change="applyModelPreset(activeProfile)"
                  >
                    <el-option
                      v-for="preset in modelPresetsForProvider(activeProfile.provider)"
                      :key="preset.value"
                      :label="preset.label"
                      :value="preset.value"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="温度">
                  <el-slider
                    v-model="activeProfile.temperature"
                    :min="0"
                    :max="2"
                    :step="0.1"
                    show-input
                  />
                </el-form-item>
                <el-form-item label="Max Tokens">
                  <el-input-number
                    v-model="activeProfile.max_tokens"
                    :min="256"
                    :max="200000"
                    :step="512"
                  />
                </el-form-item>
                <el-form-item label="思考模式">
                  <el-switch
                    v-model="activeProfile.thinking_enabled"
                    active-text="开"
                    inactive-text="关"
                  />
                </el-form-item>
                <el-form-item
                  v-if="activeProfile.thinking_enabled"
                  label="思考预算"
                >
                  <el-input-number
                    v-model="activeProfile.thinking_budget_tokens"
                    :min="1024"
                    :max="200000"
                    :step="1024"
                  />
                  <span class="form-hint">Token 数，控制思考深度</span>
                </el-form-item>
              </el-form>

              <div class="purpose-actions">
                <el-button @click="copyCurrentToTemplate">
                  复制当前到模板
                </el-button>
                <el-button
                  :loading="testing"
                  @click="testCurrent"
                >
                  测试当前用途
                </el-button>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>
    </div>

    <template #footer>
      <el-button @click="visible = false">
        取消
      </el-button>
      <el-button
        type="primary"
        :loading="saving"
        @click="saveSettings"
      >
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useEventBus } from '../../composables/useEventBus';
import {
  DEFAULT_AI_PROVIDER,
  DEFAULT_BASE_URL,
  MODEL_PROVIDERS,
  applyModelPreset,
  applyProviderPreset,
  modelPresetsForProvider,
} from '../../constants/aiProviders';
import { useAuthStore } from '../../stores/auth';
import api from '../../utils/api';

const auth = useAuthStore();

const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'close']);

const visible = ref(props.modelValue);
watch(() => props.modelValue, v => { visible.value = v; });
watch(visible, v => emit('update:modelValue', v));

const FALLBACK_PURPOSES = [
  ['writing', '写作生成', '章节草稿生成、续写、润色'],
  ['outline', '同步大纲', '根据正文同步章节或书籍大纲'],
  ['detector', 'AI概率检测', '检测正文 AI 生成痕迹'],
  ['correction', 'AI纠错', '中文错别字检测与修改建议'],
  ['import', '智能导入分类', '判断导入文档类型和章节结构'],
  ['skills', 'Skills提炼', '从参考文本提炼写作约束'],
  ['book_analysis', '全书分析', '三级全书分析流程'],
  ['review', '长篇生成/校验', '审查、校验和多智能体长篇流程'],
  ['chat', 'AI 对话', '多轮对话式写作辅助'],
].map(([key, label, description]) => ({ key, label, description }));

const purposeList = ref(FALLBACK_PURPOSES);
const activePurpose = ref('writing');
const saving = ref(false);
const testing = ref(false);
const importInput = ref(null);
const form = ref(createDefaultSettings());
const templateProfile = ref(createProfile());

const activeProfile = computed(() => form.value.profiles?.[activePurpose.value] || null);

async function loadSettings() {
  try {
    const { data } = await api.get('/settings/ai');
    applySettings(data);
  } catch (e) {
    ElMessage.warning(e.response?.data?.detail || e.message || 'AI 设置接口暂不可用，已使用本地默认值');
    form.value = createDefaultSettings();
  }
}

function applySettings(data) {
  const next = createDefaultSettings();
  next.version = data.version || next.version;
  next.request_retries = data.request_retries ?? next.request_retries;
  next.book_analysis_concurrency = data.book_analysis_concurrency ?? next.book_analysis_concurrency;
  next.book_analysis_fast_extra_body = data.book_analysis_fast_extra_body || '';
  next.book_analysis_final_extra_body = data.book_analysis_final_extra_body || '';

  const purposes = data.purposes || {};
  purposeList.value = Object.keys(next.profiles).map(key => ({
    key,
    label: data.profiles?.[key]?.label || purposes[key]?.label || FALLBACK_PURPOSES.find(p => p.key === key)?.label || key,
    description: data.profiles?.[key]?.description || purposes[key]?.description || FALLBACK_PURPOSES.find(p => p.key === key)?.description || '',
  }));

  for (const key of Object.keys(next.profiles)) {
    next.profiles[key] = normalizeProfile(data.profiles?.[key]);
  }
  form.value = next;
  templateProfile.value = normalizeProfile(next.profiles.writing);
}

function triggerImport() {
  importInput.value?.click();
}

async function onImportConfig(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    const text = await file.text();
    const json = JSON.parse(text);
    applySettings(json);
    ElMessage.success('配置已导入，保存后生效');
  } catch (e) {
    ElMessage.error(e.message || '配置文件格式无效');
  }
}

function copyTemplateToAll() {
  for (const key of Object.keys(form.value.profiles)) {
    form.value.profiles[key] = normalizeProfile(templateProfile.value);
  }
  ElMessage.success('已复制到全部用途');
}

function copyCurrentToTemplate() {
  if (!activeProfile.value) return;
  templateProfile.value = normalizeProfile(activeProfile.value);
}

async function testCurrent() {
  if (!activeProfile.value) return;
  testing.value = true;
  try {
    const { data } = await api.post('/settings/ai/test', {
      purpose: activePurpose.value,
      profile: activeProfile.value,
    });
    if (data.ok) ElMessage.success(data.message || '配置可用');
    else ElMessage.warning(data.message || '配置不可用');
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '测试失败');
  } finally {
    testing.value = false;
  }
}

async function saveSettings() {
  saving.value = true;
  try {
    const payload = {
      ...form.value,
      profiles: Object.fromEntries(
        Object.entries(form.value.profiles).map(([key, profile]) => [key, normalizeProfile(profile)]),
      ),
    };
    const { data } = await api.put('/settings/ai', payload);
    applySettings(data);
    ElMessage.success('AI 设置已保存');
    visible.value = false;
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '保存失败');
  } finally {
    saving.value = false;
  }
}

function createDefaultSettings() {
  const profiles = {};
  for (const purpose of FALLBACK_PURPOSES) profiles[purpose.key] = createProfile();
  return {
    version: 'ai_profiles_v3_book_analysis_pyramid',
    profiles,
    request_retries: 2,
    book_analysis_concurrency: 3,
    book_analysis_fast_extra_body: '',
    book_analysis_final_extra_body: '',
  };
}

function createProfile() {
  return {
    remote_enabled: false,
    provider: DEFAULT_AI_PROVIDER,
    api_key: '',
    base_url: DEFAULT_BASE_URL,
    model: '',
    temperature: 0.7,
    max_tokens: 4096,
    thinking_enabled: false,
    thinking_budget_tokens: 10000,
  };
}

function normalizeProfile(profile = {}) {
  return {
    ...createProfile(),
    remote_enabled: Boolean(profile.remote_enabled),
    provider: profile.provider || DEFAULT_AI_PROVIDER,
    api_key: profile.api_key || '',
    base_url: profile.base_url || DEFAULT_BASE_URL,
    model: profile.model || '',
    temperature: Number.isFinite(Number(profile.temperature)) ? Number(profile.temperature) : 0.7,
    max_tokens: Number.isFinite(Number(profile.max_tokens)) ? Number(profile.max_tokens) : 4096,
    thinking_enabled: Boolean(profile.thinking_enabled),
    thinking_budget_tokens: Number.isFinite(Number(profile.thinking_budget_tokens)) ? Number(profile.thinking_budget_tokens) : 10000,
  };
}
</script>

<style scoped>
.ai-login-gate {
  display: flex;
  justify-content: center;
  padding: 40px 0;
}
.ai-settings {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.profile-template,
.purpose-editor {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  padding: 12px;
}

.section-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  align-items: end;
}

.template-grid :deep(.el-form-item) {
  margin-bottom: 0;
}

.template-actions,
.purpose-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.hidden-file {
  display: none;
}

.model-select {
  width: 100%;
}

.template-grid :deep(.el-input-number) {
  width: 100%;
}

.form-hint {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-secondary);
}

.purpose-tabs {
  height: 420px;
}

.purpose-pane {
  padding: 0 6px 0 14px;
}

.purpose-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.purpose-heading h3 {
  margin: 0;
  font-size: 17px;
  line-height: 1.3;
  color: var(--text-primary);
}

.purpose-heading p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.purpose-form {
  max-width: 600px;
}
</style>
