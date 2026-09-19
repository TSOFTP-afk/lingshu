# 运行时 E2E 测试套件

## 1. 概述

本目录包含运行时 E2E（端到端）测试套件，用于连接真实前后端服务器，用种子账号（默认 `e2e_writer` / `e2e_pass_123`，可用 env `LINGSHU_E2E_USER` / `LINGSHU_E2E_PASS` 覆盖）登录，执行 V3 全书分析一条龙检测（从分析到审核到写回书籍卡/人物卡/世界卡）。

该套件会真实拉起（或复用已运行的）后端 API 服务与前端 Vite 服务，模拟用户从登录、创建书籍、写入章节、触发 V3 全书分析、等待分析完成、通过审核门禁、批量写回卡片到清理测试数据的完整流程，并在测试结束后输出 14 环节结构化检测报告。

## 2. 前置条件

- Python 3.10+，已安装项目依赖（`pip install -r requirements.txt`）
- Node.js 18+，已在 `lingshu-app/` 目录执行 `npm install`
- E2E 账号由种子脚本 `tools/seed_test_env.py` 创建（幂等，可重复运行）：
  在独立数据目录（env `LINGSHU_E2E_DB`，默认 `data/e2e_seed/`，绝不碰生产 `data/novels.db`）建立
  双库（`bookstore_demo.db` + `novels.db`）、种子账号与示例书。
  设置 `LINGSHU_E2E_USER` / `LINGSHU_E2E_PASS` 后运行测试时若账号缺失会自动调用该脚本；也可手动执行：
  ```bash
  python tools/seed_test_env.py
  ```
- （可选）Playwright 已安装：`pip install playwright && playwright install chromium`
- 端口 8787（后端）和 5175（前端，Vite dev server 实际端口）可用，或已被对应服务占用

## 3. 运行方式

### 方式一：自动拉起服务器（推荐）

```bash
pytest tests/runtime_e2e/test_v3_full_pipeline_runtime.py -v -s
```

测试会自动检测后端/前端是否运行，未运行则自动拉起子进程，测试结束后回收。

### 方式二：手动启动服务器后运行

```bash
# 终端 1：启动后端
python main.py --host 127.0.0.1 --port 8787

# 终端 2：启动前端
cd lingshu-app && npm run dev -- --host 127.0.0.1 --port 5175

# 终端 3：运行测试
pytest tests/runtime_e2e/test_v3_full_pipeline_runtime.py -v -s
```

### 运行前端冒烟测试（可选，需 Playwright）

```bash
pytest tests/runtime_e2e/test_frontend_smoke.py -v -s
```

### 运行全部 E2E 测试

```bash
pytest tests/runtime_e2e/ -v -s
```

### 排除 E2E 测试（默认 pytest 套件）

```bash
pytest --ignore=tests/runtime_e2e
```

## 4. 测试输出

### 控制台输出

测试运行过程中，每个用例的 PASS/FAIL 会输出到控制台。

### 检测报告

测试结束后在 `tests/runtime_e2e/report.txt` 生成结构化报告，覆盖 14 个环节：

1. 前后端服务器连接
2. 种子账号登录
3. 测试书籍创建
4. 章节正文写入
5. V3 分析触发
6. V3 分析完成（产出非空）
7. 审核门禁通过
8. 批量写回执行
9. 人物卡写回验证
10. 世界卡写回验证
11. 书籍卡写回验证
12. 卡片状态验证
13. 前端冒烟检查
14. 测试数据清理

每项标记 ✓（通过）或 ✗（失败），末尾给出整体结果。

### 子进程日志

自动拉起的服务器日志写入 `.codex-runtime/logs/e2e_backend.{out,err}.log` 和 `.codex-runtime/logs/e2e_frontend.{out,err}.log`。

## 5. 测试流程详解

一条龙检测流程如下：

1. 确保前后端服务器就绪（自动拉起或复用已运行）
2. 用种子账号（`e2e_writer` / `e2e_pass_123` 或 env 覆盖值）登录，获取 `access_token`
3. 创建 `__E2E_V3__<timestamp>` 测试书籍
4. 写入 5 章测试正文（复用 `tests/fixtures/test_novel.py`）
5. 触发 V3 全书分析（规则模式 `use_ai=false, execute_l1=true`）
6. 轮询直至分析完成（`completed` / `probes_ready`，超时 180 秒）
7. 验证审核门禁 `formal_writeback_allowed=true`
8. 执行批量写回（书籍卡/人物卡/世界卡）
9. 验证写回结果（characters/world_entries/books 表）
10. 验证卡片状态为 `applied`
11. 清理测试书籍及关联数据
12. 输出 14 环节检测报告

## 6. 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 登录失败 401 | 后端数据库中无种子账号或密码不一致 | 运行 `python tools/seed_test_env.py` 重建种子库，或将后端数据目录指向 `LINGSHU_E2E_DB`（`SIMPLE_AI_NOVEL_DATA_DIR` / `BOOKSTORE_DB_PATH`） |
| 登录失败 503 | 后端服务未就绪 | 检查后端日志 `.codex-runtime/logs/e2e_backend.err.log` |
| 端口占用 | 8787/5175 被其他进程占用 | 终止占用进程或修改 `helpers.py` 中的端口常量 |
| V3 分析超时 | 测试小说内容过少或分析卡死 | 检查后端日志，适当增加 `wait_for` 超时时间 |
| 写回门禁阻断 | 存在 pending backtrack 或 manual_review probes | 检查 `get_review` 返回的 `blockers` 列表 |
| 前端冒烟测试跳过 | Playwright 未安装 | `pip install playwright && playwright install chromium` |
| 测试书籍未清理 | 删除接口异常 | 手动 GET `/api/workspace/books` 查找 `__E2E_V3__` 开头的书籍并 DELETE |

## 7. 配置说明

可在 `helpers.py` 顶部修改以下常量：

- `BACKEND_HOST` / `BACKEND_PORT` — 后端服务地址（默认 `127.0.0.1:8787`）
- `FRONTEND_HOST` / `FRONTEND_PORT` — 前端服务地址（默认 `127.0.0.1:5175`）
- `E2E_BOOK_PREFIX` — 测试书籍标题前缀（默认 `__E2E_V3__`）

环境变量（推荐，不改代码）：

- `LINGSHU_E2E_USER` / `LINGSHU_E2E_PASS` — E2E 账号；未设置时自动运行种子脚本并使用默认账号 `e2e_writer` / `e2e_pass_123`
- `LINGSHU_E2E_DB` — 种子数据目录（默认 `data/e2e_seed/`，独立于生产 `data/`）

## 文件结构

```
tests/runtime_e2e/
├── __init__.py                          # 包标识
├── helpers.py                           # HTTP 客户端、轮询、健康检查、清理工具、报告类
├── conftest.py                          # pytest fixtures（服务器启停、登录、测试书籍、V3 运行）
├── test_v3_full_pipeline_runtime.py     # 主 E2E 测试（12 用例 + 14 环节报告）
├── test_frontend_smoke.py               # Playwright 前端冒烟测试（可选）
└── report.txt                           # 测试运行后生成的检测报告
```
