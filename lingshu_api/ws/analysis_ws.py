"""
全书分析 WebSocket — Legacy 三层金字塔编排已移除。

原三级分析管线（level1/level2/level3）和 one-shot 分析已被 V3 AI 增强分析替代。
新代码应使用 /ws/analysis-v3 端点（lingshu_api.ws.analysis_v3_ws）。
详见 .trae/specs/ai-v3-replace-three-layer/spec.md
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket

from lingshu_api.ws.connection import authenticate_ws, get_ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/analysis")
async def ws_analysis_legacy(ws: WebSocket):
    """Compatibility shim for the removed legacy analysis socket."""
    conn = await authenticate_ws(ws)
    if conn is None:
        return
    manager = get_ws_manager()
    client_id = conn.client_id
    try:
        while True:
            raw = await ws.receive_text()
            await manager.send(
                client_id,
                {
                    "type": "error",
                    "task_id": "",
                    "payload": {
                        "message": "Legacy /ws/analysis has been replaced by /ws/analysis-v3.",
                        "received": raw[:200],
                    },
                },
            )
    except Exception:
        pass
    finally:
        manager.disconnect(client_id)
