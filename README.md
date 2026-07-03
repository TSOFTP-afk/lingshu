# 灵枢

灵枢是一款面向长篇、百万字级小说创作的本地优先 AI 写作工作台。它把书籍、卷章、人物、世界观、Skills、Truth File、RAG、生成、审查、全书分析、同步和管理后台放在同一套工程里，目标是让作者在长周期创作中持续维护设定、结构、正文和证据链。

当前产品边界是：**创作数据和本地后端优先留在用户设备上，账号登录是所有 AI 能力的前置条件**。凡是会调用模型、配置模型、触发 AI 生成/润色/审查/对话/检测/AI 增强分析的入口，都必须先完成登录；云端仍主要承担账号、授权、同步、备份和设备信任增强，不把普通写作数据默认上传。

当前主线是 **Vue 3 + FastAPI + Electron**。原 PyQt6 桌面主线已经迁移，`novel_app/` 继续保留核心业务、数据库、AI、RAG 和分析能力，桌面体验由 Electron 壳承载。

## 当前状态

- **创作工作台**：`lingshu-app/`，Vue 3 + Element Plus，连接本地 FastAPI。
- **后端 API**：`lingshu_api/`，FastAPI REST + WebSocket，默认端口 `8787`。
- **桌面壳**：`electron/`，默认启动或连接本地 FastAPI；登录解锁 AI、同步、备份等账号能力。
- **读者/书城端**：`web/`，面向发布、阅读、书架和作者门户。
- **管理后台**：`admin-web/`、`cloud-admin/`，面向用户、作品、设备、同步、配额和审计管理。
- **灵镜管理台**：`lingjing-app/`，独立 Electron 管理端，使用密钥文件 + 管理员账号双重认证。
- **V3 分析引擎**：已落在 `novel_app/analysis/` 和 `lingshu_api/routers/analysis_v3.py`，支持语义分块、实体、事实、记忆、探针、回溯和写回门禁。

## 核心能力

### 创作与资料管理

- 书籍、分卷、章节、模板章节管理。
- 章节正文、大纲、摘要、人物卡、世界观和参考资料维护。
- 结构化表单与 Markdown/文本编辑结合。
- 本地快照、导入、导出和恢复。

### AI 写作辅助

- 所有 AI 能力必须先登录；REST 入口使用 `require_ai_access`，WebSocket 第一帧必须发送 `auth`。
- 章节草稿生成、续写、选区润色。
- AI 纠错、AI 概率检测、同步大纲。
- 多用途 AI 配置，不同任务可使用不同模型。
- AI 使用记录会写入用量事件，包含 `trace_id`、模型、provider、token、耗时和 schema/prompt 版本字段。

### 智能导入

- 支持 `.txt`、`.md`、`.docx`。
- 登录后远程模型可识别正文、大纲、人物、世界观等文档类型。
- `ChapterStructureAgent` 可识别卷/章标题、番外、作者的话，并保留行号证据。
- 长文本导入会按约 10 万字和边界窗口分段，避免章节边界丢失。

### V3 全书分析

V3 是当前分析主线，旧 `/ws/analysis` 只保留握手兼容；真实分析入口是 REST `/api/workspace/.../analysis-v3/*` 和 WebSocket `/ws/analysis-v3`。

V3 流程包括：

1. 语义感知分块。
2. 实体提及抽取。
3. 两级共指消解。
4. 原子事实抽取。
5. 记忆分层与缓存压缩。
6. 文章探针与一致性检查。
7. 精准回溯任务。
8. 事件驱动卡片生成。
9. 证据门禁后的正式写回。

前端 `lingshu-app` 的分析抽屉提供 V3 运行记录、诊断、实体审核、探针、回溯、单卡写回和增量分析入口。

### Truth File 与 RAG

- Truth File 汇总正式设定、章节摘要、伏笔和上下文。
- RAG 使用本地数据目录，区分 `chapter`、`book_design`、`truth_snapshot`、`analysis_block`、`book_reference` 等 `doc_type`。
- 写回必须经过证据门禁，未确认的分析草稿不得直接污染正式 Truth/RAG。

### 云端与管理

- 普通创作路径本地优先，离线可用。
- 账号登录是 AI 功能前置；云端能力用于账号、授权、同步、备份和设备管理。
- 管理端 token 与普通用户 token 分离。
- 灵镜管理台使用 `.lingshu-key` 密钥文件；请求签名使用 `timestamp + method + path`，服务端校验 `X-Client-KeyId`、`X-Client-Ts`、`X-Client-Sig`。
- Electron `safeStorage` 不可用时拒绝明文保存敏感密钥。

## 技术栈

