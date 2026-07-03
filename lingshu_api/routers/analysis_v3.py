"""analysis_v3 路由垫片文件 — 重导出拆分后的三个子模块路由。

原 1410 行的单文件已拆分为：
  - analysis_v3_runs.py  — 分析运行管理（创建/查询/取消运行）
  - analysis_v3_steps.py — 分析步骤执行（实体提及/共指/原子事实等）
  - analysis_v3_cards.py — 卡片操作（查询/写回/批量写回）

本文件保留 router 属性以兼容 main.py 中的路由注册。
"""
from __future__ import annotations

from fastapi import APIRouter

from lingshu_api.routers.analysis_v3_cards import router as cards_router
from lingshu_api.routers.analysis_v3_runs import router as runs_router
from lingshu_api.routers.analysis_v3_steps import router as steps_router

# 合并三个子路由为统一 router，保持与 main.py 中 analysis_v3.router 的兼容
router = APIRouter(tags=["analysis-v3"])
router.include_router(runs_router)
router.include_router(steps_router)
router.include_router(cards_router)

# 重导出子模块的公共函数，供外部引用（如 analysis_v3_ws.py）
from lingshu_api.routers.analysis_v3_runs import (  # noqa: E402, F401
    _analysis_v3_run_item,
    _check_run_book_owner,
    _check_run_book_owner_for_book,
    _create_required_analysis_ai_provider,
    _get_analysis_v3_run_or_404,
    _is_analysis_v3_run,
    _load_chapters_for_analysis,
    _classify_error_text,
)
from lingshu_api.routers.analysis_v3_steps import (  # noqa: E402, F401
    _analysis_v3_backtrack_task_item,
    _analysis_v3_event_item,
    _count_by,
    _count_rows_by,
    _row_value,
    get_analysis_v3_review_summary,
)
from lingshu_api.routers.analysis_v3_cards import (  # noqa: E402, F401
    _analysis_v3_card_item,
    _analysis_v3_dependency_item,
    _create_writeback_card_generator,
)
