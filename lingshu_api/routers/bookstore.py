"""
书城 + 创作相关路由 — 公开浏览、作者创作、章节发布。
"""
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from lingshu_api.dependencies import get_store, require_author
from novel_app.bookstore import (
    AuthorBookCreatePayload,
    AuthorBookUpdatePayload,
    AuthorChapterUpdatePayload,
    BookstoreStore,
    PublishChapterPayload,
    _bearer_token,
    _public_user,
)

router = APIRouter(tags=["bookstore"])


def _web_base_url() -> str:
    from urllib.parse import urlparse
    url = os.environ.get("BOOKSTORE_WEB_BASE_URL", "http://127.0.0.1:5173")
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "http://127.0.0.1:5173"
    return url


# ---------- 公开浏览 ----------

@router.get("/api/books")
def list_books(
    q: str = Query(default=""),
    category: str = Query(default="all"),
    store: BookstoreStore = Depends(get_store),
):
    return {"items": store.list_books(query=q, category=category)}


@router.get("/api/books/{book_id}")
def get_book(book_id: int, store: BookstoreStore = Depends(get_store)):
    book = store.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return book


@router.get("/api/books/{book_id}/chapters")
def list_chapters(book_id: int, store: BookstoreStore = Depends(get_store)):
    if not store.get_book(book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"items": store.list_chapters(book_id)}


@router.get("/api/chapters/{chapter_id}")
def get_chapter(chapter_id: int, store: BookstoreStore = Depends(get_store)):
    chapter = store.get_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    # 仅返回已发布书籍的章节内容
    book_id = chapter.get("book_id")
    if book_id:
        book = store.get_book(book_id)
        if book and book.get("visibility") != "public":
            raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


# ---------- 发布（桌面端 + Web 端） ----------

@router.post("/api/publish/chapter")
def publish_chapter(
    payload: PublishChapterPayload,
    authorization: str = Header(default=""),
    x_publish_token: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    token = _bearer_token(authorization)
    user = _public_user(store.get_user_by_token(token)) if token else None
    resolved_token = os.environ.get("BOOKSTORE_PUBLISH_TOKEN", "").strip()

    if user:
        if not int(user.get("is_author") or 0):
            raise HTTPException(status_code=403, detail="当前账号不是作者账号")
        payload_data = payload.model_dump()
        payload_data["source_app"] = f"user_{int(user['id'])}"
        payload = PublishChapterPayload(**payload_data)
    else:
        if not resolved_token:
            raise HTTPException(status_code=503, detail="发布令牌未配置，已拒绝写入")
        if not secrets.compare_digest(x_publish_token, resolved_token):
            raise HTTPException(status_code=401, detail="发布令牌无效")

    ids = store.publish_chapter(payload)
    return {
        "ok": True,
        **ids,
        "web_url": f"{_web_base_url()}/books/{ids['book_id']}/chapters/{ids['chapter_id']}",
    }


# ---------- 作者创作 ----------

@router.get("/api/author/books")
def author_books(user: dict = Depends(require_author), store: BookstoreStore = Depends(get_store)):
    if not user.get("is_author"):
        return {"items": []}
    return {"items": store.get_author_books(user["id"])}


@router.post("/api/author/books")
def create_author_book(
    payload: AuthorBookCreatePayload,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    return {"ok": True, "item": store.create_author_book(int(user["id"]), payload)}


@router.patch("/api/author/books/{book_id}")
def update_author_book(
    book_id: int,
    payload: AuthorBookUpdatePayload,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    item = store.update_author_book_summary(int(user["id"]), book_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="作品不存在")
    return {"ok": True, "item": item}


@router.get("/api/author/books/{book_id}/chapters")
def list_author_chapters(
    book_id: int,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    items = store.list_author_chapters(int(user["id"]), book_id)
    if items is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    return {"items": items}


@router.post("/api/author/books/{book_id}/chapters/next")
def create_next_chapter(
    book_id: int,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    item = store.create_next_author_chapter(int(user["id"]), book_id)
    if not item:
        raise HTTPException(status_code=404, detail="作品不存在")
    return {"ok": True, "item": item}


@router.get("/api/author/books/{book_id}/chapters/{chapter_id}")
def get_author_chapter(
    book_id: int,
    chapter_id: int,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    item = store.get_author_chapter(int(user["id"]), book_id, chapter_id)
    if not item:
        raise HTTPException(status_code=404, detail="章节不存在")
    return item


@router.patch("/api/author/books/{book_id}/chapters/{chapter_id}")
def update_author_chapter(
    book_id: int,
    chapter_id: int,
    payload: AuthorChapterUpdatePayload,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    item = store.update_author_chapter(int(user["id"]), book_id, chapter_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True, "item": item}


@router.post("/api/author/books/{book_id}/chapters/{chapter_id}/publish")
def publish_author_chapter(
    book_id: int,
    chapter_id: int,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    item = store.publish_author_chapter(int(user["id"]), book_id, chapter_id)
    if not item:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True, "item": item}


@router.delete("/api/author/books/{book_id}/chapters/{chapter_id}")
def delete_author_chapter(
    book_id: int,
    chapter_id: int,
    user: dict = Depends(require_author),
    store: BookstoreStore = Depends(get_store),
):
    if not store.delete_author_chapter(int(user["id"]), book_id, chapter_id):
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True}
