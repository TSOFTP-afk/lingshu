# 灵枢产品定位与 AI 登录前置维护指南

这份文档面向后续接手灵枢的人，优先回答三个问题：

1. 灵枢到底是什么产品。
2. AI 功能和登录之间的边界在哪里。
3. 新增或修改 AI 能力时应该改哪些地方、跑哪些验证。

## 1. 产品定位

灵枢是面向长篇、百万字级小说创作的本地优先 AI 写作工作台。

它不是通用 SaaS，也不是单纯的聊天壳。核心价值是帮助作者在长周期创作中维护书稿、章节、人物、世界观、Truth File、RAG、全书分析、写回证据链和 AI 使用记录。

当前主线架构是：

- `lingshu-app/`：Vue 3 创作工作台。
- `lingshu_api/`：FastAPI REST + WebSocket 本地网关。
- `electron/`：桌面壳，默认启动或连接本地 FastAPI。
- `novel_app/`：核心业务、数据库、AI、RAG、V3 分析引擎。
- `web/`、`admin-web/`、`cloud-admin/`、`lingjing-app/`：读者端、管理端和独立管理工具。

本地优先的含义是：

- 书稿、设定、Truth File、RAG 索引和分析草稿优先保存在本机数据目录。
- Electron 工作台默认连本地 FastAPI。
- 云端主要负责账号、授权、同步、备份、设备信任和管理。
- 不把普通创作数据默认上传为硬依赖。

新的产品边界是：

> 所有 AI 能力都必须先登录。登录是 AI 功能的前置条件，而不是可有可无的增强按钮。

## 2. AI 登录前置规则

凡是满足下面任意条件，都属于 AI 功能：

- 会调用远程模型或 OpenAI 兼容接口。
- 会配置、测试、读取或保存模型用途配置。
- 会触发 AI 生成、续写、润色、纠错、审查、对话、AI 率检测。
- 会使用 AI 增强的 V3 分析阶段，例如实体提及、共指、事实抽取。
- 会在智能导入中调用模型做章节结构识别或文档分类。

这些入口必须满足：

- REST API 使用 `require_ai_access`。
- WebSocket 使用 `authenticate_ws`，前端连接后第一帧必须发送 `auth`。
- 前端交互先调用 `auth.requireAiAccess()`，未登录时打开登录弹窗。
- 不允许匿名触发模型调用。
- 不允许 AI 增强模式静默降级成规则模式后假装成功；用户请求 AI，就必须明确成功使用 AI 或明确失败。

## 3. 后端维护入口

### 认证依赖

文件：`lingshu_api/dependencies.py`

关键函数：

- `require_login`：普通登录门禁。
- `require_ai_access`：AI 功能统一门禁。
- `require_author`、`require_admin`：作者和管理员门禁。

新增 AI REST 入口时，优先使用：

```python
user: dict = Depends(require_ai_access)
```

不要只依赖前端禁用按钮。前端只能改善体验，后端才是边界。

### AI 设置

文件：`lingshu_api/routers/settings.py`

这些接口必须登录后使用：

- `GET /api/settings/ai`
- `PUT /api/settings/ai`
- `POST /api/settings/ai/test`

原因：AI 配置包含模型用途、base URL、密钥状态和测试能力，本身就是 AI 能力的一部分。

### 工作台 AI REST

文件：`lingshu_api/routers/workspace.py`

已显式接入 AI 门禁的入口：

- `POST /api/workspace/chapters/{chapter_id}/ai-probability`
- `POST /api/workspace/chapters/{chapter_id}/polish-selection`

智能导入在工作台导入接口内部运行，导入接口本身接 `require_ai_access`。若后续拆出独立 AI 导入接口，也要单独接同一门禁。

### V3 AI 增强分析

文件：`lingshu_api/routers/analysis_v3.py`

规则模式和 AI 增强模式要区分：

- `use_ai=false`：走规则引擎。
- `use_ai=true`：必须创建可用 AI provider，失败时返回明确错误。

统一创建函数：

```python
_create_required_analysis_ai_provider(db)
```

维护要求：

- 不要在 API 层把 `use_ai=true` 静默改成 `False`。
- pipeline 内部可以对单阶段 AI 失败做规则兜底，但 API 入口必须真实表达用户请求的是 AI 模式。
- 返回的 run meta 要能看出 `ai_invoked`、`ai_stages`、`ai_call_count` 等信息。

### AI WebSocket

后端入口：

- `lingshu_api/ws/generation.py`
- `lingshu_api/ws/review_ws.py`
- `lingshu_api/ws/chat.py`
- `lingshu_api/ws/analysis_v3_ws.py`

