<template>
  <div
    class="settings-view"
    :class="themeClass"
  >
    <aside class="settings-sidebar">
      <div class="profile-block">
        <div class="profile-avatar">
          {{ accountInitial }}
        </div>
        <div class="profile-meta">
          <strong>{{ accountName }}</strong>
          <span>{{ auth.isLoggedIn ? 'AI 已解锁' : 'AI 需登录' }}</span>
        </div>
      </div>

      <el-input
        v-model="searchQuery"
        class="settings-search"
        :prefix-icon="Search"
        placeholder="Ctrl+F 搜索"
        clearable
        @keydown.enter.prevent="jumpToFirstMatch"
      />

      <nav class="settings-nav">
        <template
          v-for="group in visibleGroups"
          :key="group.key"
        >
          <div class="nav-group">
            <button
              v-for="item in group.items"
              :key="item.key"
              class="nav-item"
              :class="{ active: activeSection === item.key }"
              type="button"
              @click="goSection(item.key)"
            >
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </button>
          </div>
        </template>
        <div
          v-if="!visibleGroups.length"
          class="nav-empty"
        >
          没有匹配的设置项
        </div>
      </nav>
    </aside>

    <main class="settings-main">
      <div class="settings-topbar">
        <el-button
          class="back-button"
          @click="backToWorkspace"
        >
          <el-icon><ArrowLeft /></el-icon>
          <span>返回工作台</span>
        </el-button>
        <span class="settings-path">设置 / {{ activeItem?.label || '账号' }}</span>
      </div>

      <div class="settings-content">
        <AccountSettingsSection v-if="activeSection === 'account'" />
        <GeneralSettingsSection v-else-if="activeSection === 'general'" />
        <AiSettingsSection v-else-if="activeSection === 'ai'" />
        <section
          v-else-if="activeSection === 'import'"
          class="settings-section"
        >
          <div class="section-heading">
            <div>
              <h2>导入设置</h2>
              <p>控制作品导入时的拆分与分卷行为。</p>
            </div>
          </div>
          <div class="settings-panel">
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  启用分卷功能
                </div>
                <div class="setting-desc">
                  开启后，导入时会根据"第X卷"标题自动划分分卷结构；关闭则所有章节按顺序导入"未分卷"中。
                </div>
              </div>
              <el-switch v-model="importVolumeEnabled" />
            </div>
          </div>
        </section>

        <section
          v-else-if="activeSection === 'chat'"
          class="settings-section"
        >
          <div class="section-heading">
            <div>
              <h2>对话</h2>
              <p>AI 对话的身份选择已经恢复到对话窗口内；这里作为默认项配置入口。</p>
            </div>
          </div>
          <div class="settings-panel">
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  身份选择
                </div>
                <div class="setting-desc">
                  当前作品人物会在 AI 对话窗口中作为“我扮演 / AI 扮演”选项加载。
                </div>
              </div>
              <el-button @click="openChat">
                打开 AI 对话
              </el-button>
            </div>
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  上下文范围
                </div>
                <div class="setting-desc">
                  当前版本会自动带入当前作品和当前章节内容。
                </div>
              </div>
              <el-tag effect="plain">
                自动
              </el-tag>
            </div>
          </div>
        </section>

        <section
          v-else-if="activeSection === 'references'"
          class="settings-section"
        >
          <div class="section-heading">
            <div>
              <h2>索引与文档</h2>
              <p>集中管理参考书、导入资料和后续索引刷新能力。</p>
            </div>
          </div>
          <div class="settings-panel">
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  参考书库
                </div>
                <div class="setting-desc">
                  导入参考资料、绑定作品、启停上下文和查看分段。
                </div>
              </div>
              <el-button
                type="primary"
                @click="showReference = true"
              >
                打开参考书库
              </el-button>
            </div>
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  索引刷新
                </div>
                <div class="setting-desc">
                  后续将把重建索引、清理无效分段等维护项放在这里。
                </div>
              </div>
              <el-tag effect="plain">
                待接入
              </el-tag>
            </div>
          </div>
        </section>

        <section
          v-else-if="activeSection === 'skills'"
          class="settings-section"
        >
          <div class="section-heading">
            <div>
              <h2>Skill库配置</h2>
              <p>统一放置技能索引、命令入口和技能提炼设置。</p>
            </div>
          </div>
          <div class="settings-panel">
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  Skills 提炼用途
                </div>
                <div class="setting-desc">
                  模型与 API 配置在 AI 配置的“Skills提炼”用途中维护。
                </div>
              </div>
              <el-button @click="goSection('ai')">
                配置 Skills 模型
              </el-button>
            </div>
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  所有写作 Skill
                </div>
                <div class="setting-desc">
                  查看和管理当前导入的所有写作技能，包括启停和参数调整。
                </div>
              </div>
              <el-button @click="showSkills = true">
                查看 Skill
              </el-button>
            </div>
          </div>
        </section>

        <section
          v-else-if="activeSection === 'rules'"
          class="settings-section"
        >
          <div class="section-heading">
            <div>
              <h2>规则与记忆</h2>
              <p>后续放置作品规则、长期记忆、Truth File 和写作禁区等配置。</p>
            </div>
          </div>
          <div class="settings-panel empty-panel">
            <span>规则与记忆接口还未完成迁移，入口已预留。</span>
          </div>
        </section>

        <section
          v-else-if="activeSection === 'data'"
          class="settings-section"
        >
          <div class="section-heading">
            <div>
              <h2>数据与备份</h2>
              <p>作品导入导出仍是工作台操作；数据目录、备份和恢复会逐步集中到这里。</p>
            </div>
          </div>
          <div class="settings-panel">
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  API 入口
                </div>
                <div class="setting-desc">
                  当前前端连接到 {{ apiBaseUrl }}。
                </div>
              </div>
              <el-tag effect="plain">
                {{ apiBaseUrl }}
              </el-tag>
            </div>
            <div class="setting-row">
              <div>
                <div class="setting-name">
                  作品导入
                </div>
                <div class="setting-desc">
                  导入作品仍放在工作台书籍管理流程里。
                </div>
              </div>
              <el-button @click="openImport">
                回到工作台导入
              </el-button>
            </div>
          </div>
        </section>

        <section
          v-else-if="activeSection === 'about'"
          class="settings-section"
        >
          <div class="section-heading">
            <div>
              <h2>关于</h2>
              <p>当前前端版本和本地运行信息。</p>
            </div>
          </div>
          <div class="settings-panel">
            <div class="setting-row compact">
              <div>
                <div class="setting-name">
                  灵枢创作工作台
                </div>
                <div class="setting-desc">
                  Vue / Electron 桌面迁移版
                </div>
              </div>
              <el-tag effect="plain">
                v{{ packageInfo.version }}
              </el-tag>
            </div>
            <div class="setting-row compact">
              <div>
                <div class="setting-name">
                  前端地址
                </div>
                <div class="setting-desc">
                  {{ locationHref }}
                </div>
              </div>
              <el-tag effect="plain">
                运行中
              </el-tag>
            </div>
          </div>
        </section>
      </div>
    </main>

    <ReferenceBooksView v-model="showReference" />

    <el-dialog
      v-model="showSkills"
      title="所有写作 Skill"
      width="620px"
      destroy-on-close
    >
      <div
        v-if="skillsLoading"
        class="skills-loading"
      >
        <el-icon class="is-loading">
          <Loading />
        </el-icon>
        <span>正在加载 Skills...</span>
      </div>
      <div
        v-else-if="skillsList.length"
        class="skills-list-dialog"
      >
        <div
          v-for="skill in skillsList"
          :key="skill.id"
          class="skill-card"
        >
          <div class="skill-card-head">
            <span class="skill-card-name">{{ skill.name }}</span>
            <el-tag
              size="small"
              effect="plain"
            >
              {{ skill.category || '未分类' }}
            </el-tag>
          </div>
          <div class="skill-card-summary">
            {{ skill.summary }}
          </div>
          <div
            v-if="skill.instruction_text"
            class="skill-card-instruction"
          >
            {{ skill.instruction_text }}
          </div>
          <div
            v-if="skill.source_title"
            class="skill-card-source"
          >
            来源：{{ skill.source_title }}
          </div>
        </div>
      </div>
      <el-empty
        v-else
        description="暂无 Skill"
        :image-size="50"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  ArrowLeft,
  ChatDotRound,
  Connection,
  Files,
  FolderOpened,
  InfoFilled,
  Loading,
  MagicStick,
  Notebook,
  Search,
  Setting,
  Upload,
  User,
} from '@element-plus/icons-vue';
import { useEventBus } from '../../composables/useEventBus';
import { useAuthStore } from '../../stores/auth';
import { useThemeStore } from '../../stores/theme';
import { API_BASE_URL } from '../../utils/api';
import api from '../../utils/api';
import AccountSettingsSection from './AccountSettingsSection.vue';
import AiSettingsSection from './AiSettingsSection.vue';
import GeneralSettingsSection from './GeneralSettingsSection.vue';
import ReferenceBooksView from '../dialogs/ReferenceBooksView.vue';
import packageInfo from '../../../package.json';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const theme = useThemeStore();
const searchQuery = ref('');
const showReference = ref(false);
const showSkills = ref(false);
const skillsList = ref([]);
const skillsLoading = ref(false);
const apiBaseUrl = API_BASE_URL;
const locationHref = typeof window !== 'undefined' ? window.location.href : '';

