/**
 * 主题 Store — 4 套预设主题切换
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';

const THEMES = {
  white: { label: '白昼', className: '' },
  'light-blue': { label: '浅蓝', className: 'theme-light-blue' },
  night: { label: '暗夜', className: 'theme-night' },
  sepia: { label: '羊皮纸', className: 'theme-sepia' },
};

export const useThemeStore = defineStore('theme', () => {
  const saved = localStorage.getItem('lingshu_theme') || 'white';
  const current = ref(saved in THEMES ? saved : 'white');

  const themes = THEMES;
  const currentLabel = ref(THEMES[current.value].label);

  function apply(newTheme) {
    if (!(newTheme in THEMES)) return;
    // 移除旧主题 class
    Object.values(THEMES).forEach(t => {
      if (t.className) document.documentElement.classList.remove(t.className);
    });
    // 应用新主题
    current.value = newTheme;
    currentLabel.value = THEMES[newTheme].label;
    const cls = THEMES[newTheme].className;
    if (cls) document.documentElement.classList.add(cls);
    localStorage.setItem('lingshu_theme', newTheme);
  }

  function toggle() {
    const keys = Object.keys(THEMES);
    const idx = keys.indexOf(current.value);
    apply(keys[(idx + 1) % keys.length]);
  }

  // 初始化时应用保存的主题
  apply(current.value);

  return { current, currentLabel, themes, apply, toggle };
});