| 层面 | 当前实现 |
| --- | --- |
| 工作台前端 | Vue 3, Vite, Element Plus, Pinia, Splitpanes, G6 |
| 后端 | FastAPI, WebSocket, SQLite |
| 桌面壳 | Electron |
| 读者端 | Vue 3, Vite, Element Plus, Pinia |
| 管理端 | Vue 3, Element Plus, ECharts |
| 核心业务 | Python, SQLite, 本地文件数据目录 |
| AI 接口 | OpenAI 兼容 Chat Completions |
| 分析引擎 | `novel_app/analysis/*` V3 管线 |
| RAG | 本地向量/检索模块，支持 doc_type 分区 |
| 测试 | pytest, vue-tsc, Vite build |
| 推荐运行时 | Python 3.13+, Node.js 20+ |

## 快速启动

### 1. 安装依赖

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
npm install
npm install --prefix lingshu-app
npm install --prefix web
npm install --prefix admin-web
npm install --prefix cloud-admin
npm install --prefix lingjing-app
```

### 2. 启动后端

```powershell
npm run backend
```

等价命令：

```powershell
python -m uvicorn lingshu_api.main:app --host 127.0.0.1 --port 8787
```

健康检查：

```text
http://127.0.0.1:8787/api/health
```

### 3. 启动工作台前端

```powershell
npm run dev:ws
```

默认访问：

```text
http://127.0.0.1:5175
```

### 4. 同时启动多个前端

```powershell
npm run dev
```

该命令会启动：

- `lingshu-app/`：创作工作台。
- `web/`：书城/读者端。
- `admin-web/`：管理后台。

后端仍需单独启动。

### 5. Electron 工作台

```powershell
npm run backend
npm run electron
```

打包版 Electron 默认会启动或连接本地 FastAPI。可用环境变量覆盖主机和端口：

```powershell
$env:LINGSHU_BACKEND_HOST="127.0.0.1"
$env:LINGSHU_BACKEND_PORT="8787"
```

### 6. 灵镜管理台

```powershell
npm run dev --prefix lingjing-app
```

构建 renderer 冒烟：

```powershell
npm run build:renderer --prefix lingjing-app
```

完整 Electron 打包：

```powershell
npm run build --prefix lingjing-app
```

## 常用脚本

| 命令 | 说明 |
| --- | --- |
| `npm run backend` | 启动 FastAPI 后端 |
| `npm run dev` | 同时启动工作台、读者端、管理后台前端 |
| `npm run dev:ws` | 启动创作工作台前端 |
| `npm run dev:web` | 启动读者/书城端 |
| `npm run dev:admin` | 启动管理后台 |
| `npm run electron` | 启动 Electron 工作台壳 |
| `npm run build` | 构建工作台、读者端、管理后台 |
| `npm run test` | 运行 Python 回归测试 runner |
| `npm run test:quick` | 快速导入 FastAPI app 并统计路由 |

## 测试与验证

后端基线：

```powershell
python -m compileall -q novel_app lingshu_api tests
python tests/test_runner.py
```

重点 V3 写回链路：

```powershell
python -m pytest tests/test_v3_writeback.py tests/test_e2e_v3_writeback.py -q
```

常用 API/V3/管理端测试：

```powershell
python -m pytest tests/test_admin_auth.py tests/test_bookstore_api.py tests/test_analysis_v3_api.py -q
```

前端构建：

```powershell
npm run build --prefix lingshu-app
npm run build --prefix web
npm run build --prefix admin-web
npm run build --prefix cloud-admin
npm run build:renderer --prefix lingjing-app
```

CI 当前覆盖：

- Windows 后端测试与 compileall。
- Ubuntu Node 20 前端矩阵构建。
- `lingshu-app` 会先执行 `vue-tsc --noEmit` 再 Vite build。
- `lingjing-app` 在 CI 中执行 renderer build，完整 Electron Builder 留给发布流程。

## 环境变量

### 后端与数据目录

| 变量 | 说明 |
| --- | --- |
| `BOOKSTORE_DB_PATH` | 书城/账号/管理数据库路径 |
| `SIMPLE_AI_NOVEL_DATA_DIR` | 工作台本地数据目录 |
| `LINGSHU_PORTABLE_DATA_DIR` | Electron 便携数据目录 |
| `BOOKSTORE_ADMIN_USERS` | 逗号分隔的普通账号管理员名单 |
| `BOOKSTORE_PUBLISH_TOKEN` | 发布接口令牌 |
| `BOOKSTORE_WEB_BASE_URL` | 公开阅读链接基址 |

### AI 配置

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key |
| `OPENAI_BASE_URL` | OpenAI 兼容接口地址 |
| `OPENAI_MODEL` | 默认模型 |

应用内 AI 设置会保存在数据目录中，优先用于不同用途的模型配置。

### 工作台 Electron

| 变量 | 说明 |
| --- | --- |
| `LINGSHU_BACKEND_HOST` | 本地后端 host，默认 `127.0.0.1` |
| `LINGSHU_BACKEND_PORT` | 本地后端端口，默认 `8787` |
| `LINGSHU_LOCAL_BASE_URL` | 本地 API base URL 覆盖 |
| `LINGSHU_API_BASE_URL` | renderer API URL 覆盖 |
| `LINGSHU_WS_BASE_URL` | renderer WebSocket URL 覆盖 |
| `LINGSHU_CLOUD_BASE_URL` | 云端基址，默认 `https://www.ling-shu.top` |
| `LINGSHU_DISABLE_LOCAL_BACKEND` | 设为 `1` 时不自动拉起本地后端 |
| `LINGSHU_PYTHON` | Electron 拉起后端时使用的 Python 可执行文件 |