// 导入设置
const IMPORT_VOLUME_KEY = 'lingshu:import:volumeEnabled';
const importVolumeEnabled = ref(
  localStorage.getItem(IMPORT_VOLUME_KEY) !== 'false',
);

watch(importVolumeEnabled, (val) => {
  localStorage.setItem(IMPORT_VOLUME_KEY, String(val));
});

const navGroups = [
  {
    key: 'base',
    items: [
      { key: 'account', label: '账号', icon: User, keywords: '账户 本地 登录 注册 云端 服务器 令牌' },
      { key: 'general', label: '本机通用', icon: Setting, keywords: '主题 字号 行高 布局 专注' },
    ],
  },
  {
    key: 'ai',
    items: [
      { key: 'ai', label: 'AI 配置', icon: Connection, keywords: 'api key base url 模型 用途 生成 审查' },
      { key: 'import', label: '导入', icon: Upload, keywords: '导入 分卷 章节 拆分' },
      { key: 'chat', label: '对话', icon: ChatDotRound, keywords: '身份 扮演 上下文 聊天' },
    ],
  },
  {
    key: 'knowledge',
    items: [
      { key: 'references', label: '索引与文档', icon: FolderOpened, keywords: '参考书 导入 索引 文档 分段' },
      { key: 'skills', label: 'Skill库配置', icon: MagicStick, keywords: 'skill 技能 命令 提炼' },
      { key: 'rules', label: '规则与记忆', icon: Notebook, keywords: '规则 记忆 truth file 设定' },
    ],
  },
  {
    key: 'system',
    items: [
      { key: 'data', label: '数据与备份', icon: Files, keywords: '数据 备份 恢复 导入 导出' },
      { key: 'about', label: '关于', icon: InfoFilled, keywords: '版本 环境 状态' },
    ],
  },
];

