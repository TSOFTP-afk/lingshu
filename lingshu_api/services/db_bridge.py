"""
数据库桥接层 — 封装 novels.db (SQLite) 的访问接口。

为工作台 API 提供统一的书籍/分卷/章节/人物/世界观等 CRUD 操作，
将底层 novel_app.database.Database 的能力暴露为 REST 友好的格式。
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from starlette.requests import Request

from novel_app.database import ALL_VOLUMES, UNASSIGNED_VOLUMES, Database, cjk_unigram
from novel_app.db.cache import CacheManager
from novel_app.db.character_state_machine import CharacterStateMachineMixin


def _get_db_path() -> Path:
    """获取 novels.db 路径（优先使用环境变量）。"""
    import sys
    configured_data_dir = os.environ.get("SIMPLE_AI_NOVEL_DATA_DIR", "").strip()
    if configured_data_dir:
        return Path(configured_data_dir).expanduser() / "novels.db"
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
        return base_dir / "data" / "novels.db"
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "data" / "novels.db"


class WorkspaceDB:
    """工作台数据库桥接 — 提供 novels.db 的 CRUD 操作。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self._write_lock = threading.Lock()
        self.db = Database(db_path or _get_db_path())
        # Database.__init__ 已设置 busy_timeout/WAL/foreign_keys，
        # 此处仅执行 schema 迁移（幂等）
        self.db.initialize()
        # Redis 缓存层（Redis 不可用时所有方法优雅降级为 no-op）
        self._cache = CacheManager()

    def close(self) -> None:
        self.db.close()

    # ================================================================
    #  书籍
    # ================================================================

    def list_books(self, user_id: int | None = None) -> list[dict[str, Any]]:
        # 尝试缓存命中（仅 user_id 已知时缓存，None 不缓存避免跨用户污染）
        if user_id is not None:
            cached = self._cache.get_book_list(user_id)
            if cached is not None:
                return cached
        rows = self.db.list_books(user_id=user_id)
        result = [dict(r) for r in rows]
        if user_id is not None:
            self._cache.set_book_list(user_id, result)
        return result

    def create_book(self, title: str, user_id: int | None = None) -> dict[str, Any]:
        with self._write_lock:
            book_id = self.db.create_book(title, user_id=user_id)
            book = self.db.get_book(book_id)
            # 失效书籍列表缓存
            self._cache.invalidate_all_book_lists()
        return dict(book) if book else {"id": book_id, "title": title}

    def get_book(self, book_id: int) -> dict[str, Any] | None:
        # 尝试缓存命中
        cached = self._cache.get_book_tree(book_id)
        if cached is not None:
            return cached
        book = self.db.get_book(book_id)
        if not book:
            return None
        result = dict(book)
        result["volumes"] = self._get_volume_tree(book_id)
        # 回填缓存
        self._cache.set_book_tree(book_id, result)
        return result

    def rename_book(self, book_id: int, title: str) -> dict[str, Any] | None:
        with self._write_lock:
            self.db.rename_book(book_id, title)
            # 失效书籍树 + 书籍列表缓存
            self._cache.invalidate_on_book_write(book_id)
        return self.get_book(book_id)

    def check_book_ownership(self, book_id: int, user_id: int) -> bool:
        row = self.db.connection.execute(
            "SELECT user_id FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if row is None:
            return False
        owner = row[0]
        return owner is not None and int(owner) == int(user_id)

    def delete_book(self, book_id: int) -> None:
        with self._write_lock:
            self.db.connection.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            self.db.connection.execute("DELETE FROM volumes WHERE book_id = ?", (book_id,))
            self.db.connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
            self.db.connection.commit()
            # 失效所有相关缓存
            self._cache.invalidate_on_book_delete(book_id)

    def update_book_outline(
        self,
        book_id: int,
        outline_text: str = "",
        outline_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._write_lock:
            self.db.update_book_outline(book_id, outline_text, outline_data)
            self._cache.invalidate_on_book_write(book_id)
        return self.get_book(book_id)

    def update_book_world(self, book_id: int, world_text: str, world_data: dict | None = None) -> dict[str, Any] | None:
        with self._write_lock:
            self.db.update_book_world(book_id, world_text, world_data)
            self._cache.invalidate_on_book_write(book_id)
        return self.get_book(book_id)

    # ================================================================
    #  分卷
    # ================================================================

    def list_volumes(self, book_id: int) -> list[dict[str, Any]]:
        rows = self.db.list_volumes(book_id)
        return [dict(r) for r in rows]

    def get_volume(self, volume_id: int) -> dict[str, Any] | None:
        row = self.db.get_volume(volume_id)
        return dict(row) if row else None

    def create_volume(self, book_id: int, title: str) -> dict[str, Any]:
        with self._write_lock:
            vid = self.db.create_volume(book_id, title)
            volume = self.db.get_volume(vid)
            # 分卷变化影响书籍树结构
            self._cache.invalidate_on_book_write(book_id)
        return dict(volume) if volume else {"id": vid, "book_id": book_id, "title": title, "sort_order": 0}

    def rename_volume(self, volume_id: int, title: str) -> None:
        with self._write_lock:
            # 先查 book_id 用于缓存失效
            volume = self.db.get_volume(volume_id)
            self.db.rename_volume(volume_id, title)
            if volume:
                self._cache.invalidate_on_book_write(int(volume["book_id"]))

    def delete_volume(self, volume_id: int) -> None:
        with self._write_lock:
            # 先查 book_id 用于缓存失效（删除后无法再查）
            volume = self.db.get_volume(volume_id)
            self.db.delete_volume(volume_id)
            if volume:
                self._cache.invalidate_on_book_write(int(volume["book_id"]))

    def reorder_volumes(self, book_id: int, volume_ids: list[int]) -> None:
        with self._write_lock:
            for idx, vid in enumerate(volume_ids):
                self.db.connection.execute(
                    "UPDATE volumes SET sort_order = ? WHERE id = ? AND book_id = ?",
                    (idx + 1, vid, book_id),
                )
            self.db.connection.commit()
            # 排序变化影响书籍树结构
            self._cache.invalidate_on_book_write(book_id)

    # ================================================================
    #  章节
    # ================================================================

    def list_chapters(self, book_id: int, volume_filter: int | str = ALL_VOLUMES) -> list[dict[str, Any]]:
        rows = self.db.list_chapters(book_id, volume_filter)
        return [dict(r) for r in rows]

    def create_chapter(self, book_id: int, title: str, volume_id: int | None = None) -> dict[str, Any]:
        with self._write_lock:
            cid = self.db.create_chapter(book_id, title, volume_id)
            chapter = self.db.get_chapter(cid)
            # 失效章节缓存 + 书籍树（章节列表在 book tree 中）
            self._cache.invalidate_on_chapter_write(book_id, cid)
        return dict(chapter) if chapter else {"id": cid, "book_id": book_id, "title": title}

    def get_chapter(self, chapter_id: int) -> dict[str, Any] | None:
        # 尝试缓存命中
        cached = self._cache.get_chapter(chapter_id)
        if cached is not None:
            return cached
        chapter = self.db.get_chapter(chapter_id)
        if not chapter:
            return None
        result = dict(chapter)
        # 字数统计
        content = result.get("content") or ""
        result["word_count"] = len(content.replace("\r", "").replace("\n", "").replace(" ", ""))
        # 回填缓存
        self._cache.set_chapter(chapter_id, result)
        return result

    def update_chapter(self, chapter_id: int, **kwargs) -> dict[str, Any] | None:
        """更新章节字段：title, content, outline, sort_order 等。"""
        with self._write_lock:
            existing = self.db.get_chapter(chapter_id)
            if not existing:
                return None
            book_id = int(existing["book_id"])
            if "title" in kwargs:
                self.db.rename_chapter(chapter_id, str(kwargs["title"]))
            outline = str(kwargs.get("outline", existing["outline"] or ""))
            content = str(kwargs.get("content", existing["content"] or ""))
            summary_text = str(kwargs.get("summary_text", existing["summary_text"] or ""))
            if any(key in kwargs for key in ("outline", "content", "summary_text")):
                self.db.update_chapter(chapter_id, outline=outline, content=content, summary_text=summary_text)
            # 失效章节缓存 + 书籍树
            self._cache.invalidate_on_chapter_write(book_id, chapter_id)
        return self.get_chapter(chapter_id)

    def search_book(
        self,
        book_id: int,
        query: str,
        *,
        limit: int = 100,
        case_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Search across chapter titles and content.

        优先使用 SQLite FTS5 全文检索（延迟 ≤ 50ms），
        若 FTS5 表不存在（迁移未应用或 SQLite 不支持），则降级为
        Python 层 str.find 逐章扫描。
        """
        needle = str(query or "")
        if not needle:
            return []
        if self._fts5_available():
            return self._search_book_fts5(book_id, needle, limit=limit)
        # FTS5 不可用，降级为旧的逐章扫描
        return self._search_book_legacy(book_id, needle, limit=limit, case_sensitive=case_sensitive)

    def _fts5_available(self) -> bool:
        """检测 chapters_fts 虚拟表是否已创建。"""
        try:
            row = self.db.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chapters_fts' LIMIT 1"
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def _search_book_fts5(
        self,
        book_id: int,
        query: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """使用 FTS5 MATCH 全文检索。

        - 查询串经 cjk_unigram 预处理（与触发器存储时一致），使中文按字符切分
        - 用双引号包裹整个查询作为短语搜索，避免 FTS5 关键字（AND/OR/NOT）干扰
        - 通过 JOIN chapters 限制 book_id 范围并取回上下文
        - 每个匹配返回标题或正文中的命中位置（与旧 API 一致）
        """
        # 查询串经 cjk_unigram 处理（CJK 字符单字分隔，与 FTS5 索引存储方式一致）
        # 然后 FTS5 phrase "白 狐" 会被切分为 ["白","狐"] 两 token 要求相邻
        unigrammed = cjk_unigram(query).strip()
        if not unigrammed:
            return []
        # FTS5 短语语法："query" 表示精确短语匹配
        # 转义查询串中的双引号：把 " 改成 ""（FTS5 双引号转义）
        escaped = unigrammed.replace('"', '""')
        fts_query = f'"{escaped}"'
        results: list[dict[str, Any]] = []
        # 一次查询标题与正文两个字段，分别给出命中字段
        cursor = self.db.connection.execute(
            """
            SELECT
                c.id AS chapter_id,
                c.title AS title,
                c.content AS content,
                v.title AS volume_title,
                bm25(chapters_fts) AS score
            FROM chapters_fts
            JOIN chapters AS c ON c.id = chapters_fts.rowid
            LEFT JOIN volumes AS v ON v.id = c.volume_id
            WHERE chapters_fts MATCH ?
              AND c.book_id = ?
            ORDER BY score
            LIMIT ?
            """,
            (fts_query, book_id, max(1, int(limit))),
        )
        rows = cursor.fetchall()
        for row in rows:
            chapter_id = int(row["chapter_id"])
            title = str(row["title"] or "")
            content = str(row["content"] or "")
            volume_title = str(row["volume_title"] or "")
            # 在命中的字段中查找查询串位置以构造 context（与旧 API 兼容）
            matched_in_title = query.lower() in title.lower()
            matched_in_content = query.lower() in content.lower()
            if matched_in_title:
                self._append_text_matches(
                    results,
                    query,
                    query.lower(),
                    title,
                    chapter_id=chapter_id,
                    book_id=book_id,
                    title=title,
                    volume_title=volume_title,
                    field="title",
                    field_label="标题",
                    limit=limit,
                    case_sensitive=False,
                )
            if len(results) >= limit:
                break
            if matched_in_content:
                self._append_text_matches(
                    results,
                    query,
                    query.lower(),
                    content,
                    chapter_id=chapter_id,
                    book_id=book_id,
                    title=title,
                    volume_title=volume_title,
                    field="content",
                    field_label="正文",
                    limit=limit,
                    case_sensitive=False,
                )
            if len(results) >= limit:
                break
        return results

    def _search_book_legacy(
        self,
        book_id: int,
        query: str,
        *,
        limit: int = 100,
        case_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """旧的逐章 str.find 扫描路径（FTS5 不可用时的降级方案）。"""
        needle_cmp = query if case_sensitive else query.lower()
        results: list[dict[str, Any]] = []
        book = self.get_book(book_id)
        if not book:
            return results

        for volume in book.get("volumes") or []:
            volume_title = str(volume.get("title") or "")
            for chapter_summary in volume.get("chapters") or []:
                if len(results) >= limit:
                    return results
                chapter_id = int(chapter_summary["id"])
                chapter = self.get_chapter(chapter_id)
                if not chapter:
                    continue
                title = str(chapter.get("title") or "")
                self._append_text_matches(
                    results,
                    query,
                    needle_cmp,
                    title,
                    chapter_id=chapter_id,
                    book_id=book_id,
                    title=title,
                    volume_title=volume_title,
                    field="title",
                    field_label="标题",
                    limit=limit,
                    case_sensitive=case_sensitive,
                )
                if len(results) >= limit:
                    return results
                self._append_text_matches(
                    results,
                    query,
                    needle_cmp,
                    str(chapter.get("content") or ""),
                    chapter_id=chapter_id,
                    book_id=book_id,
                    title=title,
                    volume_title=volume_title,
                    field="content",
                    field_label="正文",
                    limit=limit,
                    case_sensitive=case_sensitive,
                )
        return results

    def delete_chapter(self, chapter_id: int) -> None:
        with self._write_lock:
            # 先查 book_id 用于缓存失效（删除后无法再查）
            existing = self.db.get_chapter(chapter_id)
            self.db.delete_chapter(chapter_id)
            if existing:
                self._cache.invalidate_on_chapter_write(int(existing["book_id"]), chapter_id)

    def move_chapter(self, chapter_id: int, target_volume_id: int | None, sort_order: int) -> None:
        with self._write_lock:
            existing = self.db.get_chapter(chapter_id)
            self.db.update_chapter_volume(chapter_id, target_volume_id)
            self.db.connection.execute(
                "UPDATE chapters SET sort_order = ? WHERE id = ?",
                (sort_order, chapter_id),
            )
            self.db.connection.commit()
            if existing:
                # 移动影响书籍树结构（章节在分卷下的归属）+ 章节缓存
                self._cache.invalidate_on_chapter_write(int(existing["book_id"]), chapter_id)

    # ================================================================
    #  人物
    # ================================================================

    def list_characters(self, book_id: int) -> list[dict[str, Any]]:
        rows = self.db.list_characters(book_id)
        return [dict(r) for r in rows]

    def create_character(self, book_id: int, name: str, profile_text: str = "", profile_data: dict | None = None) -> dict[str, Any]:
        with self._write_lock:
            cid = self.db.create_character(book_id, name)
            if profile_text or profile_data:
                if profile_data:
                    self.db.update_character_form(cid, name, "", profile_data)
                else:
                    self.db.update_character(cid, name, "", profile_text)
            char = self.db.get_character(cid)
        return dict(char) if char else {"id": cid, "book_id": book_id, "name": name}

    def get_character(self, character_id: int) -> dict[str, Any] | None:
        char = self.db.get_character(character_id)
        return dict(char) if char else None

    def update_character(self, character_id: int, **kwargs) -> dict[str, Any] | None:
        with self._write_lock:
            existing = self.db.get_character(character_id)
            if not existing:
                return None
            name = kwargs.get("name", str(existing["name"] or ""))
            role = kwargs.get("role", str(existing["role"] or ""))
            image_path = kwargs.get("image_path")
            if "profile_data" in kwargs and isinstance(kwargs.get("profile_data"), dict):
                self.db.update_character_form(character_id, name, role, kwargs["profile_data"], image_path)
            else:
                profile_text = kwargs.get("profile_text", str(existing["profile_text"] or ""))
                self.db.update_character(character_id, name, role, profile_text, image_path)
        return self.get_character(character_id)

    def delete_character(self, character_id: int) -> None:
        with self._write_lock:
            self.db.delete_character(character_id)

    def link_character_to_book(self, character_id: int, book_id: int) -> None:
        with self._write_lock:
            self.db.link_character_to_book(character_id, book_id)

    def unlink_character_from_book(self, character_id: int, book_id: int) -> None:
        with self._write_lock:
            self.db.unlink_character_from_book(character_id, book_id)

    def list_global_characters(self) -> list[dict[str, Any]]:
        rows = self.db.list_global_characters()
        return [dict(r) for r in rows]

    # ================================================================
    #  人物状态机
    # ================================================================

    def get_state_machine(self, character_id: int) -> dict[str, Any] | None:
        sm = self.db.get_state_machine(character_id)
        if sm is None:
            # 自动创建空状态机
            self.db.create_state_machine(character_id, {})
            sm = self.db.get_state_machine(character_id)
        return dict(sm) if sm else None

    def update_state_machine(self, character_id: int, data: dict) -> dict[str, Any] | None:
        with self._write_lock:
            self.db.update_state_machine(character_id, data)
            # 同步兼容视图：从状态机重新生成 profile_text/profile_data_json 写回 characters 表
            self.db._sync_legacy_profile_from_state_machine(character_id)
            sm = self.db.get_state_machine(character_id)
        return dict(sm) if sm else None

    def list_cycles(self, character_id: int, cycle_type: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.list_cycles(character_id, cycle_type)
        return [dict(r) for r in rows]

    def create_cycle(self, character_id: int, cycle_data: dict) -> dict[str, Any]:
        with self._write_lock:
            # create_cycle 涉及多表写入（cycles + state_machines + snapshots），
            # 用 transaction 保证原子性，内部各 mixin 方法的 commit 会被抑制
            with self.db.transaction():
                result = self.db.create_cycle(character_id, cycle_data)
        return result

    def list_character_snapshots(self, character_id: int) -> list[dict[str, Any]]:
        # LibraryMixin.list_snapshots（章节快照）与 CharacterStateMachineMixin.list_snapshots
        # 同名，且 LibraryMixin 在 MRO 中靠前会遮蔽状态机版本，因此显式调用 mixin 方法
        rows = CharacterStateMachineMixin.list_snapshots(self.db, character_id)
        return [dict(r) for r in rows]

    def create_character_snapshot(
        self,
        character_id: int,
        trigger_type: str = "manual",
        trigger_detail: str = "",
        phase_change_summary: str = "",
        micro_cycle_summary: str = "",
    ) -> dict[str, Any] | None:
        with self._write_lock:
            # 同上，显式调用 CharacterStateMachineMixin.create_snapshot 绕过 MRO 遮蔽
            CharacterStateMachineMixin.create_snapshot(
                self.db,
                character_id,
                trigger_type,
                trigger_detail,
                phase_change_summary=phase_change_summary,
                micro_cycle_summary=micro_cycle_summary,
            )
            rows = CharacterStateMachineMixin.list_snapshots(self.db, character_id)
        return dict(rows[-1]) if rows else None

    # ================================================================
    #  星图
    # ================================================================

    def get_star_graph(self, book_id: int) -> dict[str, Any] | None:
        graph = self.db.get_star_graph(book_id)
        return dict(graph) if graph else None

    def update_star_graph(self, book_id: int, nodes_json: str, edges_json: str) -> None:
        with self._write_lock:
            self.db.update_star_graph(book_id, nodes_json, edges_json)

    # ================================================================
    #  快照
    # ================================================================

    def create_snapshot(self, chapter_id: int, label: str, outline: str, content: str) -> int:
        with self._write_lock:
            return self.db.create_snapshot(chapter_id, label, outline, content)

    def list_snapshots(self, chapter_id: int) -> list[dict[str, Any]]:
        rows = self.db.list_snapshots(chapter_id)
        return [dict(r) for r in rows]

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        row = self.db.get_snapshot(snapshot_id)
        return dict(row) if row else None

    def restore_snapshot(self, chapter_id: int, snapshot_id: int) -> bool:
        with self._write_lock:
            snap = self.get_snapshot(snapshot_id)
            if not snap or int(snap.get("chapter_id", 0)) != chapter_id:
                return False
            self.db.update_chapter(chapter_id,
                                   outline=str(snap.get("outline", "")),
                                   content=str(snap.get("content", "")),
                                   summary_text="")
        return True

    # ================================================================
    #  生成快照
    # ================================================================

    def list_generation_snapshots(self, chapter_id: int) -> list[dict[str, Any]]:
        rows = self.db.list_generation_snapshots(chapter_id)
        return [dict(r) for r in rows]

    def create_generation_snapshot(self, chapter_id: int, data: dict) -> dict[str, Any] | None:
        with self._write_lock:
            snapshot_id = self.db.create_generation_snapshot(chapter_id, data)
            row = self.db.get_generation_snapshot(snapshot_id)
        return dict(row) if row else None

    def get_generation_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        row = self.db.get_generation_snapshot(snapshot_id)
        return dict(row) if row else None

    def delete_generation_snapshot(self, snapshot_id: int) -> None:
        with self._write_lock:
            self.db.delete_generation_snapshot(snapshot_id)

    def restore_generation_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        # restore 涉及多表写入，用 transaction 包裹保证原子性，
        # Mixin 方法内不自行 commit
        with self._write_lock:
            with self.db.transaction():
                result = self.db.restore_generation_snapshot(snapshot_id)
        return result

    # ================================================================
    #  内部辅助
    # ================================================================

    def _get_volume_tree(self, book_id: int) -> list[dict[str, Any]]:
        """获取书籍的分卷→章节树结构。"""
        volumes = self.list_volumes(book_id)
        result = []
        for vol in volumes:
            chapters = self.list_chapters(book_id, int(vol["id"]))
            result.append({
                "id": int(vol["id"]),
                "title": vol.get("title", "正文"),
                "sort_order": int(vol.get("sort_order") or 0),
                "chapters": [
                    {
                        "id": int(ch["id"]),
                        "title": ch.get("title", ""),
                        "word_count": int(ch.get("word_count") or 0),
                        "sort_order": int(ch.get("sort_order") or 0),
                    }
                    for ch in chapters
                ],
            })
        unassigned = self.list_chapters(book_id, UNASSIGNED_VOLUMES)
        if unassigned:
            result.append({
                "id": None,
                "book_id": book_id,
                "title": "未分卷",
                "sort_order": 2147483647,
                "is_virtual": True,
                "chapters": [
                    {
                        "id": int(ch["id"]),
                        "title": ch.get("title", ""),
                        "word_count": int(ch.get("word_count") or 0),
                        "sort_order": int(ch.get("sort_order") or 0),
                    }
                    for ch in unassigned
                ],
            })
        return result

    @staticmethod
    def _append_text_matches(
        results: list[dict[str, Any]],
        needle: str,
        needle_cmp: str,
        text: str,
        *,
        chapter_id: int,
        book_id: int,
        title: str,
        volume_title: str,
        field: str,
        field_label: str,
        limit: int,
        case_sensitive: bool,
    ) -> None:
        if not text or not needle_cmp:
            return
        haystack = text if case_sensitive else text.lower()
        start = 0
        while len(results) < limit:
            index = haystack.find(needle_cmp, start)
            if index < 0:
                return
            end = index + len(needle)
            context_start = max(0, index - 80)
            context_end = min(len(text), end + 120)
            context = text[context_start:context_end].replace("\n", " ")
            line = text.count("\n", 0, index) + 1
            previous_break = text.rfind("\n", 0, index)
            column = index + 1 if previous_break < 0 else index - previous_break
            results.append({
                "book_id": book_id,
                "chapter_id": chapter_id,
                "id": chapter_id,
                "title": title,
                "volume_title": volume_title,
                "field": field,
                "fieldLabel": field_label,
                "context": context,
                "start": index,
                "end": end,
                "line": line,
                "column": column,
            })
            start = max(end, index + 1)


class WorkspaceDBProvider:
    """Owns a lazily-created WorkspaceDB instance for one app lifecycle."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._instance: WorkspaceDB | None = None

    def get(self) -> WorkspaceDB:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = WorkspaceDB(self._db_path)
        return self._instance

    def close(self) -> None:
        with self._lock:
            if self._instance is not None:
                self._instance.close()
                self._instance = None

    def reset(self, db_path: Path | None = None) -> None:
        self.close()
        self._db_path = db_path


_default_workspace_provider = WorkspaceDBProvider()


def get_workspace_db(request: Request = None) -> WorkspaceDB:  # type: ignore[assignment]
    """FastAPI dependency for the app-scoped WorkspaceDB provider."""
    provider = None
    if request is not None:
        provider = getattr(getattr(request.app, "state", None), "workspace_db_provider", None)
    if provider is None:
        provider = _default_workspace_provider
    return provider.get()


def close_default_workspace_db() -> None:
    """Close the fallback provider used by scripts and direct unit calls."""
    _default_workspace_provider.close()


def reset_default_workspace_db(db_path: Path | None = None) -> None:
    """Reset the fallback provider after environment changes in tests."""
    _default_workspace_provider.reset(db_path)
