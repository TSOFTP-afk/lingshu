# 灵枢项目 Qt → Vue + JavaScript + ElementPlus 全栈迁移方案

> **版本**: v1.0  
> **生成日期**: 2026-06-11  
> **目标**: 将桌面端 PyQt6 UI 层全面迁移至 Web 技术栈，消除 GPL v3 许可证冲突  
> **声明**: 本方案仅包含架构规划与策略，不包含任何代码实现

---

## 一、迁移动机与目标

### 1.1 核心动机

| 问题 | 说明 |
|------|------|
| 许可证冲突 | PyQt6 (GPL v3) 与项目主许可证 CC BY-NC 4.0 互不兼容 |
| 跨平台局限 | Qt 桌面应用仅 Windows 构建，macOS/Linux 用户无法使用 |
| 技术栈分裂 | 项目同时维护 Qt (桌面) + Vue (Web) 两套 UI，增加维护成本 |

### 1.2 迁移目标

- **消除 PyQt6 依赖**，解除 GPL v3 许可证冲突
- **统一技术栈**：全栈 Vue 3 + JavaScript + ElementPlus + FastAPI
- **保留桌面体验**：通过 Electron 或 Tauri 打包为原生桌面应用（可选）
- **功能零损失**：确保所有 9 个抽屉 Tab、编辑工作区、AI 流水线、RAG 检索等功能完整迁移

---

## 二、现状分析

### 2.1 已有资产（可直接复用）

```
已完成 Vue 迁移的模块:
├── web/           ← 读者端（书城浏览 + 书架 + 阅读器 + 章节编辑器）
├── admin-web/     ← 管理后台（仪表盘 + 用户/作品/审计管理）
└── bookstore_api  ← FastAPI 后端（50+ REST 端点，含认证/书架/创作/管理）
```

### 2.2 待迁移模块（仍在 Qt 中）

```
novel_app/qt/  → 需要完整迁移:
├── app_window.py          # 主窗口构造 (AppWindowMixin) — 约 900 行
├── app_tree.py            # 书库树视图 (AppTreeMixin)
├── app_drawer.py          # 抽屉内容桥接 (AppDrawerMixin)
├── app_editor.py          # 正文编辑器 (AppEditorMixin)
├── app_generation.py      # AI 生成触发 (AppGenerationMixin)
├── app_analysis.py        # 全书分析管线 (AppAnalysisMixin)
├── app_import.py          # 文件导入 (AppImportMixin)
├── app_review_tasks.py    # 审查后处理 (AppReviewTasksMixin)
├── app_settings_export.py # 导出/快照 (AppSettingsExportMixin)
├── drawer/                # 9 个抽屉 Tab
│   ├── overview.py        # 概览
│   ├── shortcuts.py       # 快键
│   ├── outline.py         # 生成
│   ├── characters.py      # 人物
│   ├── world.py           # 世界观
│   ├── skills.py          # Skills
│   ├── analysis.py        # 分析
│   ├── review.py          # 记录
│   └── tasks.py           # 任务
├── dialogs.py             # 6 个对话框
├── chat_dialog.py         # AI 对话
├── correction_dialog.py   # AI 纠错
├── character_dialog.py    # 人物详情
├── reference_books.py     # 参考书库
├── star_graph/            # 星图可视化
├── chapter_tabs.py        # 多章节标签管理
├── forms.py               # 结构化表单
├── startup.py             # 启动画面
├── theme.py               # 主题系统
└── workers.py             # 工作线程模型
```

### 2.3 后端能力缺口（需新增 API）

| 模块 | 待暴露功能 | 建议方式 |
|------|-----------|---------|
| RAG 检索 | `search()`, `build_context_from_results()` | REST |
| AI 生成 | `AgentGraph.run_generation()` | WebSocket |
| AI 审查 | `AgentGraph.run_review()` | WebSocket |
| AI 全书分析 | `AIBookAnalysisMixin` 三级流水线 | WebSocket |
| AI 对话/纠错 | `ChatDialog`, `CorrectionDialog` | WebSocket (流式) |
| 人物管理 | CRUD + 图片上传 | REST |
| 世界观管理 | CRUD | REST |
| 分析/审查记录 | 列表 + 详情 + 快照 | REST |
| 参考书管理 | CRUD + Skills 提炼 | REST |
| Skills 管理 | 绑定/解绑/列表 | REST |
| 大纲导入 | TXT/DOCX 智能解析 | REST (multipart) |
| 导出 | TXT/MD/DOCX 生成 | REST (文件下载) |

