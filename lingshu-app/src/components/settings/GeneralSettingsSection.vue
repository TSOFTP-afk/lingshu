<template>
  <section class="settings-section general-settings-section">
    <div class="section-heading">
      <div>
        <h2>本机通用</h2>
        <p>这些设置只保存在当前电脑，影响工作台主题、编辑区文字和三栏布局。</p>
      </div>
      <div class="heading-actions">
        <el-button @click="resetDefaults">
          恢复默认
        </el-button>
        <el-button
          type="primary"
          @click="saveSettings"
        >
          保存设置
        </el-button>
      </div>
    </div>

    <div class="settings-panel">
      <div class="panel-title">
        外观
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-name">
            主题
          </div>
          <div class="setting-desc">
            设置中心和工作台会同时切换到同一主题。
          </div>
        </div>
        <el-select
          v-model="form.theme"
          class="setting-control"
          @change="onThemeChange"
        >
          <el-option
            v-for="(item, key) in themes.themes"
            :key="key"
            :label="item.label"
            :value="key"
          />
        </el-select>
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-name">
            启动时进入专注模式
          </div>
          <div class="setting-desc">
            下次进入工作台时自动隐藏弱相关干扰项。
          </div>
        </div>
        <el-switch v-model="form.focusDefault" />
      </div>
    </div>

    <div class="settings-panel">
      <div class="panel-title">
        编辑器
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-name">
            正文字号
          </div>
          <div class="setting-desc">
            影响章节正文编辑区。
          </div>
        </div>
        <el-input-number
          v-model="form.fontSize"
          :min="12"
          :max="24"
          :step="1"
        />
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-name">
            正文行高
          </div>
          <div class="setting-desc">
            用于控制单行文字高度，不额外改变段落空行内容。
          </div>
        </div>
        <div class="slider-control">
          <el-slider
            v-model="form.lineHeight"
            :min="130"
            :max="190"
            :step="5"
            show-input
          />
          <span>%</span>
        </div>
      </div>
    </div>

    <div class="settings-panel">
      <div class="panel-title">
        工作台布局
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-name">
            左侧书籍栏宽度
          </div>
          <div class="setting-desc">
            调整书籍管理区域占比。
          </div>
        </div>
        <el-input-number
          v-model="form.leftWidth"
          :min="18"
          :max="35"
          :step="1"
        />
      </div>
      <div class="setting-row">
        <div>
          <div class="setting-name">
            右侧工具栏宽度
          </div>
          <div class="setting-desc">
            调整生成、审查、角色、世界观等工具区域占比。
          </div>
        </div>
        <el-input-number
          v-model="form.rightWidth"
          :min="20"
          :max="40"
          :step="1"
        />
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useEventBus } from '../../composables/useEventBus';
import { useThemeStore } from '../../stores/theme';

const DEFAULTS = {
  theme: 'white',
  fontSize: 15,
  lineHeight: 160,
  leftWidth: 22,
  rightWidth: 28,
  focusDefault: false,
};

const themes = useThemeStore();
const form = ref(readSettings());

onMounted(() => {
  form.value.theme = themes.current;
  applyEditorCss(form.value);
});

watch(() => themes.current, (value) => {
  if (form.value.theme !== value) form.value.theme = value;
});

function readSettings() {
  return {
    theme: themes.current || DEFAULTS.theme,
    fontSize: readNumber('lingshu_font_size', DEFAULTS.fontSize),
    lineHeight: readNumber('lingshu_line_height', DEFAULTS.lineHeight),
    leftWidth: readNumber('lingshu_left_width', DEFAULTS.leftWidth),
    rightWidth: readNumber('lingshu_right_width', DEFAULTS.rightWidth),
    focusDefault: localStorage.getItem('lingshu_focus_default') === '1',
  };
}

function onThemeChange(theme) {
  themes.apply(theme);
  form.value.theme = themes.current;
}

function readNumber(key, fallback) {
  const value = Number.parseInt(localStorage.getItem(key) || '', 10);
  return Number.isFinite(value) ? value : fallback;
}

function resetDefaults() {
  form.value = { ...DEFAULTS };
  saveSettings('已恢复默认设置');
}

function saveSettings(message = '本机通用设置已保存') {
  const next = {
    ...form.value,
    leftWidth: clamp(Number(form.value.leftWidth), 18, 35),
    rightWidth: clamp(Number(form.value.rightWidth), 20, 40),
    fontSize: clamp(Number(form.value.fontSize), 12, 24),
    lineHeight: clamp(Number(form.value.lineHeight), 130, 190),
  };
  if (next.leftWidth + next.rightWidth > 70) {
    next.rightWidth = 70 - next.leftWidth;
  }
  form.value = next;

  themes.apply(next.theme);
  localStorage.setItem('lingshu_font_size', String(next.fontSize));
  localStorage.setItem('lingshu_line_height', String(next.lineHeight));
  localStorage.setItem('lingshu_left_width', String(next.leftWidth));
  localStorage.setItem('lingshu_right_width', String(next.rightWidth));
  localStorage.setItem('lingshu_focus_default', next.focusDefault ? '1' : '0');
  applyEditorCss(next);
  document.body.classList.toggle('focus-mode', next.focusDefault);
  useEventBus().emit('lingshu:view-settings-updated', next);
  ElMessage.success(message);
}

function applyEditorCss(settings) {
  const fontSize = clamp(Number(settings.fontSize), 12, 24);
  const lineHeight = clamp(Number(settings.lineHeight), 130, 190);
  document.documentElement.style.setProperty('--editor-font-size', `${fontSize}px`);
  document.documentElement.style.setProperty('--editor-line-height', `${Math.round(fontSize * lineHeight / 100)}px`);
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}
</script>

<style scoped>
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
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

.heading-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.settings-panel {
  border: 1px solid var(--settings-border);
  border-radius: 8px;
  background: var(--settings-panel);
  overflow: hidden;
}

.panel-title {
  padding: 14px 18px;
  border-bottom: 1px solid var(--settings-border);
  color: var(--settings-text);
  font-size: 15px;
  font-weight: 700;
}

.setting-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 320px);
  align-items: center;
  gap: 24px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--settings-border-soft);
}

.setting-row:last-child {
  border-bottom: 0;
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

.setting-control {
  width: 100%;
}

.slider-control {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  color: var(--settings-muted);
}

@media (max-width: 780px) {
  .section-heading {
    flex-direction: column;
  }

  .setting-row {
    grid-template-columns: 1fr;
    gap: 10px;
  }
}
</style>
