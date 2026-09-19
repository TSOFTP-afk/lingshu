"""BookstoreStore — 对外门面（阶段 3.3 拆分后）。

数据访问已按域拆到 novel_app/bookstore/repositories/ 仓储层：
- AuthRepository     登录/token/会话
- DeviceRepository   设备信任
- BookRepository     书目/章节/作者作品
- ShelfRepository    书架/范例发书
- AdminRepository    管理后台 CRUD/审计
- StatsRepository    用量记录与统计报表

本文件仅保留：构造（仓储组装）、跨域编排（create_user）以及全部对外公共方法的薄委托，
方法签名与行为与拆分前完全一致。
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .models import (
    DEFAULT_DB_PATH,
    AdminBookUpdatePayload,
    AdminChapterUpdatePayload,
    AdminUserUpdatePayload,
    AuthorBookCreatePayload,
    AuthorBookUpdatePayload,
    AuthorChapterUpdatePayload,
    BookshelfCreatePayload,
    BookshelfProgressPayload,
    PublishChapterPayload,
    _admin_usernames_from_env,
    _connect,
    initialize_database,
)
from .repositories import (
    SAMPLE_NOVEL_USERNAME,
    AdminRepository,
    AuthRepository,
    BookRepository,
    DeviceRepository,
    ShelfRepository,
    StatsRepository,
)
from .security import _hash_login_password

logger = logging.getLogger(__name__)

__all__ = ["BookstoreStore", "SAMPLE_NOVEL_USERNAME"]


class BookstoreStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        initialize_database(self.db_path)
        # 仓储组装：统一持有连接获取方式（_connect(db_path)），与拆分前一致
        self._auth = AuthRepository(self.db_path)
        self._devices = DeviceRepository(self.db_path)
        self._books = BookRepository(self.db_path)
        self._shelves = ShelfRepository(self.db_path, books=self._books)
        self._admin = AdminRepository(self.db_path)
        self._stats = StatsRepository(self.db_path)

    # ------------------------------------------------------------------
    # 用户注册（跨域编排：users 表写入 + 范例小说克隆，保持原实现）
    # ------------------------------------------------------------------
    def create_user(self, username: str, password: str, is_author: int = 1) -> dict[str, Any]:
        h = _hash_login_password(password)
        is_admin = 1 if username in _admin_usernames_from_env() else 0
        with _connect(self.db_path) as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO users (username, password_hash, is_author, is_admin) VALUES (?, ?, ?, ?)",
                    (username, h, is_author, is_admin),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="用户名已存在") from exc
        user_id = int(cursor.lastrowid)
        # 注册钩子：复制范例小说《镜中蝉》到新用户云空间
        # __sample__ 自身不克隆，避免递归
        if username != SAMPLE_NOVEL_USERNAME:
            try:
                clone_result = self.clone_sample_novel_to_user(user_id)
            except Exception as exc:  # 范例分发失败不应阻断注册
                logger.warning("clone_sample_novel_to_user failed for user_id=%s: %s", user_id, exc, exc_info=True)
                clone_result = {"cloned": False, "reason": "exception"}
            if clone_result.get("cloned"):
                logger.info(
                    "sample novel cloned to user_id=%s: %s chapters, %s characters, %s cards",
                    user_id,
                    clone_result.get("chapters", 0),
                    clone_result.get("characters", 0),
                    clone_result.get("analysis_cards", 0),
                )
        result = {"id": user_id, "username": username, "is_author": is_author, "is_admin": is_admin}
        return result

    # ------------------------------------------------------------------
    # 认证 / 会话（AuthRepository）
    # ------------------------------------------------------------------
    def login_user(self, username: str, password: str) -> str | None:
        return self._auth.login_user(username, password)

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        return self._auth.get_user_by_token(token)

    def logout_token(self, token: str) -> bool:
        return self._auth.logout_token(token)

    def bind_reader(self, author_id: int, reader_id: int) -> None:
        return self._auth.bind_reader(author_id, reader_id)

    # ------------------------------------------------------------------
    # 设备信任（DeviceRepository）
    # ------------------------------------------------------------------
    def check_device_trusted(self, user_id: int, fingerprint: str, ip_address: str) -> dict[str, Any]:
        return self._devices.check_device_trusted(user_id, fingerprint, ip_address)

    def trust_device(self, user_id: int, fingerprint: str, device_info: str, ip_address: str) -> None:
        return self._devices.trust_device(user_id, fingerprint, device_info, ip_address)

    def get_trusted_devices(self, user_id: int) -> list[dict[str, Any]]:
        return self._devices.get_trusted_devices(user_id)

    # ------------------------------------------------------------------
    # 用量记录 / 统计报表（StatsRepository）
    # ------------------------------------------------------------------
    def record_user_analysis_run(
        self,
        *,
        user_id: int,
        book_id: int | None = None,
        analysis_mode: str = "",
        input_chars: int = 0,
        status: str = "completed",
        source: str = "",
        run_ref: str = "",
        metadata: dict[str, Any] | None = None,
        error_text: str = "",
    ) -> int:
        return self._stats.record_user_analysis_run(
            user_id=user_id,
            book_id=book_id,
            analysis_mode=analysis_mode,
            input_chars=input_chars,
            status=status,
            source=source,
            run_ref=run_ref,
            metadata=metadata,
            error_text=error_text,
        )

    def record_user_ai_usage(
        self,
        *,
        user_id: int,
        feature: str,
        book_id: int | None = None,
        analysis_run_id: int | None = None,
        model: str = "",
        provider: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        token_source: str = "unknown",
        input_chars: int = 0,
        output_chars: int = 0,
        trace_id: str = "",
        prompt_version: str = "",
        schema_version: str = "",
        latency_ms: int = 0,
        status: str = "completed",
        error_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return self._stats.record_user_ai_usage(
            user_id=user_id,
            feature=feature,
            book_id=book_id,
            analysis_run_id=analysis_run_id,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            token_source=token_source,
            input_chars=input_chars,
            output_chars=output_chars,
            trace_id=trace_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            latency_ms=latency_ms,
            status=status,
            error_text=error_text,
            metadata=metadata,
        )

    def admin_overview(self) -> dict[str, Any]:
        return self._stats.admin_overview()

    def admin_user_stats(self, granularity: str = "monthly", year: int | None = None, month: str | None = None) -> dict[str, Any]:
        return self._stats.admin_user_stats(granularity, year, month)

    # ------------------------------------------------------------------
    # 书目 / 章节 / 作者作品（BookRepository）
    # ------------------------------------------------------------------
    def publish_chapter(self, payload: PublishChapterPayload) -> dict[str, int]:
        return self._books.publish_chapter(payload)

    def list_books(self, query: str = "", category: str = "all") -> list[dict[str, Any]]:
        return self._books.list_books(query, category)

    def get_book(self, book_id: int) -> dict[str, Any] | None:
        return self._books.get_book(book_id)

    def list_chapters(self, book_id: int) -> list[dict[str, Any]]:
        return self._books.list_chapters(book_id)

    def get_chapter(self, chapter_id: int) -> dict[str, Any] | None:
        return self._books.get_chapter(chapter_id)

    def get_author_books(self, user_id: int) -> list[dict[str, Any]]:
        return self._books.get_author_books(user_id)

    def get_author_book(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        return self._books.get_author_book(user_id, book_id)

    def create_author_book(self, user_id: int, payload: AuthorBookCreatePayload) -> dict[str, Any]:
        return self._books.create_author_book(user_id, payload)

    def update_author_book_summary(
        self,
        user_id: int,
        book_id: int,
        payload: AuthorBookUpdatePayload,
    ) -> dict[str, Any] | None:
        return self._books.update_author_book_summary(user_id, book_id, payload)

    def list_author_chapters(self, user_id: int, book_id: int) -> list[dict[str, Any]] | None:
        return self._books.list_author_chapters(user_id, book_id)

    def get_author_chapter(self, user_id: int, book_id: int, chapter_id: int) -> dict[str, Any] | None:
        return self._books.get_author_chapter(user_id, book_id, chapter_id)

    def create_next_author_chapter(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        return self._books.create_next_author_chapter(user_id, book_id)

    def update_author_chapter(
        self,
        user_id: int,
        book_id: int,
        chapter_id: int,
        payload: AuthorChapterUpdatePayload,
    ) -> dict[str, Any] | None:
        return self._books.update_author_chapter(user_id, book_id, chapter_id, payload)

    def publish_author_chapter(self, user_id: int, book_id: int, chapter_id: int) -> dict[str, Any] | None:
        return self._books.publish_author_chapter(user_id, book_id, chapter_id)

    def delete_author_chapter(self, user_id: int, book_id: int, chapter_id: int) -> bool:
        return self._books.delete_author_chapter(user_id, book_id, chapter_id)

    # ------------------------------------------------------------------
    # 书架 / 范例发书（ShelfRepository）
    # ------------------------------------------------------------------
    def ensure_default_bookshelf(self, user_id: int) -> dict[str, Any]:
        return self._shelves.ensure_default_bookshelf(user_id)

    def list_bookshelf_shelves(self, user_id: int) -> list[dict[str, Any]]:
        return self._shelves.list_bookshelf_shelves(user_id)

    def create_bookshelf_shelf(self, user_id: int, payload: BookshelfCreatePayload) -> dict[str, Any]:
        return self._shelves.create_bookshelf_shelf(user_id, payload)

    def list_bookshelf_items(self, user_id: int, shelf_id: int | None = None) -> list[dict[str, Any]] | None:
        return self._shelves.list_bookshelf_items(user_id, shelf_id)

    def get_bookshelf_item(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        return self._shelves.get_bookshelf_item(user_id, book_id)

    def add_bookshelf_item(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        return self._shelves.add_bookshelf_item(user_id, book_id)

    def remove_bookshelf_item(self, user_id: int, book_id: int) -> bool:
        return self._shelves.remove_bookshelf_item(user_id, book_id)

    def update_bookshelf_progress(
        self,
        user_id: int,
        book_id: int,
        payload: BookshelfProgressPayload,
    ) -> dict[str, Any] | None:
        return self._shelves.update_bookshelf_progress(user_id, book_id, payload)

    def clone_sample_novel_to_user(self, new_user_id: int) -> dict[str, Any]:
        return self._shelves.clone_sample_novel_to_user(new_user_id)

    # ------------------------------------------------------------------
    # 管理后台（AdminRepository）
    # ------------------------------------------------------------------
    def sync_admin_users(self, usernames: set[str]) -> None:
        return self._admin.sync_admin_users(usernames)

    def admin_list_users(self, q: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_users(q, page, page_size)

    def admin_get_user(self, user_id: int) -> dict[str, Any] | None:
        return self._admin.admin_get_user(user_id)

    def admin_update_user(self, admin_user_id: int, user_id: int, payload: AdminUserUpdatePayload) -> dict[str, Any] | None:
        return self._admin.admin_update_user(admin_user_id, user_id, payload)

    def admin_disable_user(self, admin_user_id: int, user_id: int) -> bool:
        return self._admin.admin_disable_user(admin_user_id, user_id)

    def admin_restore_user(self, admin_user_id: int, user_id: int) -> bool:
        return self._admin.admin_restore_user(admin_user_id, user_id)

    def admin_list_books(self, q: str = "", include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_books(q, include_deleted, page, page_size)

    def admin_get_book(self, book_id: int) -> dict[str, Any] | None:
        return self._admin.admin_get_book(book_id)

    def admin_update_book(self, admin_user_id: int, book_id: int, payload: AdminBookUpdatePayload) -> dict[str, Any] | None:
        return self._admin.admin_update_book(admin_user_id, book_id, payload)

    def admin_soft_delete_book(self, admin_user_id: int, book_id: int) -> bool:
        return self._admin.admin_soft_delete_book(admin_user_id, book_id)

    def admin_restore_book(self, admin_user_id: int, book_id: int) -> bool:
        return self._admin.admin_restore_book(admin_user_id, book_id)

    def admin_list_chapters(self, book_id: int | None = None, q: str = "", include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_chapters(book_id, q, include_deleted, page, page_size)

    def admin_get_chapter(self, chapter_id: int) -> dict[str, Any] | None:
        return self._admin.admin_get_chapter(chapter_id)

    def admin_update_chapter(self, admin_user_id: int, chapter_id: int, payload: AdminChapterUpdatePayload) -> dict[str, Any] | None:
        return self._admin.admin_update_chapter(admin_user_id, chapter_id, payload)

    def admin_soft_delete_chapter(self, admin_user_id: int, chapter_id: int) -> dict | None:
        return self._admin.admin_soft_delete_chapter(admin_user_id, chapter_id)

    def admin_restore_chapter(self, admin_user_id: int, chapter_id: int) -> bool:
        return self._admin.admin_restore_chapter(admin_user_id, chapter_id)

    def admin_list_bookshelf_shelves(self, include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_bookshelf_shelves(include_deleted, page, page_size)

    def admin_list_bookshelf_items(self, include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_bookshelf_items(include_deleted, page, page_size)

    def admin_soft_delete_shelf(self, admin_user_id: int, shelf_id: int) -> bool:
        return self._admin.admin_soft_delete_shelf(admin_user_id, shelf_id)

    def admin_restore_shelf(self, admin_user_id: int, shelf_id: int) -> bool:
        return self._admin.admin_restore_shelf(admin_user_id, shelf_id)

    def admin_soft_delete_shelf_item(self, admin_user_id: int, item_id: int) -> bool:
        return self._admin.admin_soft_delete_shelf_item(admin_user_id, item_id)

    def admin_restore_shelf_item(self, admin_user_id: int, item_id: int) -> bool:
        return self._admin.admin_restore_shelf_item(admin_user_id, item_id)

    def admin_list_tokens(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_tokens(page, page_size)

    def admin_revoke_token(self, admin_user_id: int, token: str) -> bool:
        return self._admin.admin_revoke_token(admin_user_id, token)

    def admin_list_quotas(
        self,
        q: str = "",
        tier: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        return self._admin.admin_list_quotas(q, tier, page, page_size)

    def admin_list_devices(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_devices(page, page_size)

    def admin_revoke_device(self, admin_user_id: int, device_id: int) -> bool:
        return self._admin.admin_revoke_device(admin_user_id, device_id)

    def admin_list_audit_logs(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self._admin.admin_list_audit_logs(page, page_size)