const flatItems = navGroups.flatMap(group => group.items);
const activeSection = computed(() => {
  const section = String(route.params.section || 'account');
  return flatItems.some(item => item.key === section) ? section : 'account';
});
const activeItem = computed(() => flatItems.find(item => item.key === activeSection.value));
const accountName = computed(() => auth.user?.display_name || auth.user?.username || '灵枢本地用户');
const accountInitial = computed(() => String(accountName.value || '灵').trim().slice(0, 1).toUpperCase() || '灵');
const themeClass = computed(() => `settings-theme-${theme.current || 'white'}`);

const visibleGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase();
  if (!query) return navGroups;
  return navGroups
    .map(group => ({
      ...group,
      items: group.items.filter(item => {
        const haystack = `${item.label} ${item.key} ${item.keywords}`.toLowerCase();
        return haystack.includes(query);
      }),
    }))
    .filter(group => group.items.length);
});

function goSection(key) {
  router.push(key === 'account' ? '/settings' : `/settings/${key}`);
}

function jumpToFirstMatch() {
  const first = visibleGroups.value[0]?.items?.[0];
  if (first) goSection(first.key);
}

function backToWorkspace() {
  router.push(localStorage.getItem('lingshu_last_workspace_path') || '/workspace');
}

function openChat() {
  router.push(localStorage.getItem('lingshu_last_workspace_path') || '/workspace');
  setTimeout(() => useEventBus().emit('lingshu:open-chat'), 80);
}

