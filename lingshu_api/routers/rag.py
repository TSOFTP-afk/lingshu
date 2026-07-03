"""
RAG 检索 API — 对应 novel_app/rag/
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from lingshu_api.dependencies import check_book_owner, require_login
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db

router = APIRouter(prefix="/api/workspace", tags=["rag"])
logger = logging.getLogger(__name__)


@router.get("/books/{book_id}/rag/search")
def rag_search(
    book_id: int,
    q: str = Query(default="", description="搜索关键词"),
    doc_types: str = Query(default="", description="文档类型，逗号分隔"),
    top_k: int = Query(default=5, ge=1, le=20),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """RAG 语义搜索 — 在作品设计文档中检索相关内容。"""
    if not q.strip():
        return {"items": [], "context": ""}
    check_book_owner(db, book_id, user)

    try:

        from novel_app.rag.retriever import ChapterRetriever

        retriever = ChapterRetriever(
            storage_dir=str(db.db.data_dir / "rag_index"),
        )
        # 使用 FallbackEmbedder 做向量搜索
        results = retriever.search(
            book_id=book_id,
            query=q,
            top_k=top_k,
            doc_types=[t.strip() for t in doc_types.split(",") if t.strip()] if doc_types else None,
        )
        items = [{"id": r.get("chapter_id"), "score": r.get("score", 0), "title": r.get("title", ""), "content": r.get("content", "")} for r in results]
        context = retriever.build_context_from_results(results, max_chars=3000)
        return {"items": items, "context": context}
    except Exception:
        logger.exception("RAG 检索失败")
        return {"items": [], "context": "", "error": "检索失败，请稍后重试"}


@router.post("/books/{book_id}/rag/reindex")
def rag_reindex(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """触发全书 RAG 索引重建。"""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="作品不存在")
    check_book_owner(db, book_id, user)

    try:
        from novel_app.rag.retriever import ChapterRetriever
        retriever = ChapterRetriever(storage_dir=str(db.db.data_dir / "rag_index"))

        indexed = 0
        for vol in (book.get("volumes") or []):
            for ch in (vol.get("chapters") or []):
                detail = db.get_chapter(ch["id"])
                if not detail:
                    continue
                retriever.index_chapter(
                    book_id=book_id,
                    chapter_id=ch["id"],
                    title=detail.get("title", ""),
                    summary=detail.get("summary_text", ""),
                    outline=detail.get("outline", ""),
                    content_snippet=(detail.get("content") or "")[:2000],
                )
                indexed += 1

        return {"ok": True, "indexed": indexed}
    except Exception as exc:
        logger.exception("索引构建失败")
        raise HTTPException(status_code=500, detail="索引构建失败，请稍后重试") from exc
