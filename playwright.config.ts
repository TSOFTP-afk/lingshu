import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// 项目根（playwright 命令从仓库根运行；config 会被转译为 CJS，避免 import.meta）
const projectRoot = process.cwd();

// E2E 独立数据目录：与 tools/seed_test_env.py 共用，绝不碰生产 data/novels.db。
const e2eDataDir = path.join(projectRoot, 'data', 'e2e_seed');
const backendEnv = {
  // 种子脚本与 uvicorn 后端使用同一套库与密码盐（pepper/salt 从该目录派生）
  LINGSHU_E2E_DB: e2eDataDir,
  LINGSHU_E2E_USER: 'e2e_writer',
  LINGSHU_E2E_PASS: 'e2e_pass_123',
  SIMPLE_AI_NOVEL_DATA_DIR: e2eDataDir,
  BOOKSTORE_DB_PATH: path.join(e2eDataDir, 'bookstore_demo.db'),
};

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5175',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      // 先幂等种子化，再拉起真实后端（前端 Vite 通过 /api 代理到 8787）
      command:
        'python tools/seed_test_env.py && python -m uvicorn lingshu_api.main:app --host 127.0.0.1 --port 8787',
      url: 'http://127.0.0.1:8787/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: backendEnv,
      cwd: projectRoot,
    },
    {
      command: 'npm run dev --prefix lingshu-app -- --host 127.0.0.1 --port 5175',
      url: 'http://127.0.0.1:5175',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      cwd: projectRoot,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
