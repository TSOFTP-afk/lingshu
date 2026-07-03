"""
导出 API — 对应 Qt app_settings_export.py + novel_app/exporter.py
"""
import contextlib
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from lingshu_api.dependencies import check_book_owner, require_login
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db

router = APIRouter(prefix="/api/workspace", tags=["export"])
logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    """过滤文件名，仅保留字母数字、中文、下划线、连字符和点号。"""
    return re.sub(r"[^\w\u4e00-\u9fff.\-]", "_", name)[:40]


def _content_disposition(safe_name: str, ext: str) -> str:
    """构建 Content-Disposition 头，中文文件名使用 RFC 5987 编码。

    latin-1 编码无法表示中文，filename* 参数用 UTF-8 百分号编码传输中文。
    同时提供 ASCII fallback filename 避免老客户端无法解析。
    """
    from urllib.parse import quote
    ascii_fallback = re.sub(r"[^\x20-\x7e]", "_", safe_name) or "export"
    quoted = quote(f"{safe_name}{ext}", safe="")
    return f"attachment; filename=\"{ascii_fallback}{ext}\"; filename*=UTF-8''{quoted}"


@router.get("/books/{book_id}/export")
def export_book(
    book_id: int,
    fmt: str = Query(default="txt", description="导出格式: txt|md|docx"),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """导出全书为 TXT / Markdown / DOCX。"""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="作品不存在")
    check_book_owner(db, book_id, user)

    out = None
    try:
        import os
        import tempfile

        from novel_app.exporter import BookExporter
        exporter = BookExporter(db.db)
        ext = {"txt": ".txt", "md": ".md", "docx": ".docx"}.get(fmt, ".txt")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            out = Path(tmp.name)

        if fmt == "docx":
            exporter.export_docx(book_id, out)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt == "md":
            exporter.export_markdown(book_id, out)
            media = "text/markdown"
        else:
            exporter.export_txt(book_id, out)
            media = "text/plain"

        data = out.read_bytes()
        safe_name = _sanitize_filename(book.get("title", "export"))
        return Response(content=data, media_type=media, headers={
            "Content-Disposition": _content_disposition(safe_name, ext)
        })
    except Exception as exc:
        logger.exception("导出失败")
        raise HTTPException(status_code=500, detail="导出失败，请稍后重试") from exc
    finally:
        if out is not None:
            with contextlib.suppress(OSError):
                os.unlink(out)


@router.get("/chapters/{chapter_id}/export")
def export_chapter(
    chapter_id: int,
    fmt: str = Query(default="txt"),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """导出单章。"""
    ch = db.get_chapter(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="章节不存在")
    book_id = int(ch.get("book_id") or 0)
    if book_id:
        check_book_owner(db, book_id, user)

    out = None
    try:
        import os
        import tempfile

        from novel_app.exporter import BookExporter
        exporter = BookExporter(db.db)
        ext = {"txt": ".txt", "md": ".md", "docx": ".docx"}.get(fmt, ".txt")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            out = Path(tmp.name)

        if fmt == "docx":
            exporter.export_chapter_docx(chapter_id, out)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fmt == "md":
            exporter.export_chapter_markdown(chapter_id, out)
            media = "text/markdown"
        else:
            exporter.export_chapter_txt(chapter_id, out)
            media = "text/plain"

        data = out.read_bytes()
        safe_name = _sanitize_filename(ch.get("title", "chapter"))
        return Response(content=data, media_type=media, headers={
            "Content-Disposition": _content_disposition(safe_name, ext)
        })
    except Exception as exc:
        logger.exception("导出失败")
        raise HTTPException(status_code=500, detail="导出失败，请稍后重试") from exc
    finally:
        if out is not None:
            with contextlib.suppress(OSError):
                os.unlink(out)