---

## 三、目标架构设计

### 3.1 整体架构

```
┌────────────────────────────────────────────────────┐
│                  桌面壳（可选）                       │
│         Electron / Tauri / PWA                     │
├────────────────────────────────────────────────────┤
│                 Vue 3 SPA 前端                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ 创作工作台 │ │  书城读者端 │ │   管理后台       │   │
│  │ (新建)    │ │  (现有)   │ │   (现有)         │   │
│  └──────────┘ └──────────┘ └──────────────────┘   │
├────────────────────────────────────────────────────┤
│              FastAPI 统一后端（扩展）                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ 书城 API  │ │ 创作 API  │ │  管理 API        │   │
│  │ (现有)   │ │ (新增)   │ │  (现有)          │   │
│  └──────────┘ └──────────┘ └──────────────────┘   │
│  ┌──────────────────────────────────────────────┐  │
│  │        WebSocket 服务（新增）                  │  │
│  │   AI 生成流 / AI 审查流 / 分析管线 / 对话      │  │
│  └──────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────┤
│             Python 核心服务层（不变）                 │
│  Database │ RAG │ AgentGraph │ AI Service │ Export│
└────────────────────────────────────────────────────┘
```

### 3.2 路由设计（创作工作台 - 新建）

```
/workspace                          # 创作工作台入口
/workspace/books/:bookId            # 书籍工作区
  ├── /volumes/:volumeId            # 卷级视图
  │   └── /chapters/:chapterId      # 章节编辑
  └── /settings                     # 书籍设置（大纲/世界观/导出）
/workspace/books/:bookId/chat       # AI 对话
/workspace/books/:bookId/reference   # 参考书库
/workspace/books/:bookId/star-graph  # 星图编辑器
/workspace/import                   # 导入向导
/workspace/settings                 # 全局设置（AI 配置/主题/视图）
```

### 3.3 组件树设计（主工作台）

```
AppLayout
├── GlobalHeaderBar                  # 顶栏
│   ├── BrandLogo "灵枢"
│   ├── WorkspaceBreadcrumb          # 面包屑导航
│   └── ToolbarMenu                  # [编辑▾] [AI▾] [视图▾] [设定▾]
│
├── BodyContainer
│   └── ResizableSplitter             # 三栏可拖拽分割
│       ├── LibraryPanel (左)         # 作品轨道
│       │   ├── PanelHeader "作品轨道"
│       │   ├── ActionButtons [新建] [收起]
│       │   ├── QuickActions [长篇生成] [Skills] [参考书库]
│       │   └── BookTree              # el-tree 组件
│       │
│       ├── WorkspacePanel (中)       # 编辑区
│       │   ├── EditorTitleBar        # 标题 + meta 信息
│       │   ├── StatsCard             # 3 格字数/AI统计
│       │   ├── QuickActionBar        # 10 个快捷操作
│       │   ├── ChapterTabBar         # 多章节标签
│       │   └── EditorArea            # el-tabs 切换
│       │       ├── EmptyState        # 空状态引导
│       │       ├── OutlineEditor     # 大纲编辑器 + BookOutlineForm
│       │       └── ContentEditor     # Monaco 富文本
│       │
│       └── DrawerPanel (右)          # 9 Tab 抽屉
│           ├── DrawerTitleBar        # 标题 + 关闭
│           └── el-tabs
│               ├── [概览] OverviewTab
│               ├── [快键] ShortcutsTab
│               ├── [生成] GenerateTab
│               ├── [人物] CharactersTab
│               ├── [世界观] WorldTab
│               ├── [Skills] SkillsTab
│               ├── [分析] AnalysisTab
│               ├── [记录] ReviewTab
│               └── [任务] TasksTab
│
└── StatusBar                         # 底栏
    ├── StatusText
    ├── SaveIndicator
    ├── WordCount
    ├── AIProbabilityIndicator
    └── TotalWordCount
```

---

## 四、前端技术选型

### 4.1 核心依赖

