/// <reference types="vitest" />
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue'],
          element: ['element-plus', '@element-plus/icons-vue'],
          vendor: ['axios'],
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5175,
    hmr: {
      host: '0.0.0.0',
    },
    proxy: {
      '/api': {
        target: 'https://www.ling-shu.top',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      thresholds: {
        lines: 60,
        functions: 60,
        branches: 50,
        statements: 60,
      },
    },
  },
});