function openImport() {
  router.push(localStorage.getItem('lingshu_last_workspace_path') || '/workspace');
  setTimeout(() => useEventBus().emit('lingshu:import'), 80);
}

async function loadSkills() {
  skillsLoading.value = true;
  try {
    const { data } = await api.get('/workspace/skills');
    skillsList.value = data.items || [];
  } catch {
    skillsList.value = [];
  } finally {
    skillsLoading.value = false;
  }
}

onMounted(loadSkills);
</script>

<style scoped>
.settings-view {
  --settings-bg: var(--bg-secondary);
  --settings-sidebar: var(--bg-primary);
  --settings-panel: var(--bg-primary);
  --settings-panel-soft: var(--bg-secondary);
  --settings-border: var(--border-color);
  --settings-border-soft: var(--border-light);
  --settings-text: var(--text-primary);
  --settings-muted: var(--text-secondary);
  --settings-dim: var(--text-placeholder);
  --settings-accent: var(--color-primary);
  --settings-topbar: color-mix(in srgb, var(--bg-primary) 92%, transparent);
  --settings-button-bg: var(--bg-secondary);
  --settings-button-hover: var(--bg-hover);
  --el-bg-color: var(--bg-primary);
  --el-bg-color-overlay: var(--bg-primary);
  --el-fill-color-blank: var(--bg-primary);
  --el-fill-color-light: var(--bg-secondary);
  --el-border-color: var(--border-color);
  --el-border-color-light: var(--border-light);
  --el-text-color-primary: var(--text-primary);
  --el-text-color-regular: var(--text-regular);
  --el-text-color-secondary: var(--text-secondary);
  --el-color-primary: var(--color-primary);
  display: grid;
  grid-template-columns: 308px minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--settings-bg);
  color: var(--settings-text);
}

.settings-theme-night {
  --settings-bg: #17191c;
  --settings-sidebar: #191b1f;
  --settings-panel: #1f2227;
  --settings-panel-soft: #23262c;
  --settings-border: #30343b;
  --settings-border-soft: #292d34;
  --settings-text: #f3f4f6;
  --settings-muted: #9ca3af;
  --settings-dim: #737b89;
  --settings-accent: #14b8a6;
  --settings-topbar: rgba(23, 25, 28, 0.92);
  --settings-button-bg: #252932;
  --settings-button-hover: #2f343d;
  --el-bg-color: #202329;
  --el-bg-color-overlay: #242830;
  --el-fill-color-blank: #202329;
  --el-fill-color-light: #262b33;
  --el-border-color: #3a404a;
  --el-border-color-light: #343a44;
  --el-text-color-primary: #f3f4f6;
  --el-text-color-regular: #cbd0d9;
  --el-text-color-secondary: #9ca3af;
  --el-color-primary: #14b8a6;
}

.settings-sidebar {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 18px 12px;
  border-right: 1px solid var(--settings-border-soft);
  background: var(--settings-sidebar);
}

.profile-block {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px 18px;
}