| 类别 | 技术 | 用途 | 许可证 |
|------|------|------|--------|
| 框架 | Vue 3.5 | SPA 框架 | MIT |
| 语言 | JavaScript (ES2022+) | 统一 JS（弃 TypeScript） | — |
| UI 库 | Element Plus 2.9 | 组件库（已有基础） | MIT |
| 状态管理 | Pinia 2 | 响应式状态 | MIT |
| 路由 | Vue Router 4 | SPA 路由 | MIT |
| HTTP | axios | REST 调用 | MIT |
| 构建 | Vite 6 | 开发/构建 | MIT |

### 4.2 新增依赖

| 类别 | 技术 | 用途 | 许可证 |
|------|------|------|--------|
| 代码编辑器 | Monaco Editor (`@guolao/vue-monaco-editor`) | 正文/大纲 Markdown 编辑 | MIT |
| 分割面板 | `splitpanes` | 三栏可拖拽布局 | MIT |
| WebSocket | 原生 `WebSocket` API | AI 流式通信 | 内置 |
| 文件上传 | `el-upload` (Element Plus 内置) | TXT/DOCX 导入 | MIT |
| 图表 | ECharts 6 (admin-web 已有) | 分析/审计可视化 | Apache 2.0 |
| 图可视化 | `@antv/g6` | 星图关系编辑 | MIT |
| Markdown 渲染 | `marked` + `highlight.js` | 预览渲染 | MIT |
| 桌面壳 | Electron 30+ / Tauri 2.0 | 可选桌面打包 | MIT |

### 4.3 桌面壳方案对比

| 维度 | Electron | Tauri | PWA (纯 Web) |
|------|----------|-------|-------------|
| 包体积 | ~150MB | ~10MB | 0 (浏览器运行) |
| 本地文件访问 | 完整 | 完整（需 Rust 插件） | 有限 |
| 系统托盘 | 支持 | 支持 | 不支持 |
| 自动更新 | 成熟方案 | 内置 | 浏览器控制 |
| 许可证 | MIT | MIT | — |
| 学习成本 | 低（JS 生态） | 中（需 Rust） | 无 |
| **推荐度** | ★★★★ | ★★★ | ★★★ |

> **推荐**: 优先 **Electron**，原因：(1) 与 Vue 生态无缝集成；(2) 已有 Launcher.cs 的逻辑可直接翻译为 Electron main process 代码；(3) 团队全程 JavaScript 技术栈。

---

## 五、后端 API 扩展计划

### 5.1 API 服务组织

```
lingshu_api/                  # 新建 API 服务包
├── __init__.py
├── main.py                   # FastAPI 应用入口
├── routers/
│   ├── bookshelf.py          # 现有: 书架 API
│   ├── auth.py               # 现有: 认证 API
│   ├── bookstore.py          # 现有: 书城 + 创作 API
│   ├── admin.py              # 现有: 管理后台 API
│   ├── workspace.py          # 新增: 工作台核心 API
│   ├── characters.py         # 新增: 人物 CRUD
│   ├── world.py              # 新增: 世界观 CRUD
│   ├── skills.py             # 新增: Skills 管理
│   ├── analysis.py           # 新增: 分析记录
│   ├── review.py             # 新增: 审查记录
│   ├── references.py         # 新增: 参考书管理
│   ├── export.py             # 新增: 导出服务
│   ├── import_doc.py         # 新增: 文档导入
│   └── rag.py                # 新增: RAG 检索
├── ws/
│   ├── __init__.py
│   ├── generation.py         # 新增: AI 生成 WebSocket
│   ├── review_ws.py          # 新增: AI 审查 WebSocket
│   ├── analysis_ws.py        # 新增: 全书分析 WebSocket
│   └── chat.py               # 新增: AI 对话/纠错 WebSocket
├── schemas/
│   ├── workspace.py          # 新增: 工作台 Pydantic 模型
│   └── ws_messages.py        # 新增: WebSocket 消息协议
└── services/
    ├── db_bridge.py          # 新增: novels.db 访问桥接层
    └── file_service.py       # 新增: 文件上传/存储
```

### 5.2 核心新增 REST 端点

