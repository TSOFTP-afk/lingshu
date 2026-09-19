"""
工作台核心 API — 聚合模块（原 1680 行单文件按数据域拆分而来）。

对应迁移的 Qt 模块:
- app_tree.py    → 书籍/分卷/章节列表 + 树结构
- app_editor.py  → 章节正文+大纲保存/读取
- app_import.py  → 文件导入 (TXT/DOCX)
- forms.py       → 书籍大纲表单 (已有 structured_templates)

拆分后的子路由（URL / 方法 / 模型 / 依赖注入签名均与拆分前完全一致）:
- workspace_books.py     → 书籍/分卷/章节 CRUD、搜索、书籍大纲
- workspace_ai.py        → AI 率检测、选区润色（require_ai_access）
- workspace_probes.py    → 写作探针伴随机制
- workspace_snapshots.py → 章节快照 + 生成快照
- workspace_writeback.py → 分析运行 / 草案卡 / 写回
- workspace_import.py    → 文件导入 (TXT/MD/DOCX/EPUB)
- workspace_common.py    → 跨域共享辅助（日志通道、_check_chapter_owner）
"""
from fastapi import APIRouter

from lingshu_api.routers.workspace_ai import router as ai_router
from lingshu_api.routers.workspace_books import router as books_router
from lingshu_api.routers.workspace_import import router as import_router
from lingshu_api.routers.workspace_probes import router as probes_router
from lingshu_api.routers.workspace_snapshots import router as snapshots_router
from lingshu_api.routers.workspace_writeback import router as writeback_router

# 与拆分前 main.py 的注册方式保持一致：app.include_router(workspace.router)
router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# include 顺序保持与原文件端点声明顺序一致
router.include_router(books_router)
router.include_router(ai_router)
router.include_router(probes_router)
router.include_router(snapshots_router)
router.include_router(writeback_router)
router.include_router(import_router)
