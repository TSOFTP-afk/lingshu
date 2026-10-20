"""
人物管理 API — 对应 Qt drawer/characters.py + character_dialog.py
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from lingshu_api.dependencies import check_book_owner, require_login
from lingshu_api.schemas.workspace import (
    CharacterCreate,
    CharacterLinkBook,
    CharacterSnapshotCreate,
    CharacterUpdate,
    CycleCreate,
    StateMachineUpdate,
)
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.structured_templates import (
    PROTAGONIST_FORM_SCHEMA,
    SUPPORTING_CHARACTER_FORM_SCHEMA,
    character_profile_schema_for_role,
)

MAX_IMAGE_SIZE = 5 * 1024 * 1024

router = APIRouter(prefix="/api/workspace", tags=["characters"])
_cloud_logger = logging.getLogger(__name__)


def _character_payload(item: dict[str, Any], db: WorkspaceDB) -> dict[str, Any]:
    character_id = int(item.get("id") or 0)
    role = str(item.get("role", "") or "")
    payload = dict(item)
    payload["profile_data"] = db.db.get_character_profile_form(character_id) if character_id else {}
    payload["profile_schema"] = character_profile_schema_for_role(role)
    return payload


def _character_schemas() -> dict[str, list[dict[str, Any]]]:
    return {
        "protagonist": PROTAGONIST_FORM_SCHEMA,
        "supporting": SUPPORTING_CHARACTER_FORM_SCHEMA,
    }


def _is_admin(user: dict) -> bool:
    return bool(int(user.get("is_admin") or 0))


def _require_character_write_access(
    db: WorkspaceDB, char: dict[str, Any], user: dict
) -> int:
    """写操作归属校验，返回归属 book_id。

    归属书籍的人物：必须通过书籍归属校验（不得因 book_id 缺失跳过）；
    全局人物（book_id 无效/为 0）：仅管理员可写，普通用户 403。
    """
    book_id = int(char.get("book_id") or 0)
    if book_id:
        check_book_owner(db, book_id, user)
    elif not _is_admin(user):
        raise HTTPException(status_code=403, detail="全局人物仅管理员可修改")
    return book_id


@router.get("/books/{book_id}/characters")
def list_characters(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出作品下的人物（含全局人物）。"""
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    check_book_owner(db, book_id, user)
    items = db.list_characters(book_id)
    return {
        "items": [_character_payload(item, db) for item in items],
        "schemas": _character_schemas(),
    }


@router.post("/books/{book_id}/characters")
def create_character(request: Request, book_id: int, payload: CharacterCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """创建人物。"""
    check_book_owner(db, book_id, user)
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="人物名称不能为空")
    char = db.create_character(
        book_id, name,
        profile_text=payload.profile_text,
        profile_data=payload.profile_data,
    )
    return {"ok": True, "item": _character_payload(char, db), "schemas": _character_schemas()}


@router.get("/characters/{character_id}")
def get_character(character_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取人物详情。"""
    char = db.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="人物不存在")
    book_id = int(char.get("book_id") or 0)
    if book_id:
        check_book_owner(db, book_id, user)
    return {**_character_payload(char, db), "schemas": _character_schemas()}


@router.patch("/characters/{character_id}")
def update_character(request: Request, character_id: int, payload: CharacterUpdate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """更新人物（名称/角色/描述/图片路径）。"""
    char = db.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="人物不存在")
    _require_character_write_access(db, char, user)
    kwargs = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if kwargs:
        db.update_character(character_id, **kwargs)
    item = db.get_character(character_id)
    return {"ok": True, "item": _character_payload(item, db) if item else None, "schemas": _character_schemas()}


@router.delete("/characters/{character_id}")
def delete_character(request: Request, character_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除人物。"""
    char = db.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="人物不存在")
    _require_character_write_access(db, char, user)
    db.delete_character(character_id)
    return {"ok": True}