#### 工作台 API（16 个端点）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/workspace/books` | 书籍列表 |
| `POST` | `/api/workspace/books` | 创建书籍 |
| `GET` | `/api/workspace/books/:id` | 书籍详情 + 卷/章树 |
| `PATCH` | `/api/workspace/books/:id` | 更新书籍 |
| `DELETE` | `/api/workspace/books/:id` | 删除书籍 |
| `POST` | `/api/workspace/books/:id/volumes` | 创建分卷 |
| `PATCH` | `/api/workspace/volumes/:id` | 更新分卷（含排序） |
| `DELETE` | `/api/workspace/volumes/:id` | 删除分卷 |
| `POST` | `/api/workspace/volumes/:id/chapters` | 创建章节 |
| `GET` | `/api/workspace/chapters/:id` | 获取章节（正文+大纲） |
| `PATCH` | `/api/workspace/chapters/:id` | 保存章节 |
| `DELETE` | `/api/workspace/chapters/:id` | 删除章节 |
| `PATCH` | `/api/workspace/chapters/:id/move` | 移动章节 |
| `GET` | `/api/workspace/books/:id/snapshots` | 快照列表 |
| `POST` | `/api/workspace/chapters/:id/snapshot` | 创建快照 |
| `POST` | `/api/workspace/chapters/:id/restore` | 恢复快照 |

#### 人物 API（5 个端点）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/workspace/books/:id/characters` | 人物列表 |
| `POST` | `/api/workspace/books/:id/characters` | 创建人物 |
| `PATCH` | `/api/workspace/characters/:id` | 更新人物（含图片上传） |
| `DELETE` | `/api/workspace/characters/:id` | 删除人物 |
| `POST` | `/api/workspace/characters/:id/image` | 上传人物立绘 |

#### RAG API（2 个端点）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/workspace/books/:id/rag/search?q=&doc_types=&top_k=` | 语义搜索 |
| `POST` | `/api/workspace/books/:id/rag/reindex` | 触发全书重建索引 |

### 5.3 WebSocket 协议设计

```
消息格式（JSON）:
{
  "type": "request|progress|chunk|result|error|cancel",
  "task_id": "uuid",
  "payload": { ... }
}

各通道:
/ws/generation   → AI 生成（Planner→Writer→Auditor→Reviser 流式进度）
/ws/review       → AI 审查（Auditor→Reviser 流式）
/ws/analysis     → 全书分析（三级管线步骤进度）
/ws/chat         → AI 对话/纠错（SSE 风格流式 token）

进度消息示例:
{ "type": "progress", "task_id": "...", "stage": "writer", "percent": 45 }
{ "type": "chunk", "task_id": "...", "text": "章节正文片段..." }
{ "type": "result", "task_id": "...", "findings": [...], "score": 85 }
```

### 5.4 数据库桥接策略

当前两个数据库完全独立，需要建立桥接：

| 方案 | 描述 | 推荐度 |
|------|------|--------|
| **方案 A（推荐）** | 统一 API 访问层：bookstore_api.py 扩展访问 novels.db | ★★★★ |
| 方案 B | 独立 API 服务：新建 workspace_api.py 专用访问 novels.db | ★★★ |
| 方案 C | 数据合并：将 novels.db Schema 迁移合并到 bookstore_demo.db | ★★ |

> **推荐方案 A**：最小化服务数量，当前 bookstore_api 已有成熟的认证/中间件体系，直接扩展路由即可。

---

## 六、组件迁移映射表

### 6.1 Qt 组件 → Vue 组件一一对应