.profile-avatar {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  color: #fff;
  background: linear-gradient(135deg, #13b5a8, #4169e1);
  font-weight: 800;
}

.profile-avatar.large {
  width: 56px;
  height: 56px;
  font-size: 22px;
}

.profile-meta {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.profile-meta strong {
  color: var(--settings-text);
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-meta span {
  justify-self: start;
  padding: 2px 7px;
  border-radius: 5px;
  color: var(--settings-muted);
  background: var(--settings-panel-soft);
  font-size: 12px;
}

.settings-search {
  margin: 8px 0 16px;
}

.settings-nav {
  min-height: 0;
  overflow-y: auto;
}

.nav-group {
  padding: 10px 0;
  border-bottom: 1px solid var(--settings-border-soft);
}

.nav-item {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: center;
  width: 100%;
  height: 42px;
  padding: 0 12px;
  border: 0;
  border-radius: 6px;
  color: var(--settings-muted);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.nav-item:hover {
  color: var(--settings-text);
  background: var(--settings-button-hover);
  border: 1px solid var(--settings-accent);
}

.nav-item.active {
  color: var(--settings-accent);
  background: color-mix(in srgb, var(--settings-accent) 10%, transparent);
}

.nav-item span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-empty {
  padding: 18px 12px;
  color: var(--settings-dim);
  font-size: 13px;
}

.settings-main {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
}

.settings-topbar {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 28px;
  border-bottom: 1px solid var(--settings-border-soft);
  background: var(--settings-topbar);
  backdrop-filter: blur(10px);
}

.back-button {
  border-color: transparent;
  background: var(--settings-button-bg);
}

.settings-path {
  color: var(--settings-dim);
  font-size: 12px;
}

.settings-content {
  width: min(960px, calc(100% - 56px));
  margin: 0 auto;
  padding: 28px 0 64px;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-heading h2 {
  margin: 0;
  color: var(--settings-text);
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: 0;
}

.section-heading p {
  margin: 8px 0 0;
  color: var(--settings-muted);
  font-size: 13px;
  line-height: 1.7;
}

.settings-panel {
  border: 1px solid var(--settings-border);
  border-radius: 8px;
  background: var(--settings-panel);
  overflow: hidden;
}

.account-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border-bottom: 1px solid var(--settings-border);
}

.account-summary h3 {
  margin: 0;
  color: var(--settings-text);
  font-size: 17px;
}

.account-summary p {
  margin: 5px 0 0;
  color: var(--settings-muted);
  font-size: 13px;
}

.setting-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 20px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--settings-border-soft);
}

.setting-row:last-child {
  border-bottom: 0;
}

.setting-row.compact {
  min-height: 68px;
}

.setting-name {
  color: var(--settings-text);
  font-size: 14px;
  font-weight: 700;
}

.setting-desc {
  margin-top: 5px;
  color: var(--settings-muted);
  font-size: 12px;
  line-height: 1.6;
}

.empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  color: var(--settings-muted);
}

.settings-view :deep(.el-input__wrapper),
.settings-view :deep(.el-select__wrapper),
.settings-view :deep(.el-textarea__inner) {
  background: var(--el-fill-color-blank);
  box-shadow: 0 0 0 1px var(--el-border-color) inset;
}

.settings-view :deep(.el-input__wrapper:hover),
.settings-view :deep(.el-select__wrapper:hover),
.settings-view :deep(.el-textarea__inner:hover) {
  box-shadow: 0 0 0 1px var(--settings-accent) inset;
}

.settings-view :deep(.el-button) {
  border-color: var(--settings-border);
  background: var(--settings-button-bg);
  color: var(--settings-text);
}

.settings-view :deep(.el-button:hover) {
  border-color: var(--settings-accent);
  color: var(--settings-accent);
}

.settings-view :deep(.el-button--primary) {
  border-color: var(--settings-accent);
  background: var(--settings-accent);
  color: #fff;
}

.settings-view :deep(.el-tag) {
  background: var(--settings-panel-soft);
  border-color: var(--settings-border);
  color: var(--settings-muted);
}

.skills-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 0;
  color: var(--settings-muted);
  font-size: 14px;
}

.skills-list-dialog {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 50vh;
  overflow-y: auto;
}

.skill-card {
  padding: 12px 14px;
  border: 1px solid var(--settings-border-soft);
  border-radius: 6px;
  background: var(--settings-panel-soft);
}

.skill-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.skill-card-name {
  color: var(--settings-text);
  font-size: 14px;
  font-weight: 700;
}

.skill-card-summary {
  margin-top: 6px;
  color: var(--settings-muted);
  font-size: 13px;
  line-height: 1.5;
}

.skill-card-instruction {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 4px;
  background: var(--settings-bg);
  color: var(--settings-dim);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.skill-card-source {
  margin-top: 6px;
  color: var(--settings-dim);
  font-size: 11px;
}

@media (max-width: 900px) {
  .settings-view {
    grid-template-columns: 238px minmax(0, 1fr);
  }

  .settings-content {
    width: min(100% - 28px, 960px);
  }
}

@media (max-width: 680px) {
  .settings-view {
    grid-template-columns: 1fr;
  }

  .settings-sidebar {
    display: none;
  }

  .settings-topbar {
    padding: 0 14px;
  }

  .account-summary,
  .setting-row {
    grid-template-columns: 1fr;
  }
}
</style>