### 灵镜管理台

| 变量 | 说明 |
| --- | --- |
| `LINGJING_SERVER_BASE_URL` | 管理端连接的完整服务基址 |
| `LINGJING_SERVER_PROTOCOL` | 默认 `https` |
| `LINGJING_SERVER_HOST` | 默认 `120.27.202.2` |
| `LINGJING_SERVER_PORT` | 可选端口 |
| `LINGJING_DEV_API_TARGET` | Vite dev proxy 目标 |

## 主要目录

```text
.
├── lingshu_api/                 FastAPI 统一后端
│   ├── routers/                 REST 路由：auth、workspace、analysis_v3、admin 等
│   ├── services/                同步、设置、用量记录、数据库桥接
│   └── ws/                      WebSocket：generation、review、chat、analysis-v3
├── lingshu-app/                 Vue 创作工作台
├── electron/                    灵枢 Electron 工作台壳
├── web/                         读者/书城前端
├── admin-web/                   管理后台前端
├── cloud-admin/                 云端管理后台前端
├── lingjing-app/                灵镜 Electron 管理台
├── novel_app/                   核心业务、AI、数据库、RAG、分析引擎
│   ├── analysis/                V3 分析、记忆、探针、回溯、写回
│   ├── db/                      SQLite schema 与业务数据访问
│   ├── rag/                     本地检索与向量模块
│   └── agents/                  写作/导入/AgentGraph 等智能体
├── tests/                       pytest 回归测试
├── docs/                        规划、迁移、设计和留档文档
├── packaging/                   打包相关资源
└── tools/                       辅助脚本
```

## API 与 WebSocket 概览

常用 REST 前缀：

- `/api/auth/*`：普通用户认证。
- `/api/bookshelf/*`：书架。
- `/api/workspace/*`：本地工作台。
- `/api/workspace/books/{book_id}/analysis-v3/*`：V3 分析运行。
- `/api/settings/ai`：AI 用途、模型和密钥配置，必须登录。
- `/api/admin/auth/*`：独立管理员认证。
- `/api/admin/*`：管理后台。
- `/api/rag/*`：RAG 检索与索引。

WebSocket：

- `/ws/generation`：写作生成。
- `/ws/review`：审查。
- `/ws/chat`：对话助手。
- `/ws/analysis-v3`：V3 分析进度。
- `/ws/analysis`：旧入口兼容 shim，新代码不要依赖。

AI WebSocket 连接必须先发送认证帧：

```json
{"type":"auth","payload":{"token":"<access_token>"}}
```

## 数据与安全原则

- 默认本地优先，离线创作不依赖云端。
- 用户正文、设定、Truth File、RAG 索引默认保存在本地数据目录。
- 所有 AI 能力必须登录后使用；新增 AI REST 入口接入 `require_ai_access`，新增 AI WebSocket 入口接入 `authenticate_ws`。
- 云端同步是增强功能，不应成为本地工作台启动前置条件。
- 管理端密钥必须通过系统安全存储保存；不可用时拒绝明文降级。
- 写回正式设定前必须保留证据来源和快照。
- 旧 Qt 代码不再是主线；新增 UI 优先进入 Vue/FastAPI/Electron 栈。

## 打包

工作台 Electron 打包脚本：

```powershell
.\build_electron.ps1
```

灵镜管理台：

```powershell
npm run build --prefix lingjing-app
```

打包时注意：

- PowerShell 脚本对编码敏感，避免手工保存成带 BOM 的异常格式。
- Electron 完整打包可能生成较大的 release 目录。
- CI 只做 renderer build 冒烟，正式安装包以发布流程为准。

## 维护建议

- 改动公共 API 时同步补测试，优先覆盖 `tests/test_lingshu_api.py`、`tests/test_workspace_api.py`、`tests/test_analysis_v3_api.py`。
- 改动 V3 分析链时至少跑 `tests/test_analysis_pipeline_v3.py`、`tests/test_v3_writeback.py`、`tests/test_e2e_v3_writeback.py`。
- 改动前端工作台时至少跑 `npm run build --prefix lingshu-app`。
- 改动 Electron/preload 时确认 renderer 仍默认走本地 API。
- 新增 AI 功能时先补登录门禁，再接模型调用；前端 WebSocket 使用 `sendWsAuth()` 后再发送任务消息。
- 不要把未确认的分析草稿直接写入 Truth File 或 RAG。
- 大型模块拆分应在测试基线稳定后进行，避免和行为修复混在一个变更里。