| Qt 源文件 | Qt 类/函数 | → Vue 组件 | Element Plus 组件 |
|-----------|-----------|-----------|-------------------|
| `app_window.py` | `AppWindowMixin` | `WorkspaceLayout.vue` | `el-container` |
| `app_tree.py` | `AppTreeMixin` | `LibraryPanel.vue` | `el-tree` |
| `app_editor.py` | `AppEditorMixin` | `ContentEditor.vue` | Monaco Editor |
| `app_drawer.py` | `AppDrawerMixin` | `DrawerPanel.vue` | `el-tabs` |
| `app_generation.py` | `AppGenerationMixin` | `GenerateTab.vue` | `el-button` + WS |
| `app_analysis.py` | `AppAnalysisMixin` | `AnalysisPipeline.vue` | `el-progress` + WS |
| `app_import.py` | `AppImportMixin` | `ImportWizard.vue` | `el-upload` + `el-dialog` |
| `app_review_tasks.py` | `AppReviewTasksMixin` | `ReviewResultCard.vue` | `el-card` |
| `app_settings_export.py` | `AppSettingsExportMixin` | `ExportDialog.vue` | `el-dialog` + `el-select` |
| `startup.py` | `StartupSplash` | `LoadingScreen.vue` | CSS 动画 |
| `theme.py` | `ThemeTokens` + `PRESET_THEMES` | Pinia `themeStore` + CSS Variables | `el-color-picker` |
| `dialogs.py` | `AiSettingsDialog` | `AiSettingsPanel.vue` | `el-dialog` + `el-tabs` |
| `dialogs.py` | `ViewSettingsDialog` | `ViewSettingsPanel.vue` | `el-dialog` |
| `dialogs.py` | `SearchDialog` | `SearchPanel.vue` | `el-drawer` + `el-input` |
| `chat_dialog.py` | `ChatDialog` | `AiChatPanel.vue` | WebSocket + 聊天 UI |
| `correction_dialog.py` | `CorrectionDialog` | `CorrectionPanel.vue` | WebSocket + diff 视图 |
| `character_dialog.py` | `CharacterDetailDialog` | `CharacterDetail.vue` | `el-dialog` + `el-form` |
| `reference_books.py` | `ReferenceBooksDialog` | `ReferenceBooksView.vue` | `el-dialog` + `el-table` |
| `forms.py` | `BookOutlineFormWidget` | `BookOutlineForm.vue` | `el-form` |
| `forms.py` | `CharacterProfileFormWidget` | `CharacterProfileForm.vue` | `el-form` |
| `forms.py` | `WorldFormWidget` | `WorldForm.vue` | `el-form` |
| `chapter_tabs.py` | `ChapterTabsController` | `ChapterTabBar.vue` | `el-tabs` |
| `workers.py` | `AiWorker` / `FunctionWorker` | WebSocket 连接管理 | Pinia store |
| `star_graph/` | 全部文件 | `StarGraphView.vue` | `@antv/g6` |
| `drawer/overview.py` | `build_overview_tab()` | `OverviewTab.vue` | `el-descriptions` |
| `drawer/shortcuts.py` | `build_shortcuts_tab()` | `ShortcutsTab.vue` | `el-tag` + 快捷键绑定 |
| `drawer/outline.py` | `build_outline_tab()` | `GenerateTab.vue` | `el-input` + WS |
| `drawer/characters.py` | `build_characters_tab()` | `CharactersTab.vue` | `el-card` 列表 |
| `drawer/world.py` | `build_world_tab()` | `WorldTab.vue` | `el-form` + Markdown |
| `drawer/skills.py` | `build_skills_tab()` | `SkillsTab.vue` | `el-collapse` |
| `drawer/analysis.py` | `build_analysis_tab()` | `AnalysisTab.vue` | `el-timeline` |
| `drawer/review.py` | `build_review_tab()` | `ReviewTab.vue` | `el-table` + 快照 diff |
| `drawer/tasks.py` | `build_task_tab()` | `TasksTab.vue` | `el-progress` + 日志流 |

---

## 七、分阶段实施计划

### 阶段 0：基础设施（2 周）

| 任务ID | 任务 | 说明 |
|--------|------|------|
| 0.1 | 项目脚手架搭建 | `lingshu-app` 前端项目（Vite + Vue 3 + Element Plus） |
| 0.2 | 后端模块化重构 | 将 bookstore_api.py 拆分为 lingshu_api/ 路由模块 |
| 0.3 | 数据库桥接层 | `db_bridge.py` 封装 novels.db 访问，统一数据库操作接口 |
| 0.4 | WebSocket 基础设施 | FastAPI WebSocket + 连接管理 + Ping/Pong 保活 |
| 0.5 | Pinia Store 体系 | `bookStore`, `chapterStore`, `characterStore`, `worldStore`, `skillStore`, `taskStore`, `themeStore` |
| 0.6 | 主题系统 | CSS Variables 驱动的 4 套预设（white/light_blue/night/sepia） |
| 0.7 | 布局框架 | 三栏可拖拽 `splitpanes` + 响应式断点 |

### 阶段 1：核心工作台（3 周）

| 任务ID | 任务 | 对应 Qt 模块 | 优先级 |
|--------|------|-------------|--------|
| 1.1 | 书籍列表 + 树视图 `LibraryPanel.vue` | `app_tree.py` | P0 |
| 1.2 | 章节编辑器 `ContentEditor.vue`（Monaco + Markdown 预览） | `app_editor.py` | P0 |
| 1.3 | 章节大纲编辑器 + BookOutlineForm | `forms.py` | P0 |
| 1.4 | 多章节标签管理 `ChapterTabBar.vue` | `chapter_tabs.py` | P0 |
| 1.5 | 字数统计 + 自动保存 | `app_editor.py` 统计部分 | P0 |
| 1.6 | 工作台 REST API（书籍/卷/章 CRUD） | `workspace.py` | P0 |
| 1.7 | 导入向导 `ImportWizard.vue` | `app_import.py` | P1 |

