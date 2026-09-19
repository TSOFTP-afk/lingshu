"""书架/范例发书仓储 — 从 store.py 按域搬移（SQL 与行为不变）。

承接：书架（bookshelf_shelves/bookshelf_items）与注册发书（clone_sample_novel_to_user）。
连接与事务模式照搬原 store.py：``with _connect(self.db_path) as connection`` + 显式 ``connection.commit()``。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..cloud_store import _bookshelf_row, _bookshelf_shelf_row
from ..models import (
    BookshelfCreatePayload,
    BookshelfProgressPayload,
    _connect,
    _default_bookshelf_name,
    _system_default_bookshelf_names,
)
from .book_repository import BookRepository
from .common import SAMPLE_NOVEL_USERNAME


class ShelfRepository:
    def __init__(self, db_path: Path, books: BookRepository) -> None:
        self.db_path = db_path
        self._books = books

    def ensure_default_bookshelf(self, user_id: int) -> dict[str, Any]:
        with _connect(self.db_path) as connection:
            item = self._ensure_default_bookshelf(connection, int(user_id))
            connection.commit()
            return item

    def _ensure_default_bookshelf(self, connection: sqlite3.Connection, user_id: int) -> dict[str, Any]:
        default_name = _default_bookshelf_name()
        row = connection.execute(
            """
            SELECT id, user_id, name, is_default, created_at, updated_at
            FROM bookshelf_shelves
            WHERE user_id = ? AND is_default = 1 AND deleted_at IS NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        if not row:
            cursor = connection.execute(
                """
                INSERT INTO bookshelf_shelves (user_id, name, is_default)
                VALUES (?, ?, 1)
                """,
                (int(user_id), default_name),
            )
            row = connection.execute(
                """
                SELECT id, user_id, name, is_default, created_at, updated_at
                FROM bookshelf_shelves
                WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        elif row["name"] != default_name and row["name"] in _system_default_bookshelf_names():
            connection.execute(
                """
                UPDATE bookshelf_shelves
                SET name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (default_name, int(row["id"])),
            )
            row = connection.execute(
                """
                SELECT id, user_id, name, is_default, created_at, updated_at
                FROM bookshelf_shelves
                WHERE id = ?
                """,
                (int(row["id"]),),
            ).fetchone()
        connection.execute(
            """
            UPDATE bookshelf_items
            SET shelf_id = ?
            WHERE user_id = ? AND shelf_id IS NULL AND deleted_at IS NULL
            """,
            (int(row["id"]), int(user_id)),
        )
        return _bookshelf_shelf_row(row)

    def list_bookshelf_shelves(self, user_id: int) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            self._ensure_default_bookshelf(connection, int(user_id))
            rows = connection.execute(
                """
                SELECT
                    s.id,
                    s.user_id,
                    s.name,
                    s.is_default,
                    s.created_at,
                    s.updated_at,
                    COUNT(i.id) AS book_count
                FROM bookshelf_shelves AS s
                LEFT JOIN bookshelf_items AS i ON i.shelf_id = s.id AND i.user_id = s.user_id AND i.deleted_at IS NULL
                WHERE s.user_id = ? AND s.deleted_at IS NULL
                GROUP BY s.id
                ORDER BY s.is_default DESC, s.updated_at DESC, s.id DESC
                """,
                (int(user_id),),
            ).fetchall()
            connection.commit()
        return [_bookshelf_shelf_row(row) for row in rows]

    def create_bookshelf_shelf(self, user_id: int, payload: BookshelfCreatePayload) -> dict[str, Any]:
        name = payload.name.strip()
        with _connect(self.db_path) as connection:
            self._ensure_default_bookshelf(connection, int(user_id))
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO bookshelf_shelves (user_id, name, is_default)
                    VALUES (?, ?, 0)
                    """,
                    (int(user_id), name),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="书架名称已存在") from exc
            row = connection.execute(
                """
                SELECT id, user_id, name, is_default, created_at, updated_at, 0 AS book_count
                FROM bookshelf_shelves
                WHERE id = ? AND deleted_at IS NULL
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        return _bookshelf_shelf_row(row)

    def _bookshelf_shelf_exists(self, connection: sqlite3.Connection, user_id: int, shelf_id: int) -> bool:
        row = connection.execute(
            "SELECT id FROM bookshelf_shelves WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (int(shelf_id), int(user_id)),
        ).fetchone()
        return row is not None

    def list_bookshelf_items(self, user_id: int, shelf_id: int | None = None) -> list[dict[str, Any]] | None:
        with _connect(self.db_path) as connection:
            default_shelf = self._ensure_default_bookshelf(connection, int(user_id))
            target_shelf_id = int(shelf_id or default_shelf["id"])
            if not self._bookshelf_shelf_exists(connection, int(user_id), target_shelf_id):
                return None
            rows = connection.execute(
                """
                SELECT
                    b.id,
                    b.title,
                    b.summary,
                    b.category,
                    b.sub_tags,
                    b.cover_url,
                    b.updated_at,
                    bi.shelf_id,
                    bi.added_at,
                    bi.updated_at AS shelf_updated_at,
                    bi.last_chapter_id,
                    last.title AS last_chapter_title,
                    last.volume_title AS last_chapter_volume_title,
                    last.sort_order AS last_chapter_sort_order,
                    (
                        SELECT COUNT(*)
                        FROM chapters AS count_chapters
                        WHERE count_chapters.book_id = b.id
                          AND count_chapters.status = 'published'
                          AND count_chapters.deleted_at IS NULL
                    ) AS chapter_count,
                    (
                        SELECT COALESCE(SUM(LENGTH(word_chapters.content)), 0)
                        FROM chapters AS word_chapters
                        WHERE word_chapters.book_id = b.id
                          AND word_chapters.status = 'published'
                          AND word_chapters.deleted_at IS NULL
                    ) AS word_count,
                    (
                        SELECT id
                        FROM chapters AS first_chapter
                        WHERE first_chapter.book_id = b.id
                          AND first_chapter.status = 'published'
                          AND first_chapter.deleted_at IS NULL
                        ORDER BY first_chapter.sort_order ASC, first_chapter.id ASC
                        LIMIT 1
                    ) AS first_chapter_id,
                    (
                        SELECT title
                        FROM chapters AS first_chapter
                        WHERE first_chapter.book_id = b.id
                          AND first_chapter.status = 'published'
                          AND first_chapter.deleted_at IS NULL
                        ORDER BY first_chapter.sort_order ASC, first_chapter.id ASC
                        LIMIT 1
                    ) AS first_chapter_title,
                    (
                        SELECT id
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_id,
                    (
                        SELECT title
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_title,
                    (
                        SELECT volume_title
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_volume_title,
                    (
                        SELECT updated_at
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_updated_at,
                    (
                        SELECT COUNT(*)
                        FROM chapters AS progress_chapters
                        WHERE progress_chapters.book_id = b.id
                          AND progress_chapters.status = 'published'
                          AND progress_chapters.deleted_at IS NULL
                          AND last.id IS NOT NULL
                          AND (
                            progress_chapters.sort_order < last.sort_order
                            OR (
                                progress_chapters.sort_order = last.sort_order
                                AND progress_chapters.id <= last.id
                            )
                          )
                    ) AS last_chapter_index
                FROM bookshelf_items AS bi
                JOIN books AS b ON b.id = bi.book_id AND b.deleted_at IS NULL
                LEFT JOIN chapters AS last
                  ON last.id = bi.last_chapter_id
                 AND last.book_id = b.id
                 AND last.status = 'published'
                 AND last.deleted_at IS NULL
                WHERE bi.user_id = ? AND bi.shelf_id = ? AND bi.deleted_at IS NULL
                ORDER BY bi.updated_at DESC, bi.id DESC
                """,
                (int(user_id), target_shelf_id),
            ).fetchall()
            connection.commit()
        return [_bookshelf_row(row) for row in rows]

    def get_bookshelf_item(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        items = self.list_bookshelf_items(user_id)
        if items is None:
            return None
        for item in items:
            if int(item["id"]) == int(book_id):
                return item
        return None

    def add_bookshelf_item(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        if not self._books.get_book(book_id):
            return None
        with _connect(self.db_path) as connection:
            shelf = self._ensure_default_bookshelf(connection, int(user_id))
            connection.execute(
                """
                INSERT INTO bookshelf_items (user_id, shelf_id, book_id)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, book_id) DO UPDATE SET
                    shelf_id = COALESCE(bookshelf_items.shelf_id, excluded.shelf_id),
                    deleted_at = NULL,
                    deleted_by = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (int(user_id), int(shelf["id"]), int(book_id)),
            )
            connection.commit()
        return self.get_bookshelf_item(user_id, book_id)

    def remove_bookshelf_item(self, user_id: int, book_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE bookshelf_items
                SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                    deleted_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND book_id = ? AND deleted_at IS NULL
                """,
                (int(user_id), int(user_id), int(book_id)),
            )
            connection.commit()
        return cursor.rowcount > 0

    def update_bookshelf_progress(
        self,
        user_id: int,
        book_id: int,
        payload: BookshelfProgressPayload,
    ) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            shelf = connection.execute(
                "SELECT id FROM bookshelf_items WHERE user_id = ? AND book_id = ? AND deleted_at IS NULL",
                (int(user_id), int(book_id)),
            ).fetchone()
            if not shelf:
                return None
            chapter = connection.execute(
                """
                SELECT id
                FROM chapters
                WHERE id = ?
                  AND book_id = ?
                  AND status = 'published'
                  AND deleted_at IS NULL
                """,
                (int(payload.chapter_id), int(book_id)),
            ).fetchone()
            if not chapter:
                raise HTTPException(status_code=422, detail="阅读进度章节不属于该书或尚未发布")
            connection.execute(
                """
                UPDATE bookshelf_items
                SET last_chapter_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND book_id = ? AND deleted_at IS NULL
                """,
                (int(payload.chapter_id), int(user_id), int(book_id)),
            )
            connection.commit()
        return self.get_bookshelf_item(user_id, book_id)

    def clone_sample_novel_to_user(self, new_user_id: int) -> dict[str, Any]:
        """将 __sample__ 用户的范例小说《镜中蝉》复制到新用户云空间。

        复制范围（按依赖顺序）：
        - cloud_books / cloud_chapters / cloud_characters
        - cloud_character_state_machines / cloud_character_cycles / cloud_character_snapshots（状态机三表）
        - cloud_character_relationships / cloud_world_entries / cloud_chapter_events
        - cloud_analysis_runs / cloud_analysis_cards

        所有 local_*_id 字段置空（新用户无本地映射）。
        整个操作在单个 with _connect 事务内完成，失败则整体回滚。
        若 __sample__ 用户或其范例书不存在，返回 cloned=False 优雅降级。
        """
        with _connect(self.db_path) as connection:
            sample_row = connection.execute(
                "SELECT id FROM users WHERE username = ?", (SAMPLE_NOVEL_USERNAME,)
            ).fetchone()
            if not sample_row:
                return {"cloned": False, "reason": "sample_user_not_found"}
            sample_user_id = int(sample_row["id"])

            sample_books = connection.execute(
                "SELECT * FROM cloud_books WHERE user_id = ? AND source_type = 'sample' ORDER BY id",
                (sample_user_id,),
            ).fetchall()
            if not sample_books:
                return {"cloned": False, "reason": "sample_book_not_found"}

            stats = {
                "cloned": True, "user_id": new_user_id,
                "books": 0, "chapters": 0, "characters": 0,
                "state_machines": 0, "cycles": 0, "snapshots": 0,
                "relationships": 0, "world_entries": 0, "chapter_events": 0,
                "analysis_runs": 0, "analysis_cards": 0,
            }

            for book_row in sample_books:
                old_book_id = int(book_row["id"])
                # 1. cloud_books
                cursor = connection.execute(
                    """
                    INSERT INTO cloud_books (
                        user_id, title, outline_text, outline_data_json, world_text, world_data_json,
                        cover_image_path, source_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_user_id,
                        book_row["title"], book_row["outline_text"], book_row["outline_data_json"],
                        book_row["world_text"], book_row["world_data_json"], book_row["cover_image_path"],
                        "sample_clone", book_row["created_at"], book_row["updated_at"],
                    ),
                )
                new_book_id = int(cursor.lastrowid)
                stats["books"] += 1

                # 1b. books 本地表写入（前端 /api/author/books 只查 books 表，
                #     过滤 source_app=f"user_{user_id}"，必须同步写一份才能在前端"我的作品"看到）
                local_book_cursor = connection.execute(
                    """
                    INSERT INTO books (source_app, source_book_id, title, summary, category, cover_url, is_test)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        f"user_{new_user_id}",
                        str(new_book_id),
                        book_row["title"],
                        book_row["outline_text"] or "",
                        "范例",
                        book_row["cover_image_path"] or "",
                    ),
                )
                local_book_id = int(local_book_cursor.lastrowid)
                stats["books_local"] = stats.get("books_local", 0) + 1

                # 2. cloud_chapters + chapters 本地表（建立 old_chapter_id -> new_chapter_id 映射）
                chapter_id_map: dict[int, int] = {}
                for ch_row in connection.execute(
                    "SELECT * FROM cloud_chapters WHERE cloud_book_id = ? ORDER BY sort_order, id",
                    (old_book_id,),
                ).fetchall():
                    c = connection.execute(
                        """
                        INSERT INTO cloud_chapters (
                            cloud_book_id, cloud_volume_id, title, outline, content, summary_text,
                            chapter_type, sort_order, ai_probability, ai_probability_level, created_at, updated_at
                        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, ch_row["title"], ch_row["outline"], ch_row["content"],
                            ch_row["summary_text"], ch_row["chapter_type"], ch_row["sort_order"],
                            ch_row["ai_probability"], ch_row["ai_probability_level"],
                            ch_row["created_at"], ch_row["updated_at"],
                        ),
                    )
                    chapter_id_map[int(ch_row["id"])] = int(c.lastrowid)
                    stats["chapters"] += 1
                    # 同步写 chapters 本地表（前端 /api/author/books 统计 chapter_count/word_count 依赖）
                    connection.execute(
                        """
                        INSERT INTO chapters (
                            book_id, source_chapter_id, volume_title, title, outline, summary_text,
                            content, sort_order, ai_probability, ai_probability_level
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            local_book_id, str(c.lastrowid), "正文",
                            ch_row["title"], ch_row["outline"], ch_row["summary_text"],
                            ch_row["content"], ch_row["sort_order"],
                            ch_row["ai_probability"], ch_row["ai_probability_level"],
                        ),
                    )
                    stats["chapters_local"] = stats.get("chapters_local", 0) + 1

                # 3. cloud_characters + 状态机三表（建立 old_char_id -> new_char_id 映射）
                char_id_map: dict[int, int] = {}
                for char_row in connection.execute(
                    "SELECT * FROM cloud_characters WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    c = connection.execute(
                        """
                        INSERT INTO cloud_characters (
                            cloud_book_id, name, role, profile_text, profile_data_json, image_path,
                            graph_x, graph_y, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, char_row["name"], char_row["role"], char_row["profile_text"],
                            char_row["profile_data_json"], char_row["image_path"], char_row["graph_x"],
                            char_row["graph_y"], char_row["created_at"], char_row["updated_at"],
                        ),
                    )
                    old_cid = int(char_row["id"])
                    new_cid = int(c.lastrowid)
                    char_id_map[old_cid] = new_cid
                    stats["characters"] += 1

                    # 4. cloud_character_state_machines
                    sm_row = connection.execute(
                        "SELECT * FROM cloud_character_state_machines WHERE cloud_character_id = ?",
                        (old_cid,),
                    ).fetchone()
                    if sm_row:
                        connection.execute(
                            """
                            INSERT INTO cloud_character_state_machines (
                                cloud_character_id,
                                desire_text, desire_origin, desire_anchor, desire_extreme, desire_fear_mirror,
                                mbti_type, mbti_i_e, mbti_n_s, mbti_t_f, mbti_j_p,
                                mbti_strategy, mbti_advantage, mbti_blindspot,
                                fate_type, fate_content, fate_trigger, fate_target, fate_limit,
                                belief_core, belief_origin, belief_alignment, belief_sacrifice, belief_taboo,
                                current_desire_state, current_mbti_state, current_fate_state, current_belief_state,
                                current_friction, current_dilemma, total_change_score, last_update_source,
                                created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_cid,
                                sm_row["desire_text"], sm_row["desire_origin"], sm_row["desire_anchor"],
                                sm_row["desire_extreme"], sm_row["desire_fear_mirror"],
                                sm_row["mbti_type"], sm_row["mbti_i_e"], sm_row["mbti_n_s"], sm_row["mbti_t_f"],
                                sm_row["mbti_j_p"], sm_row["mbti_strategy"], sm_row["mbti_advantage"], sm_row["mbti_blindspot"],
                                sm_row["fate_type"], sm_row["fate_content"], sm_row["fate_trigger"], sm_row["fate_target"],
                                sm_row["fate_limit"],
                                sm_row["belief_core"], sm_row["belief_origin"], sm_row["belief_alignment"],
                                sm_row["belief_sacrifice"], sm_row["belief_taboo"],
                                sm_row["current_desire_state"], sm_row["current_mbti_state"], sm_row["current_fate_state"],
                                sm_row["current_belief_state"], sm_row["current_friction"], sm_row["current_dilemma"],
                                sm_row["total_change_score"], sm_row["last_update_source"],
                                sm_row["created_at"], sm_row["updated_at"],
                            ),
                        )
                        stats["state_machines"] += 1

                    # 5. cloud_character_cycles
                    for cycle_row in connection.execute(
                        "SELECT * FROM cloud_character_cycles WHERE cloud_character_id = ? ORDER BY sort_order, id",
                        (old_cid,),
                    ).fetchall():
                        connection.execute(
                            """
                            INSERT INTO cloud_character_cycles (
                                cloud_character_id, cycle_type, cycle_code, triggered_desire,
                                belief_filtered_strategy, action_taken, world_feedback, feedback_intensity,
                                mbti_change, star_state, fate_state, internal_friction,
                                change_score, cumulative_score, batch_span, batch_micro_count,
                                batch_summary, sort_order, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_cid, cycle_row["cycle_type"], cycle_row["cycle_code"],
                                cycle_row["triggered_desire"], cycle_row["belief_filtered_strategy"],
                                cycle_row["action_taken"], cycle_row["world_feedback"], cycle_row["feedback_intensity"],
                                cycle_row["mbti_change"], cycle_row["star_state"], cycle_row["fate_state"],
                                cycle_row["internal_friction"], cycle_row["change_score"], cycle_row["cumulative_score"],
                                cycle_row["batch_span"], cycle_row["batch_micro_count"], cycle_row["batch_summary"],
                                cycle_row["sort_order"], cycle_row["created_at"],
                            ),
                        )
                        stats["cycles"] += 1

                    # 6. cloud_character_snapshots
                    for snap_row in connection.execute(
                        "SELECT * FROM cloud_character_snapshots WHERE cloud_character_id = ? ORDER BY snapshot_no, id",
                        (old_cid,),
                    ).fetchall():
                        connection.execute(
                            """
                            INSERT INTO cloud_character_snapshots (
                                cloud_character_id, snapshot_no, trigger_type, trigger_detail, related_cycle_id,
                                desire_state, mbti_state, fate_state, belief_state, friction_level, phase_dilemma,
                                phase_change_summary, micro_cycle_summary, total_score_at_snapshot, created_at
                            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_cid, snap_row["snapshot_no"], snap_row["trigger_type"], snap_row["trigger_detail"],
                                snap_row["desire_state"], snap_row["mbti_state"], snap_row["fate_state"],
                                snap_row["belief_state"], snap_row["friction_level"], snap_row["phase_dilemma"],
                                snap_row["phase_change_summary"], snap_row["micro_cycle_summary"],
                                snap_row["total_score_at_snapshot"], snap_row["created_at"],
                            ),
                        )
                        stats["snapshots"] += 1

                # 7. cloud_character_relationships
                for rel_row in connection.execute(
                    "SELECT * FROM cloud_character_relationships WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    new_src = char_id_map.get(int(rel_row["source_character_id"]))
                    new_tgt = char_id_map.get(int(rel_row["target_character_id"]))
                    if not new_src or not new_tgt:
                        continue
                    connection.execute(
                        """
                        INSERT INTO cloud_character_relationships (
                            cloud_book_id, source_character_id, target_character_id,
                            relationship_type, description, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, new_src, new_tgt,
                            rel_row["relationship_type"], rel_row["description"],
                            rel_row["created_at"], rel_row["updated_at"],
                        ),
                    )
                    stats["relationships"] += 1

                # 8. cloud_world_entries
                for we_row in connection.execute(
                    "SELECT * FROM cloud_world_entries WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    connection.execute(
                        """
                        INSERT INTO cloud_world_entries (
                            cloud_book_id, name, category, content_text, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, we_row["name"], we_row["category"], we_row["content_text"],
                            we_row["created_at"], we_row["updated_at"],
                        ),
                    )
                    stats["world_entries"] += 1

                # 9. cloud_chapter_events
                for ev_row in connection.execute(
                    "SELECT * FROM cloud_chapter_events WHERE cloud_book_id = ? ORDER BY sort_order, id",
                    (old_book_id,),
                ).fetchall():
                    new_ch_id = chapter_id_map.get(int(ev_row["cloud_chapter_id"]))
                    if not new_ch_id:
                        continue
                    connection.execute(
                        """
                        INSERT INTO cloud_chapter_events (
                            cloud_book_id, cloud_chapter_id, label, description, sort_order, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, new_ch_id, ev_row["label"], ev_row["description"],
                            ev_row["sort_order"], ev_row["created_at"], ev_row["updated_at"],
                        ),
                    )
                    stats["chapter_events"] += 1

                # 10. cloud_analysis_runs（建立 old_run_id -> new_run_id 映射）
                run_id_map: dict[int, int] = {}
                for run_row in connection.execute(
                    "SELECT * FROM cloud_analysis_runs WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    c = connection.execute(
                        """
                        INSERT INTO cloud_analysis_runs (
                            cloud_book_id, scope_type, status, pipeline_version, input_hash,
                            summary, error_text, meta_json, completed_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, run_row["scope_type"], run_row["status"], run_row["pipeline_version"],
                            run_row["input_hash"], run_row["summary"], run_row["error_text"], run_row["meta_json"],
                            run_row["completed_at"], run_row["created_at"], run_row["updated_at"],
                        ),
                    )
                    run_id_map[int(run_row["id"])] = int(c.lastrowid)
                    stats["analysis_runs"] += 1

                # 11. cloud_analysis_cards
                for card_row in connection.execute(
                    "SELECT * FROM cloud_analysis_cards WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    new_run_id = run_id_map.get(int(card_row["cloud_run_id"]))
                    if not new_run_id:
                        continue
                    connection.execute(
                        """
                        INSERT INTO cloud_analysis_cards (
                            cloud_book_id, cloud_run_id, card_uid, card_type, entity_uid, card_version,
                            ars_score, status, payload_json, diff_json, applied_table, applied_at,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, new_run_id, card_row["card_uid"], card_row["card_type"],
                            card_row["entity_uid"], card_row["card_version"], card_row["ars_score"],
                            card_row["status"], card_row["payload_json"], card_row["diff_json"],
                            card_row["applied_table"], card_row["applied_at"],
                            card_row["created_at"], card_row["updated_at"],
                        ),
                    )
                    stats["analysis_cards"] += 1

        # novels.db 的写入由 auth.py register 端点调用 _seed_sample_to_workspace 完成
        # （使用 WorkspaceDB 共享 Database 连接，避免 sqlite3 锁冲突）

        return stats