这些 WebSocket 都必须通过：

```python
conn = await authenticate_ws(ws)
```

协议要求第一帧是：

```json
{"type":"auth","payload":{"token":"<access_token>"}}
```

认证成功后服务端返回 `auth_ok`，之后才处理业务消息。

## 4. 前端维护入口

### 认证 store

文件：`lingshu-app/src/stores/auth.js`

关键函数：

- `requireAuth()`：普通登录要求。
- `requireAiAccess()`：AI 功能登录要求。

新增 AI 按钮或 AI 任务前，先调用：

```js
if (!auth.requireAiAccess()) return;
```

### REST API

文件：`lingshu-app/src/utils/api.js`

Axios 拦截器会自动附加：

```http
Authorization: Bearer <token>
```

401 会清理 token 并打开登录弹窗。

### WebSocket

文件：`lingshu-app/src/utils/api.js`

新增 AI WebSocket 时，连接成功后先调用：

```js
sendWsAuth(ws);
```

再发送业务消息。

已接入的前端入口包括：

- `GenerateTab.vue`：AI 生成、续写、润色。
- `ReviewTab.vue`：AI 审查。
- `AiChatPanel.vue`：AI 对话。
- `CorrectionPanel.vue`：AI 纠错。
- `ContentEditor.vue`：选区润色、AI 纠错入口。
- `WorkspaceLayout.vue`：AI 率检测。
- `AnalysisTab.vue`：V3 分析和增量分析入口。

## 5. 智能导入边界

智能导入包含两层：

- 基础解析：本地正则、文本拆章、fallback 分段。
- AI 辅助：调用 `ChapterStructureAgent` 和远程模型识别卷/章结构。

当前章节结构识别的主分段常量在：

```python
novel_app/agents/chapter_structure.py
SMART_IMPORT_ANALYSIS_CHUNK_CHARS = 100_000
```

不要把它误改回 30 万字。测试名中也应保持 100k 边界语义。

## 6. 数据与安全原则

必须遵守：

- 登录 token 只作为 AI、账号、同步等能力的凭据，不改变本地优先的数据落点。
- refresh token 或长期密钥不能暴露给 renderer。
- Electron `safeStorage` 不可用时不能静默降级为明文保存敏感密钥。
- 管理端 HMAC 使用 `timestamp + method + path`，服务端校验 `X-Client-KeyId`、`X-Client-Ts`、`X-Client-Sig`。
- 未确认的 V3 分析草稿不得直接写入正式 Truth File 或 RAG。
- 正式写回必须保留 evidence/card/snapshot 标识。

## 7. 新增 AI 功能 Checklist

新增一个 AI 功能时，按这个顺序做：

1. 明确它是否会调用模型或配置模型。只要会，就是 AI 功能。
2. 后端 REST 接 `require_ai_access`，WebSocket 接 `authenticate_ws`。
3. 前端按钮或任务入口调用 `auth.requireAiAccess()`。
4. 如果是 WebSocket，前端 `onopen` 先调用 `sendWsAuth(ws)`。
5. 记录 AI 用量：`trace_id`、feature、model、provider、token、耗时、状态。
6. 错误提示要明确是未登录、登录过期、AI 未配置，还是模型调用失败。
7. 补测试或至少跑相关现有测试。
8. 更新 README 或本维护指南中对应入口。

## 8. 推荐验证命令

后端语法和核心测试：

```powershell
python -m compileall -q novel_app lingshu_api tests
python -m pytest tests/test_workspace_api.py tests/test_analysis_v3_api.py tests/test_reference_api_and_ai_settings.py -q
```

AI/导入相关：

```powershell
python -m pytest tests/test_agents.py tests/test_ai_json_mode.py tests/test_ai_provider.py -q
```

前端工作台：

```powershell
npm run build --prefix lingshu-app
```

完整基线：

```powershell
python tests/test_runner.py
npm run build --prefix lingshu-app
npm run build --prefix web
npm run build --prefix admin-web
npm run build --prefix cloud-admin
npm run build:renderer --prefix lingjing-app
```

## 9. 常见坑

- 只在按钮上写 `:disabled="!auth.isLoggedIn"` 不够，函数内部仍要调用 `requireAiAccess()`。
- WebSocket 不能一连接就发业务消息，必须先发 `auth`。
- V3 API 层不要吞掉 AI provider 创建失败，否则用户以为跑了 AI，实际跑了规则。
- AI 设置接口也属于 AI 功能，不能匿名开放。
- 智能导入的 10 万字分段是产品决策，不是随手优化参数。
- README 是入口文档，本文件是维护文档；两边的产品定位必须保持一致。