### 阶段 2：抽屉面板 — 数据管理（3 周）

| 任务ID | 任务 | 对应 Qt 模块 | 优先级 |
|--------|------|-------------|--------|
| 2.1 | 概览 Tab `OverviewTab.vue` | `drawer/overview.py` | P1 |
| 2.2 | 人物 Tab + 详情对话框 | `drawer/characters.py` + `character_dialog.py` | P0 |
| 2.3 | 世界观 Tab `WorldTab.vue` | `drawer/world.py` | P0 |
| 2.4 | Skills Tab `SkillsTab.vue` | `drawer/skills.py` | P1 |
| 2.5 | 快键 Tab `ShortcutsTab.vue` | `drawer/shortcuts.py` | P2 |
| 2.6 | 人物/世界观/参考书/技能 REST API | 多个路由 | P0 |

### 阶段 3：AI 能力迁移（4 周）

| 任务ID | 任务 | 对应 Qt 模块 | 优先级 |
|--------|------|-------------|--------|
| 3.1 | WebSocket 生成流水线 `/ws/generation` | `app_generation.py` + `workers.py` | P0 |
| 3.2 | 生成 Tab `GenerateTab.vue`（大纲→生成→进度） | `drawer/outline.py` | P0 |
| 3.3 | WebSocket AI 对话 `/ws/chat` | `chat_dialog.py` | P0 |
| 3.4 | AI 对话面板 `AiChatPanel.vue` | `chat_dialog.py` | P0 |
| 3.5 | WebSocket AI 审查 `/ws/review` | `app_review_tasks.py` | P1 |
| 3.6 | 审查记录 Tab `ReviewTab.vue` | `drawer/review.py` | P1 |
| 3.7 | WebSocket 全书分析 `/ws/analysis` | `app_analysis.py` | P1 |
| 3.8 | 分析 Tab `AnalysisTab.vue`（diff 查看/应用/拒绝） | `drawer/analysis.py` | P1 |
| 3.9 | 任务面板 Tab `TasksTab.vue` | `drawer/tasks.py` | P1 |
| 3.10 | AI 纠错面板 `CorrectionPanel.vue` | `correction_dialog.py` | P2 |

### 阶段 4：高级功能（3 周）

| 任务ID | 任务 | 对应 Qt 模块 | 优先级 |
|--------|------|-------------|--------|
| 4.1 | RAG 检索 API + 工作台集成 | `novel_app/rag/` | P1 |
| 4.2 | 参考书库管理 `ReferenceBooksView.vue` | `reference_books.py` | P1 |
| 4.3 | 星图关系可视化 `StarGraphView.vue`（G6） | `star_graph/` | P2 |
| 4.4 | 导出功能 `ExportDialog.vue` + 服务端文件生成 | `app_settings_export.py` | P1 |
| 4.5 | AI 设置面板 `AiSettingsPanel.vue` | `dialogs.py` AiSettingsDialog | P1 |
| 4.6 | 视图设置面板 `ViewSettingsPanel.vue` | `dialogs.py` ViewSettingsDialog | P2 |
| 4.7 | 全文搜索面板 `SearchPanel.vue` | `dialogs.py` SearchDialog | P2 |
| 4.8 | 全局快捷键绑定 + 专注模式 | `app_tree.py` 快捷键 | P2 |

### 阶段 5：桌面打包与收尾（2 周）

| 任务ID | 任务 | 说明 | 优先级 |
|--------|------|------|--------|
| 5.1 | Electron 壳应用搭建 | main process + preload，替换 `Launcher.cs` | P1 |
| 5.2 | 本地文件系统访问 + DPAPI 密钥安全存储 | `secure_storage.py` 适配 | P1 |
| 5.3 | 应用图标 + 启动画面 | `LoadingScreen.vue` 替代 `startup.py` | P2 |
| 5.4 | 自动更新机制 | `electron-updater` | P2 |
| 5.5 | 移除 PyQt6 依赖 | 清理 `requirements.txt` | P0 |
| 5.6 | 回归测试 | 103 条测试用例适配 | P0 |

