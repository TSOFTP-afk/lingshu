from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from lingshu_api.dependencies import require_login
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.reference_books import (
    BOOK_REFERENCE_ROLES,
    read_reference_text_file,
    reference_source_path,
    split_reference_text_into_segments,
)

router = APIRouter(prefix="/api/workspace", tags=["references"])
logger = logging.getLogger(__name__)

ALLOWED_REFERENCE_SUFFIXES = {".txt", ".md", ".markdown", ".docx"}


class BindReferencePayload(BaseModel):
    """绑定参考书请求体。"""
    role: str = "style_reference"
    notes: str = ""


class UpdateReferencePayload(BaseModel):
    """更新参考书绑定请求体。"""
    role: str | None = None
    enabled: bool | None = None
    notes: str | None = None


@router.get("/books/{book_id}/references")
async def get_book_references(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    if not db.get_book(book_id):
        return {"items": [], "context": ""}
    try:
        refs = [dict(r) for r in db.db.list_book_reference_sources(book_id, enabled_only=False)]
        context = db.db.build_book_reference_context(book_id)
        return {"items": refs, "context": context}
    except Exception:
        return {"items": [], "context": ""}


@router.get("/references")
async def list_all_references(user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    try:
        refs = [dict(r) for r in db.db.list_reference_sources()]
        return {"items": refs}
    except Exception:
        return {"items": []}


@router.post("/references/import-file")
async def import_reference_file(
    file: UploadFile = File(...),
    book_id: int | None = Form(default=None),
    title: str = Form(default=""),
    author: str = Form(default=""),
    role: str = Form(default="style_reference"),
    notes: str = Form(default=""),
    rights_note: str = Form(default="user_imported"),
    source_type: str = Form(default="book"),
    source_url: str = Form(default=""),
    source_license: str = Form(default=""),
    reusable_level: str = Form(default="pattern_only"),
    attribution_note: str = Form(default=""),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    target_book_id = int(book_id) if book_id else None
    if target_book_id and not db.get_book(target_book_id):
        raise HTTPException(status_code=404, detail="Book not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Reference file is empty")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Reference file exceeds 50MB")

    suffix = Path(file.filename or "reference.txt").suffix.lower()
    if suffix not in ALLOWED_REFERENCE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only txt, md, markdown and docx are supported")

    stored_path = _store_reference_upload(db, file.filename or "reference.txt", raw)
    try:
        text = read_reference_text_file(stored_path)
    except Exception as exc:
        _delete_if_safe(db, stored_path)
        logger.exception("Cannot read reference file")
        raise HTTPException(status_code=400, detail="Cannot read reference file") from exc

    if not text.strip():
        _delete_if_safe(db, stored_path)
        raise HTTPException(status_code=400, detail="Reference file is empty")

    source_title = title.strip() or Path(file.filename or "reference").stem.strip() or "Imported reference"
    source_id = db.db.create_reference_source(
        source_title,
        _relative_to_data_dir(db, stored_path),
        author=author,
        rights_note=rights_note,
        source_type=source_type,
        source_url=source_url,
        source_license=source_license,
        reusable_level=reusable_level,
        attribution_note=attribution_note,
    )

    result = {"ok": True, "source_id": source_id, "item": _row_to_dict(db.db.get_reference_source(source_id))}
    if target_book_id:
        result.update(_bind_reference(db, target_book_id, source_id, role=role, notes=notes))
    return result


@router.post("/books/{book_id}/references/{source_id}")
async def bind_reference_to_book(
    book_id: int,
    source_id: int,
    body: BindReferencePayload = BindReferencePayload(),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    return {
        "ok": True,
        **_bind_reference(
            db,
            book_id,
            source_id,
            role=body.role,
            notes=body.notes,
        ),
    }


@router.patch("/books/{book_id}/references/{source_id}")
async def update_book_reference(
    book_id: int,
    source_id: int,
    body: UpdateReferencePayload,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    _ensure_book_and_source(db, book_id, source_id)
    db.db.update_book_reference_binding(
        book_id,
        source_id,
        role=_normalize_role(body.role) if body.role is not None else None,
        enabled=body.enabled,
        notes=str(body.notes or "") if body.notes is not None else None,
    )
    return {"ok": True}


@router.delete("/books/{book_id}/references/{source_id}")
async def unbind_reference_from_book(
    book_id: int,
    source_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    _ensure_book_and_source(db, book_id, source_id)
    db.db.unbind_reference_source_from_book(book_id, source_id)
    return {"ok": True}


@router.get("/books/{book_id}/references/{source_id}/segments")
async def list_reference_segments(
    book_id: int,
    source_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    _ensure_book_and_source(db, book_id, source_id)
    rows = db.db.list_book_reference_segments(book_id, source_id=source_id, limit=500)
    return {"items": [dict(row) for row in rows]}


@router.delete("/references/{source_id}")
async def delete_reference_source(source_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    source = db.db.get_reference_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Reference source not found")
    path = reference_source_path(dict(source), db.db.data_dir)
    db.db.delete_reference_source(source_id)
    _delete_if_safe(db, path)
    return {"ok": True}


def _bind_reference(
    db: WorkspaceDB,
    book_id: int,
    source_id: int,
    *,
    role: str,
    notes: str,
) -> dict:
    _ensure_book_and_source(db, book_id, source_id)
    binding_id = db.db.bind_reference_source_to_book(
        book_id,
        source_id,
        role=_normalize_role(role),
        notes=notes,
    )
    source = dict(db.db.get_reference_source(source_id) or {})
    path = reference_source_path(source, db.db.data_dir)
    try:
        text = read_reference_text_file(path)
    except Exception as exc:
        logger.exception("Cannot read reference source")
        raise HTTPException(status_code=400, detail="Cannot read reference source") from exc
    segments = split_reference_text_into_segments(text)
    db.db.create_book_reference_segments(book_id, source_id, segments)
    return {
        "binding_id": binding_id,
        "book_id": book_id,
        "source_id": source_id,
        "stats": {"segment_count": len(segments), "total_chars": len(text)},
    }


def _ensure_book_and_source(db: WorkspaceDB, book_id: int, source_id: int) -> None:
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    if not db.db.get_reference_source(source_id):
        raise HTTPException(status_code=404, detail="Reference source not found")


def _store_reference_upload(db: WorkspaceDB, filename: str, raw: bytes) -> Path:
    suffix = Path(filename).suffix.lower() or ".txt"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip(".-") or "reference"
    stored = db.db.references_dir / f"{uuid.uuid4().hex[:12]}-{safe_stem}{suffix}"
    stored.write_bytes(raw)
    return stored


def _relative_to_data_dir(db: WorkspaceDB, path: Path) -> str:
    try:
        return path.resolve().relative_to(db.db.data_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _delete_if_safe(db: WorkspaceDB, path: Path) -> None:
    try:
        resolved = path.resolve()
        root = db.db.references_dir.resolve()
        if root in resolved.parents or resolved == root:
            resolved.unlink(missing_ok=True)
    except Exception:
        pass


def _normalize_role(role: object) -> str:
    allowed = {key for key, _label in BOOK_REFERENCE_ROLES}
    value = str(role or "style_reference").strip() or "style_reference"
    return value if value in allowed else "style_reference"


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}
