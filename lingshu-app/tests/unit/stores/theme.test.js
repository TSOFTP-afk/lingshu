import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useThemeStore } from '../../../src/stores/theme';

describe('useThemeStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
    document.documentElement.className = '';
  });

  describe('初始状态', () => {
    it('默认主题为 white', () => {
      const store = useThemeStore();
      expect(store.current).toBe('white');
      expect(store.currentLabel).toBe('白昼');
    });

    it('从 localStorage 恢复保存的主题', () => {
      localStorage.setItem('lingshu_theme', 'night');

      const store = useThemeStore();
      expect(store.current).toBe('night');
      expect(store.currentLabel).toBe('暗夜');
    });

    it('localStorage 中无效主题回退为 white', () => {
      localStorage.setItem('lingshu_theme', 'invalid_theme');

      const store = useThemeStore();
      expect(store.current).toBe('white');
    });
  });

  describe('themes', () => {
    it('包含 4 套预设主题', () => {
      const store = useThemeStore();
      const keys = Object.keys(store.themes);
      expect(keys).toContain('white');
      expect(keys).toContain('light-blue');
      expect(keys).toContain('night');
      expect(keys).toContain('sepia');
      expect(keys).toHaveLength(4);
    });
  });

  describe('apply', () => {
    it('应用有效主题', () => {
      const store = useThemeStore();
      store.apply('night');

      expect(store.current).toBe('night');
      expect(store.currentLabel).toBe('暗夜');
    });

    it('应用主题时设置 CSS class', () => {
      const store = useThemeStore();
      store.apply('night');

      expect(document.documentElement.classList.contains('theme-night')).toBe(true);
    });

    it('应用无 className 的主题时移除其他主题 class', () => {
      const store = useThemeStore();
      store.apply('night');
      expect(document.documentElement.classList.contains('theme-night')).toBe(true);

      store.apply('white');
      expect(document.documentElement.classList.contains('theme-night')).toBe(false);
    });

    it('应用主题时持久化到 localStorage', () => {
      const store = useThemeStore();
      store.apply('sepia');

      expect(localStorage.getItem('lingshu_theme')).toBe('sepia');
    });

    it('切换主题时移除旧主题 class', () => {
      const store = useThemeStore();
      store.apply('light-blue');
      expect(document.documentElement.classList.contains('theme-light-blue')).toBe(true);

      store.apply('sepia');
      expect(document.documentElement.classList.contains('theme-light-blue')).toBe(false);
      expect(document.documentElement.classList.contains('theme-sepia')).toBe(true);
    });

    it('无效主题不应用', () => {
      const store = useThemeStore();
      const prev = store.current;

      store.apply('nonexistent');

      expect(store.current).toBe(prev);
    });
  });

  describe('toggle', () => {
    it('循环切换主题', () => {
      const store = useThemeStore();

      expect(store.current).toBe('white');

      store.toggle();
      expect(store.current).toBe('light-blue');

      store.toggle();
      expect(store.current).toBe('night');

      store.toggle();
      expect(store.current).toBe('sepia');

      store.toggle();
      expect(store.current).toBe('white');
    });
  });
});