### 阶段 6：统一与清理（1 周）

| 任务ID | 任务 | 说明 |
|--------|------|------|
| 6.1 | 三端入口统一 | 创作工作台 + 书城 + 管理后台合并到单一 Vite 多页应用 |
| 6.2 | 清理 Qt 代码 | 删除 `novel_app/qt/` 全部文件 |
| 6.3 | 文档更新 | 更新 `CHANGELOG.md`、`README.md` |
| 6.4 | CI/CD 更新 | 更新 `.github/workflows/ci.yml` |

---

## 八、项目目录结构（迁移后）

```
灵枢/
├── lingshu_app/              # Vue 3 前端（新建）
│   ├── public/
│   │   └── lingshu-bg.jpg
│   ├── src/
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── AppLayout.vue
│   │   │   │   ├── GlobalHeaderBar.vue
│   │   │   │   ├── StatusBar.vue
│   │   │   │   └── LoadingScreen.vue
│   │   │   ├── workspace/
│   │   │   │   ├── WorkspaceLayout.vue
│   │   │   │   ├── LibraryPanel.vue
│   │   │   │   ├── ContentEditor.vue
│   │   │   │   ├── OutlineEditor.vue
│   │   │   │   ├── ChapterTabBar.vue
│   │   │   │   └── StatsCard.vue
│   │   │   ├── drawer/
│   │   │   │   ├── DrawerPanel.vue
│   │   │   │   ├── OverviewTab.vue
│   │   │   │   ├── ShortcutsTab.vue
│   │   │   │   ├── GenerateTab.vue
│   │   │   │   ├── CharactersTab.vue
│   │   │   │   ├── WorldTab.vue
│   │   │   │   ├── SkillsTab.vue
│   │   │   │   ├── AnalysisTab.vue
│   │   │   │   ├── ReviewTab.vue
│   │   │   │   └── TasksTab.vue
│   │   │   ├── dialogs/
│   │   │   │   ├── AiSettingsPanel.vue
│   │   │   │   ├── ViewSettingsPanel.vue
│   │   │   │   ├── ExportDialog.vue
│   │   │   │   ├── ImportWizard.vue
│   │   │   │   ├── AiChatPanel.vue
│   │   │   │   ├── CorrectionPanel.vue
│   │   │   │   ├── CharacterDetail.vue
│   │   │   │   └── SearchPanel.vue
│   │   │   ├── forms/
│   │   │   │   ├── BookOutlineForm.vue
│   │   │   │   ├── CharacterProfileForm.vue
│   │   │   │   └── WorldForm.vue
│   │   │   ├── star-graph/
│   │   │   │   └── StarGraphView.vue
│   │   │   └── shared/
│   │   │       ├── WordCount.vue
│   │   │       ├── AiBadge.vue
│   │   │       └── SplitPane.vue
│   │   ├── stores/
│   │   │   ├── book.js
│   │   │   ├── chapter.js
│   │   │   ├── character.js
│   │   │   ├── world.js
│   │   │   ├── skill.js
│   │   │   ├── task.js
│   │   │   ├── theme.js
│   │   │   ├── auth.js
│   │   │   └── ws.js
│   │   ├── composables/
│   │   │   ├── useWebSocket.js
│   │   │   ├── useAutoSave.js
│   │   │   ├── useKeyboard.js
│   │   │   └── useTheme.js
│   │   ├── utils/
│   │   │   ├── api.js
│   │   │   └── crypto.js
│   │   ├── router.js
│   │   ├── App.vue
│   │   └── main.js
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── lingshu_api/              # 统一 FastAPI 后端（新建/重构）
│   ├── __init__.py
│   ├── main.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── bookshelf.py
│   │   ├── bookstore.py
│   │   ├── admin.py
│   │   ├── workspace.py
│   │   ├── characters.py
│   │   ├── world.py
│   │   ├── skills.py
│   │   ├── analysis.py
│   │   ├── review.py
│   │   ├── references.py
│   │   ├── export.py
│   │   ├── import_doc.py
│   │   └── rag.py
│   ├── ws/
│   │   ├── generation.py
│   │   ├── review_ws.py
│   │   ├── analysis_ws.py
│   │   └── chat.py
│   ├── schemas/
│   │   ├── workspace.py
│   │   └── ws_messages.py
│   └── services/
│       ├── db_bridge.py
│       └── file_service.py
│
├── novel_app/                # 核心服务层（保留，移除 qt/）
│   ├── agents/               # 保留
│   ├── analysis/             # 保留
│   ├── audit/                # 保留
│   ├── core/                 # 保留
│   ├── db/                   # 保留
│   ├── rag/                  # 保留
│   ├── state/                # 保留
│   ├── structured_templates/ # 保留
│   ├── theme/                # 保留
│   ├── truth/                # 保留
│   ├── ai_*.py               # 保留
│   ├── database.py           # 保留
│   ├── exporter.py           # 保留
│   ├── model_router.py       # 保留
│   ├── secure_storage.py     # 保留
│   └── ...                   # 保留
│   # novel_app/qt/ → 删除
│
├── web/                      # 现有读者端（保留，后续统一）
├── admin-web/                # 现有管理后台（保留，后续统一）
├── tests/                    # 测试（适配新 API）
├── docs/                     # 文档
└── electron/                 # Electron 壳（新建，可选）
    ├── main.js
    ├── preload.js
    └── package.json
```