@router.post("/characters/{character_id}/link-book")
def link_character_to_book(character_id: int, payload: CharacterLinkBook, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """将人物关联到书籍。"""
    book_id = payload.book_id
    if not book_id:
        raise HTTPException(status_code=400, detail="book_id 必填")
    check_book_owner(db, book_id, user)
    db.link_character_to_book(character_id, book_id)
    return {"ok": True}


@router.post("/characters/{character_id}/unlink-book")
def unlink_character_from_book(character_id: int, payload: CharacterLinkBook, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """解除人物与书籍的关联。"""
    book_id = payload.book_id
    if not book_id:
        raise HTTPException(status_code=400, detail="book_id 必填")
    check_book_owner(db, book_id, user)
    db.unlink_character_from_book(character_id, book_id)
    return {"ok": True}


@router.post("/characters/{character_id}/image")
async def upload_character_image(
    character_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """上传人物立绘图片。"""
    char = db.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="人物不存在")
    _require_character_write_access(db, char, user)
    raw = await file.read()
    if len(raw) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="图片大小不能超过 5MB")
    # 保存到 media/character_images/
    import uuid
    from pathlib import Path
    ext = Path(file.filename or "image.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        raise HTTPException(status_code=400, detail="不支持的图片格式")
    dest_dir = db.db.character_images_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{uuid.uuid4().hex}_{character_id}{ext}"
    dest_path = dest_dir / file_name
    dest_path.write_bytes(raw)
    # 更新数据库
    rel_path = f"media/character_images/{file_name}"
    db.db.update_character_image(character_id, str(dest_path))
    return {"ok": True, "path": rel_path}


# ================================================================
#  人物状态机
# ================================================================


def _load_character_with_owner(
    character_id: int, user: dict, db: WorkspaceDB, *, require_write: bool = False
) -> tuple[dict[str, Any], int]:
    """加载人物并校验书籍归属，返回 (character, book_id)。不存在则抛 404。

    读操作：归属书籍的人物校验归属，全局人物对登录用户开放；
    写操作（require_write=True）：全局人物仅管理员可写。
    """
    char = db.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="人物不存在")
    if require_write:
        book_id = _require_character_write_access(db, char, user)
        return char, book_id
    book_id = int(char.get("book_id") or 0)
    if book_id:
        check_book_owner(db, book_id, user)
    return char, book_id


@router.get("/characters/{character_id}/state-machine")
def get_state_machine(
    character_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """获取人物状态机（三轴+价值观+运行态快照），不存在时自动创建空记录。"""
    _load_character_with_owner(character_id, user, db)
    sm = db.get_state_machine(character_id)
    return {"item": sm}


@router.patch("/characters/{character_id}/state-machine")
def update_state_machine(
    request: Request,
    character_id: int,
    payload: StateMachineUpdate,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """更新人物状态机字段（仅更新提供的字段）。"""
    _load_character_with_owner(character_id, user, db, require_write=True)
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="未提供更新字段")
    try:
        updated = db.update_state_machine(character_id, data)
        return {"item": updated}
    except HTTPException:
        raise
    except Exception as exc:
        _cloud_logger.exception("更新状态机失败 character_id=%s", character_id)
        raise HTTPException(status_code=500, detail="更新状态机失败") from exc


@router.get("/characters/{character_id}/cycles")
def list_cycles(
    character_id: int,
    cycle_type: str | None = None,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """列出人物的循环日志，可按 cycle_type 过滤。"""
    _load_character_with_owner(character_id, user, db)
    items = db.list_cycles(character_id, cycle_type)
    return {"items": items}


@router.post("/characters/{character_id}/cycles")
def create_cycle(
    request: Request,
    character_id: int,
    payload: CycleCreate,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """创建循环日志（自动处理增值累计与快照存档）。"""
    _load_character_with_owner(character_id, user, db, require_write=True)
    try:
        result = db.create_cycle(character_id, payload.model_dump())
        return {"item": result}
    except HTTPException:
        raise
    except Exception as exc:
        _cloud_logger.exception("创建循环日志失败 character_id=%s", character_id)
        raise HTTPException(status_code=500, detail="创建循环日志失败") from exc


@router.get("/characters/{character_id}/snapshots")
def list_character_snapshots(
    character_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """列出人物的快照存档。"""
    _load_character_with_owner(character_id, user, db)
    items = db.list_character_snapshots(character_id)
    return {"items": items}


@router.post("/characters/{character_id}/snapshots")
def create_character_snapshot(
    request: Request,
    character_id: int,
    payload: CharacterSnapshotCreate,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """手动触发快照存档。"""
    _load_character_with_owner(character_id, user, db, require_write=True)
    try:
        item = db.create_character_snapshot(
            character_id,
            trigger_type="manual",
            trigger_detail=payload.trigger_detail,
            phase_change_summary=payload.phase_change_summary,
            micro_cycle_summary=payload.micro_cycle_summary,
        )
        return {"item": item}
    except HTTPException:
        raise
    except Exception as exc:
        _cloud_logger.exception("创建快照存档失败 character_id=%s", character_id)
        raise HTTPException(status_code=500, detail="创建快照存档失败") from exc
