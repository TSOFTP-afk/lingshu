"""社区卡片帖子的数据访问层。

提供 ``community_card_posts`` 表的 CRUD 操作，遵循项目既有的 DB 访问约定：
- 通过 ``Database`` 实例访问连接（``self.database.connection``）；
- 多表写操作使用 ``Database.transaction()`` 上下文管理器；
- 所有 SQL 均使用参数化查询（``?`` 占位符）；
- JSON 解析失败时回退为空字典，不抛异常；
- ``users`` 表可能不存在于当前数据库（本地 DB 中无此表），关联失败时
  ``poster_name`` 回退为空字符串。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from novel_app.database import Database


class DuplicatePostError(Exception):
    """同一用户对同一来源卡片重复发布时抛出。"""


class CommunityStoreError(Exception):
    """社区卡片存储层的通用错误。"""


class CommunityStore:
    """``community_card_posts`` 表的数据访问层。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    # ──────────────────── 内部工具 ────────────────────

    @staticmethod
    def _safe_loads(text: str | None) -> dict[str, Any]:
        """安全解析 JSON 字符串，失败或非对象时返回空字典。"""
        try:
            data = json.loads(text or "")
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    # ──────────────────── 查询接口 ────────────────────

    def list_posts(
        self,
        card_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """列出社区卡片帖子，按创建时间倒序分页返回。

        ``card_type`` 为 ``None`` 时不限类型；为 ``'world'`` 或 ``'character'`` 时按类型过滤。
        返回 ``{"items": [...], "total": N, "page": page, "page_size": page_size}``。
        """
        page = max(1, int(page))
        page_size = max(1, int(page_size))
        offset = (page - 1) * page_size

        where_clause = ""
        params: list[Any] = []
        if card_type:
            where_clause = "WHERE p.card_type = ?"
            params.append(str(card_type))

        count_sql = f"SELECT COUNT(*) FROM community_card_posts AS p {where_clause}"
        conn = self.database.connection
        total_row = conn.execute(count_sql, params).fetchone()
        total = int(total_row[0]) if total_row else 0

        join_sql = "LEFT JOIN users AS u ON u.id = p.poster_user_id"
        select_sql = (
            "SELECT p.id, p.card_type, p.card_name, p.intro, p.poster_user_id, "
            "p.source_book_title, p.view_count, p.created_at, "
            "COALESCE(u.username, '') AS poster_name "
            f"FROM community_card_posts AS p {join_sql} {where_clause} "
            "ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?"
        )
        try:
            rows = conn.execute(select_sql, params + [page_size, offset]).fetchall()
        except sqlite3.Error:
            # users 表不存在或 JOIN 失败，回退为不带 JOIN 的查询
            fallback_sql = (
                "SELECT p.id, p.card_type, p.card_name, p.intro, p.poster_user_id, "
                "p.source_book_title, p.view_count, p.created_at, "
                "'' AS poster_name "
                f"FROM community_card_posts AS p {where_clause} "
                "ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?"
            )
            rows = conn.execute(fallback_sql, params + [page_size, offset]).fetchall()

        items = [dict(row) for row in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_post(self, post_id: int) -> dict[str, Any] | None:
        """获取单个帖子的完整记录（含解析后的 payload），并原子自增浏览数。

        帖子不存在时返回 ``None``。
        """
        post_id = int(post_id)
        conn = self.database.connection

        join_sql = "LEFT JOIN users AS u ON u.id = p.poster_user_id"
        select_sql = (
            "SELECT p.*, COALESCE(u.username, '') AS poster_name "
            f"FROM community_card_posts AS p {join_sql} WHERE p.id = ?"
        )
        try:
            row = conn.execute(select_sql, (post_id,)).fetchone()
        except sqlite3.Error:
            fallback_sql = (
                "SELECT p.*, '' AS poster_name "
                "FROM community_card_posts AS p WHERE p.id = ?"
            )
            row = conn.execute(fallback_sql, (post_id,)).fetchone()

        if row is None:
            return None

        # 原子自增浏览数
        conn.execute(
            "UPDATE community_card_posts SET view_count = view_count + 1 WHERE id = ?",
            (post_id,),
        )
        conn.commit()

        item = dict(row)
        item["view_count"] = int(item.get("view_count") or 0) + 1
        item["payload"] = self._safe_loads(item.get("payload_json"))
        return item

    # ──────────────────── 写入接口 ────────────────────

    def create_post(
        self,
        poster_user_id: int,
        card_type: str,
        source_book_id: int,
        source_card_id: int,
        intro: str,
    ) -> int:
        """从来源书籍/角色读取快照并写入社区帖子，返回新帖子 id。

        - ``card_type='world'``：从 ``books`` 表读取世界观，``source_card_id`` 应为 0；
        - ``card_type='character'``：从 ``characters`` 表读取角色，并校验书籍归属。

        来源不存在或不属于当前用户时抛 ``ValueError``；
        命中唯一约束（重复发布）时抛 ``DuplicatePostError``。
        """
        poster_user_id = int(poster_user_id)
        source_book_id = int(source_book_id)
        source_card_id = int(source_card_id)
        card_type = str(card_type or "")
        intro = str(intro or "")

        if card_type not in ("world", "character"):
            raise ValueError(f"不支持的卡片类型: {card_type!r}（仅支持 'world' 或 'character'）")

        conn = self.database.connection

        # 多表读写：读取来源数据 + 写入 community_card_posts，整体包裹在事务中
        with self.database.transaction():
            if card_type == "world":
                if source_card_id != 0:
                    raise ValueError("世界观卡片的 source_card_id 必须为 0")
                book = conn.execute(
                    "SELECT title, world_text, world_data_json "
                    "FROM books WHERE id = ? AND user_id = ?",
                    (source_book_id, poster_user_id),
                ).fetchone()
                if book is None:
                    raise ValueError("来源书籍不存在或不属于当前用户")
                book_title = str(book["title"] or "")
                world_data = self._safe_loads(book["world_data_json"])
                card_name = f"{book_title} - 世界观"
                payload: dict[str, Any] = {
                    "world_text": str(book["world_text"] or ""),
                    "world_data": world_data,
                    "book_title": book_title,
                }
                source_book_title = book_title
            else:  # character
                character = conn.execute(
                    "SELECT name, role, profile_text, profile_data_json, image_path, book_id "
                    "FROM characters WHERE id = ? AND book_id = ?",
                    (source_card_id, source_book_id),
                ).fetchone()
                if character is None:
                    raise ValueError("来源角色不存在或不属于指定书籍")
                book = conn.execute(
                    "SELECT title, user_id FROM books WHERE id = ?",
                    (source_book_id,),
                ).fetchone()
                if book is None or int(book["user_id"] or 0) != poster_user_id:
                    raise ValueError("来源书籍不存在或不属于当前用户")
                book_title = str(book["title"] or "")
                profile_data = self._safe_loads(character["profile_data_json"])
                card_name = str(character["name"] or "")
                payload = {
                    "name": str(character["name"] or ""),
                    "role": str(character["role"] or ""),
                    "profile_text": str(character["profile_text"] or ""),
                    "profile_data": profile_data,
                    "image_path": str(character["image_path"] or ""),
                }
                source_book_title = book_title

            payload_json = json.dumps(payload, ensure_ascii=False, default=str)

            try:
                cursor = conn.execute(
                    """
                    INSERT INTO community_card_posts (
                        poster_user_id, card_type, card_name, intro, payload_json,
                        source_book_id, source_book_title, source_card_id,
                        view_count, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        poster_user_id,
                        card_type,
                        card_name,
                        intro,
                        payload_json,
                        source_book_id,
                        source_book_title,
                        source_card_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # UNIQUE(poster_user_id, source_book_id, source_card_id, card_type) 冲突
                raise DuplicatePostError("该卡片已发布到社区，请勿重复发布") from exc

            return int(cursor.lastrowid)

    def delete_post(self, post_id: int, poster_user_id: int) -> bool:
        """删除指定帖子，仅允许发布者本人删除。

        帖子不存在时返回 ``False``；非本人发布时抛 ``PermissionError``。
        """
        post_id = int(post_id)
        poster_user_id = int(poster_user_id)
        conn = self.database.connection

        post = conn.execute(
            "SELECT poster_user_id FROM community_card_posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        if post is None:
            return False
        if int(post["poster_user_id"] or 0) != poster_user_id:
            raise PermissionError("无权删除他人发布的帖子")

        cursor = conn.execute(
            "DELETE FROM community_card_posts WHERE id = ? AND poster_user_id = ?",
            (post_id, poster_user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


__all__ = [
    "CommunityStore",
    "DuplicatePostError",
    "CommunityStoreError",
]