---

## 九、依赖变更一览

### 9.1 Python 端

```diff
# requirements.txt
- PyQt6==6.11.0              # 移除 GPL v3 依赖
- PyQt6-Qt6==6.11.1          # 移除
- PyQt6-sip==13.11.1         # 移除
  fastapi>=0.115,<1          # 已有（保留）
  uvicorn>=0.23,<1           # 已有（保留）
+ websockets>=12,<14         # 新增: WebSocket 支持
+ python-multipart>=0.0.9    # 新增: 文件上传
  qdrant-client==1.17.1      # 保留
  python-docx==1.1.2         # 保留
```

### 9.2 前端端

```diff
# lingshu_app/package.json
+ "vue": "^3.5"              # 框架
+ "element-plus": "^2.9"     # UI 库
+ "pinia": "^2.3"            # 状态管理
+ "vue-router": "^4.5"       # 路由
+ "axios": "^1.7"            # HTTP
+ "splitpanes": "^3.1"       # 分割面板
+ "@guolao/vue-monaco-editor": "^1.5"  # 代码编辑器
+ "marked": "^12.0"          # Markdown 渲染
+ "highlight.js": "^11.9"    # 代码高亮
+ "@antv/g6": "^5.0"         # 星图可视化
+ "echarts": "^6.1"          # 图表（已有）
```

---

## 十、风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| Monaco Editor 大文件性能 | 10 万字以上章节编辑卡顿 | 虚拟滚动 + 分片加载 + 防抖保存 |
| WebSocket 长任务超时 | AI 生成/分析可能耗时数分钟 | 心跳保活 + 断线重连 + 任务持久化恢复 |
| DPAPI 加密无法跨平台 | Electron 中不可直接调用 Windows DPAPI | `electron-safe-storage` 或 `keytar` 替代 |
| 103 条测试用例需适配 | 测试从 Qt UI 测试变更为 API 测试 | 增量迁移，保留核心业务逻辑测试 |
| AI 流式输出延迟 | WebSocket 方案比 Qt 线程通信有额外延迟 | 使用 SSE 作为备选方案，降低 WebSocket 复杂度 |
| 团队 Vue 学习曲线 | 原 Qt/Python 开发者需学习 Vue 生态 | 阶段 0 预留学习时间，提供模板和脚手架 |

---

## 十一、总结

| 维度 | 迁移前 | 迁移后 |
|------|--------|--------|
| 许可证风险 | CRITICAL (PyQt6 GPL v3) | 消除 (MIT + MIT) |
| 技术栈 | Qt + Vue 双轨 | Vue 全栈统一 |
| 跨平台 | Windows only | Windows + macOS + Linux |
| 后端 API | 50 端点 (仅书城/管理) | 80+ 端点 + 4 路 WebSocket |
| 部署方式 | .exe 单文件 | Web 直接访问 + 可选 Electron 桌面壳 |
| 维护成本 | 两套 UI 框架 | 单一技术栈 |

**建议优先推进阶段 0-2**（基础设施 + 核心工作台 + 数据管理），这三阶段完成后即可获得一个功能完备的创作工作台，后续 AI 能力和高级功能可逐步叠加。
