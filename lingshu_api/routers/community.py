"""
社区卡片帖子路由 — 浏览、上传、删除社区卡片。

公开接口（GET）无需登录；写入接口（POST/DELETE）需登录。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from lingshu_api.dependencies import require_login
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.community.store import CommunityStore, DuplicatePostError

router = APIRouter(prefix="/api/community", tags=["community"])
logger = logging.getLogger(__name__)

_VALID_CARD_TYPES = ("world", "character")


class CardUploadRequest(BaseModel):
    """上传卡片到社区的请求体。"""
    card_type: str = Field(..., description="卡片类型：'world' 或 'character'")
    source_book_id: int = Field(..., description="来源书籍 id")
    source_card_id: int = Field(default=0, description="来源角色 id（世界观卡片传 0）")
    intro: str = Field(default="", max_length=100, description="简介，最多 100 字")


# ──────────────────── 浏览（公开）────────────────────


@router.get("/cards")
def list_cards(
    type: str | None = None,  # noqa: A002 — FastAPI 查询参数名固定为 type（API 契约）
    page: int = 1,
    page_size: int = 20,
    db: WorkspaceDB = Depends(get_workspace_db),
) -> dict[str, Any]:
    """列出社区卡片帖子（公开浏览，按创建时间倒序分页）。"""
    if type is not None and type not in _VALID_CARD_TYPES:
        raise HTTPException(status_code=400, detail="type 仅支持 'world' 或 'character'")
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    elif page_size > 100:
        page_size = 100

    store = CommunityStore(db.db)
    try:
        return store.list_posts(card_type=type, page=page, page_size=page_size)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("列出社区卡片失败 type=%s page=%s page_size=%s", type, page, page_size)
        raise HTTPException(status_code=500, detail="获取社区卡片列表失败，请稍后重试") from exc


@router.get("/cards/{post_id}")
def get_card(
    post_id: int,
    db: WorkspaceDB = Depends(get_workspace_db),
) -> dict[str, Any]:
    """获取单个社区卡片帖子详情（公开浏览，自增浏览数）。"""
    store = CommunityStore(db.db)
    try:
        post = store.get_post(post_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("获取社区卡片失败 post_id=%s", post_id)
        raise HTTPException(status_code=500, detail="获取社区卡片失败，请稍后重试") from exc
    if post is None:
        raise HTTPException(status_code=404, detail="卡片不存在")
    return post


# ──────────────────── 上传（需登录）────────────────────


@router.post("/cards", status_code=201)
def upload_card(
    payload: CardUploadRequest,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
) -> dict[str, Any]:
    """上传卡片到社区（需登录）。"""
    user_id = int(user["id"])
    intro = (payload.intro or "").strip()
    store = CommunityStore(db.db)
    try:
        new_id = store.create_post(
            poster_user_id=user_id,
            card_type=payload.card_type,
            source_book_id=payload.source_book_id,
            source_card_id=payload.source_card_id,
            intro=intro,
        )
    except DuplicatePostError as exc:
        raise HTTPException(status_code=409, detail="该卡片已上传到社区") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "上传社区卡片失败 user_id=%s card_type=%s source_book_id=%s",
            user_id, payload.card_type, payload.source_book_id,
        )
        raise HTTPException(status_code=500, detail="上传失败，请稍后重试") from exc
    return {"id": new_id, "message": "上传成功"}


# ──────────────────── 删除（需登录）────────────────────


@router.delete("/cards/{post_id}", status_code=204)
def delete_card(
    post_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
) -> Response:
    """删除自己上传的社区卡片（需登录，仅限本人）。"""
    user_id = int(user["id"])
    store = CommunityStore(db.db)
    try:
        deleted = store.delete_post(post_id, user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="无权删除他人上传的卡片") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("删除社区卡片失败 post_id=%s user_id=%s", post_id, user_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="卡片不存在")
    return Response(status_code=204)
