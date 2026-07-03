from __future__ import annotations

from novel_app.db.common import *


class LibraryMixin:
    def _next_volume_sort_order(self, book_id: int) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM volumes WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        return int(row["next_order"]) if row else 1

    def _next_chapter_sort_order(self, book_id: int, volume_id: int | None) -> int:
        clause, params = self._build_volume_clause(volume_id)
        row = self.connection.execute(
            f"""
            SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
            FROM chapters
            WHERE book_id = ? AND {clause}
            """,
            (book_id, *params),
        ).fetchone()
        return int(row["next_order"]) if row else 1

    def list_books(self, user_id: int | None = None) -> list[sqlite3.Row]:
        if user_id is not None:
            cursor = self.connection.execute(
                "SELECT id, title FROM books WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            )
        else:
            cursor = self.connection.execute(
                "SELECT id, title FROM books ORDER BY id DESC"
            )
        return list(cursor.fetchall())

    def create_book(self, title: str, user_id: int | None = None) -> int:
        outline_data = book_outline_form_defaults(title)
        outline_text = book_outline_form_to_markdown(outline_data, title)
        world_data = world_form_defaults()
        world_text = world_form_to_markdown(world_data)
        cursor = self.connection.execute(
            """
            INSERT INTO books (title, outline_text, outline_data_json, world_text, world_data_json, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                outline_text,
                self._book_outline_data_to_json(outline_data, title),
                world_text,
                self._world_form_data_to_json(world_data),
                user_id,
            ),
        )
        book_id = int(cursor.lastrowid)
        self.connection.commit()
        self.log_change("books", book_id, "insert", {"id": book_id, "title": title, "user_id": user_id})
        return book_id

    def get_book(self, book_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT id, title, outline_text, outline_data_json, world_text, world_data_json, cover_image_path, user_id, cloud_book_id
            FROM books
            WHERE id = ?
            """,
            (book_id,),
        )
        return cursor.fetchone()

    def check_book_ownership(self, book_id: int, user_id: int) -> bool:
        """检查书籍是否属于指定用户。严格隔离：未绑定用户的书籍不允许访问。"""
        row = self.connection.execute(
            "SELECT user_id FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if not row:
            return False
        book_user_id = row["user_id"]
        if book_user_id is None:
            return False
        return int(book_user_id) == int(user_id)

    def rename_book(self, book_id: int, title: str) -> None:
        self.connection.execute(
            """
            UPDATE books
            SET title = ?
            WHERE id = ?
            """,
            (title, book_id),
        )
        self.connection.commit()
        self.log_change("books", book_id, "update", {"id": book_id, "title": title})

    def update_book_outline(self, book_id: int, outline_text: str, outline_data: dict[str, Any] | None = None) -> None:
        book = self.get_book(book_id)
        title = str(book["title"] or "") if book else ""
        volume_specs = self._book_outline_volume_specs(book_id)
        if outline_data is None:
            outline_text, outline_data_json = self._book_outline_payload_from_text(outline_text, title, volume_specs)
        else:
            normalized = normalize_book_outline_form(outline_data, title, volume_specs)
            outline_text = book_outline_form_to_markdown(normalized, title, volume_specs)
            outline_data_json = self._book_outline_data_to_json(normalized, title, volume_specs)
        self.connection.execute(
            """
            UPDATE books
            SET outline_text = ?, outline_data_json = ?
            WHERE id = ?
            """,
            (outline_text, outline_data_json, book_id),
        )
        self.connection.commit()

    def update_book_outline_form(self, book_id: int, outline_data: dict[str, Any]) -> None:
        self.update_book_outline(book_id, "", outline_data=outline_data)

    def get_book_outline_form(self, book_id: int) -> dict[str, Any]:
        book = self.get_book(book_id)
        if not book:
            return book_outline_form_defaults("")
        title = str(book["title"] or "")
        volume_specs = self._book_outline_volume_specs(book_id)
        data = self._book_outline_json_to_data(str(book["outline_data_json"] or ""), title, volume_specs)
        if data is None:
            data = book_outline_markdown_to_form(str(book["outline_text"] or ""), title, volume_specs)
        return normalize_book_outline_form(data, title, volume_specs)

    def update_book_world(self, book_id: int, world_text: str, world_data: dict[str, Any] | None = None) -> None:
        if world_data is None:
            world_text, world_data_json = self._world_payload_from_text(world_text)
        else:
            normalized = normalize_world_form(world_data)
            world_text = world_form_to_markdown(normalized)
            world_data_json = self._world_form_data_to_json(normalized)
        self.connection.execute(
            """
            UPDATE books
            SET world_text = ?, world_data_json = ?
            WHERE id = ?
            """,
            (world_text, world_data_json, book_id),
        )
        self.connection.commit()

    def update_book_world_form(self, book_id: int, world_data: dict[str, Any]) -> None:
        self.update_book_world(book_id, "", world_data=world_data)

    def get_book_world_form(self, book_id: int) -> dict[str, Any]:
        book = self.get_book(book_id)
        if not book:
            return world_form_defaults()
        data = self._world_form_json_to_data(str(book["world_data_json"] or ""))
        if data is None:
            data = world_markdown_to_form(str(book["world_text"] or ""))
        return normalize_world_form(data)

    def update_book_cover(self, book_id: int, cover_image_path: str) -> None:
        self.connection.execute(
            """
            UPDATE books
            SET cover_image_path = ?
            WHERE id = ?
            """,
            (cover_image_path, book_id),
        )
        self.connection.commit()

    def delete_book(self, book_id: int) -> None:
        self.connection.execute(
            "DELETE FROM books WHERE id = ?",
            (book_id,),
        )
        self.connection.commit()
        self.log_change("books", book_id, "delete", {"id": book_id})

    def list_volumes(self, book_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                v.id,
                v.book_id,
                v.title,
                v.outline_text,
                v.sort_order,
                COUNT(c.id) AS chapter_count
            FROM volumes AS v
            LEFT JOIN chapters AS c ON c.volume_id = v.id
            WHERE v.book_id = ?
            GROUP BY v.id, v.book_id, v.title, v.outline_text, v.sort_order
            ORDER BY v.sort_order ASC, v.id ASC
            """,
            (book_id,),
        )
        return list(cursor.fetchall())

    def count_unassigned_chapters(self, book_id: int) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM chapters
            WHERE book_id = ? AND volume_id IS NULL
            """,
            (book_id,),
        ).fetchone()
        return int(row["count"]) if row else 0

    def create_volume(self, book_id: int, title: str) -> int:
        # 多表写入（volumes + books outline 刷新）必须用事务保护，防止部分写入
        with self.transaction():
            cursor = self.connection.execute(
                """
                INSERT INTO volumes (book_id, title, sort_order)
                VALUES (?, ?, ?)
                """,
                (book_id, title, self._next_volume_sort_order(book_id)),
            )
            volume_id = int(cursor.lastrowid)
            self._refresh_book_outline_volume_plans(book_id)
        return volume_id

    def get_volume(self, volume_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT id, book_id, title, outline_text, sort_order
            FROM volumes
            WHERE id = ?
            """,
            (volume_id,),
        )
        return cursor.fetchone()

    def rename_volume(self, volume_id: int, title: str) -> None:
        self.connection.execute(
            """
            UPDATE volumes
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, volume_id),
        )
        updated = self.get_volume(volume_id)
        if updated:
            self._refresh_book_outline_volume_plans(int(updated["book_id"]))
        self.connection.commit()

    def update_volume_outline(self, volume_id: int, outline_text: str) -> None:
        self.connection.execute(
            """
            UPDATE volumes
            SET outline_text = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (outline_text, volume_id),
        )
        self.connection.commit()

    def delete_volume(self, volume_id: int) -> None:
        volume = self.get_volume(volume_id)
        if not volume:
            return

        book_id = int(volume["book_id"])
        self.connection.execute(
            "DELETE FROM volumes WHERE id = ?",
            (volume_id,),
        )
        self._normalize_volume_order(book_id)
        self._normalize_all_chapter_orders()
        self._refresh_book_outline_volume_plans(book_id)
        self.connection.commit()

    def move_volume(self, volume_id: int, direction: int) -> bool:
        if direction == 0:
            return False
        current = self.get_volume(volume_id)
        if not current:
            return False

        with self.connection:
            comparator = "<" if direction < 0 else ">"
            order = "DESC" if direction < 0 else "ASC"
            neighbor = self.connection.execute(
                f"""
                SELECT id, sort_order
                FROM volumes
                WHERE book_id = ? AND sort_order {comparator} ?
                ORDER BY sort_order {order}, id {order}
                LIMIT 1
                """,
                (int(current["book_id"]), int(current["sort_order"])),
            ).fetchone()
            if not neighbor:
                return False

            self.connection.execute(
                "UPDATE volumes SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(neighbor["sort_order"]), volume_id),
            )
            self.connection.execute(
                "UPDATE volumes SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(current["sort_order"]), int(neighbor["id"])),
            )
            self._normalize_volume_order(int(current["book_id"]))
            self._refresh_book_outline_volume_plans(int(current["book_id"]))
        return True

    def list_chapters(self, book_id: int, volume_filter: int | str = ALL_VOLUMES) -> list[sqlite3.Row]:
        base_sql = """
            SELECT
                c.id,
                c.title,
                c.sort_order,
                c.volume_id,
                LENGTH(COALESCE(c.content, '')) AS word_count,
                c.ai_probability,
                c.ai_probability_level,
                COALESCE(tmpl.is_template, 0) AS is_template,
                COALESCE(v.title, '未分卷') AS volume_title,
                COALESCE(v.sort_order, 2147483647) AS volume_sort_order
            FROM chapters AS c
            LEFT JOIN volumes AS v ON v.id = c.volume_id
            LEFT JOIN (
                SELECT chapter_id, 1 AS is_template
                FROM chapter_tags
                WHERE tag = 'template'
            ) AS tmpl ON tmpl.chapter_id = c.id
            WHERE c.book_id = ?
        """
        params: list[Any] = [book_id]

        if volume_filter == UNASSIGNED_VOLUMES:
            base_sql += " AND c.volume_id IS NULL"
            order_sql = " ORDER BY c.sort_order ASC, c.id ASC"
        elif volume_filter != ALL_VOLUMES:
            base_sql += " AND c.volume_id = ?"
            params.append(volume_filter)
            order_sql = " ORDER BY c.sort_order ASC, c.id ASC"
        else:
            order_sql = """
                ORDER BY
                    CASE WHEN c.volume_id IS NULL THEN 1 ELSE 0 END ASC,
                    COALESCE(v.sort_order, 2147483647) ASC,
                    c.sort_order ASC,
                    c.id ASC
            """

        cursor = self.connection.execute(base_sql + order_sql, params)
        return list(cursor.fetchall())

    def create_chapter(self, book_id: int, title: str, volume_id: int | None = None) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO chapters (book_id, volume_id, title, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (book_id, volume_id, title, self._next_chapter_sort_order(book_id, volume_id)),
        )
        chapter_id = int(cursor.lastrowid)
        self.connection.commit()
        self.log_change("chapters", chapter_id, "insert",
                        {"id": chapter_id, "book_id": book_id, "title": title})
        return chapter_id

    def get_chapter(self, chapter_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT
                c.id,
                c.book_id,
                c.volume_id,
                c.title,
                c.outline,
                c.content,
                c.summary_text,
                c.ai_probability,
                c.ai_probability_level,
                c.sort_order,
                c.updated_at,
                COALESCE(v.title, '未分卷') AS volume_title,
                EXISTS(
                    SELECT 1 FROM chapter_tags AS ct
                    WHERE ct.chapter_id = c.id AND ct.tag = 'template'
                ) AS is_template
            FROM chapters AS c
            LEFT JOIN volumes AS v ON v.id = c.volume_id
            WHERE c.id = ?
            """,
            (chapter_id,),
        )
        return cursor.fetchone()

    def rename_chapter(self, chapter_id: int, title: str) -> None:
        self.connection.execute(
            """
            UPDATE chapters
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, chapter_id),
        )
        self.connection.commit()
        self.log_change("chapters", chapter_id, "update", {"id": chapter_id, "title": title})

    def delete_chapter(self, chapter_id: int) -> None:
        chapter = self.connection.execute(
            """
            SELECT id, book_id, volume_id
            FROM chapters
            WHERE id = ?
            """,
            (chapter_id,),
        ).fetchone()
        if not chapter:
            return

        self.connection.execute(
            "DELETE FROM chapters WHERE id = ?",
            (chapter_id,),
        )
        self._normalize_chapter_order(int(chapter["book_id"]), chapter["volume_id"])
        self.connection.commit()
        self.log_change("chapters", chapter_id, "delete",
                        {"id": chapter_id, "book_id": int(chapter["book_id"])})

    def update_chapter(
        self,
        chapter_id: int,
        outline: str,
        content: str,
        summary_text: str = "",
        chapter_type: str | None = None,
    ) -> None:
        if chapter_type is not None:
            valid_types = {"正文", "番外", "作者的话"}
            if chapter_type not in valid_types:
                chapter_type = "正文"
            self.connection.execute(
                """
                UPDATE chapters
                SET outline = ?, content = ?, summary_text = ?, chapter_type = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (outline, content, summary_text, chapter_type, chapter_id),
            )
        else:
            self.connection.execute(
                """
                UPDATE chapters
                SET outline = ?, content = ?, summary_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (outline, content, summary_text, chapter_id),
            )
        self.connection.commit()
        self.log_change("chapters", chapter_id, "update", {"id": chapter_id})

    def update_chapter_ai_probability(self, chapter_id: int, probability: int, level: str) -> None:
        probability = max(0, min(100, int(probability)))
        normalized_level = level if level in {"certain", "high", "medium", "low", "none"} else "none"
        self.connection.execute(
            """
            UPDATE chapters
            SET ai_probability = ?, ai_probability_level = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (probability, normalized_level, chapter_id),
        )
        self.connection.commit()

    def set_chapter_tag(self, chapter_id: int, tag: str) -> None:
        cleaned = str(tag or "").strip()
        if not cleaned:
            return
        self.connection.execute(
            """
            INSERT OR IGNORE INTO chapter_tags (chapter_id, tag)
            VALUES (?, ?)
            """,
            (chapter_id, cleaned),
        )
        self.connection.commit()

    def remove_chapter_tag(self, chapter_id: int, tag: str) -> None:
        self.connection.execute(
            "DELETE FROM chapter_tags WHERE chapter_id = ? AND tag = ?",
            (chapter_id, str(tag or "").strip()),
        )
        self.connection.commit()

    def has_chapter_tag(self, chapter_id: int, tag: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM chapter_tags
            WHERE chapter_id = ? AND tag = ?
            LIMIT 1
            """,
            (chapter_id, str(tag or "").strip()),
        ).fetchone()
        return row is not None

    def list_template_chapters(self, book_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                c.id,
                c.book_id,
                c.volume_id,
                c.title,
                c.outline,
                c.content,
                c.sort_order,
                COALESCE(v.title, '未分卷') AS volume_title
            FROM chapter_tags AS tag
            JOIN chapters AS c ON c.id = tag.chapter_id
            LEFT JOIN volumes AS v ON v.id = c.volume_id
            WHERE c.book_id = ? AND tag.tag = 'template'
            ORDER BY
                CASE WHEN c.volume_id IS NULL THEN 1 ELSE 0 END ASC,
                COALESCE(v.sort_order, 2147483647) ASC,
                c.sort_order ASC,
                c.id ASC
            """,
            (book_id,),
        )
        return list(cursor.fetchall())

    def list_chapter_ai_spans(self, chapter_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT id, chapter_id, start_offset, end_offset, source_task_id, created_at
            FROM chapter_ai_spans
            WHERE chapter_id = ?
            ORDER BY start_offset ASC, id ASC
            """,
            (chapter_id,),
        )
        return list(cursor.fetchall())

    def add_chapter_ai_span(
        self,
        chapter_id: int,
        start_offset: int,
        end_offset: int,
        source_task_id: str = "",
    ) -> int:
        start = max(0, int(start_offset))
        end = max(start, int(end_offset))
        if end <= start:
            return 0
        cursor = self.connection.execute(
            """
            INSERT INTO chapter_ai_spans (chapter_id, start_offset, end_offset, source_task_id)
            VALUES (?, ?, ?, ?)
            """,
            (chapter_id, start, end, source_task_id),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def delete_chapter_ai_spans(self, chapter_id: int) -> None:
        self.connection.execute(
            "DELETE FROM chapter_ai_spans WHERE chapter_id = ?",
            (chapter_id,),
        )
        self.connection.commit()

    def delete_chapter_ai_spans_in_range(self, chapter_id: int, start_offset: int, end_offset: int) -> None:
        start = max(0, int(start_offset))
        end = max(start, int(end_offset))
        self.connection.execute(
            """
            DELETE FROM chapter_ai_spans
            WHERE chapter_id = ?
              AND start_offset < ?
              AND end_offset > ?
            """,
            (chapter_id, end, start),
        )
        self.connection.commit()

    def update_chapter_summary(self, chapter_id: int, summary_text: str) -> None:
        self.connection.execute(
            """
            UPDATE chapters
            SET summary_text = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (summary_text, chapter_id),
        )
        self.connection.commit()

    def update_chapter_volume(self, chapter_id: int, volume_id: int | None) -> None:
        chapter = self.connection.execute(
            """
            SELECT id, book_id, volume_id
            FROM chapters
            WHERE id = ?
            """,
            (chapter_id,),
        ).fetchone()
        if not chapter:
            return

        old_volume_id = chapter["volume_id"]
        if old_volume_id == volume_id:
            return

        book_id = int(chapter["book_id"])
        new_order = self._next_chapter_sort_order(book_id, volume_id)
        self.connection.execute(
            """
            UPDATE chapters
            SET volume_id = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (volume_id, new_order, chapter_id),
        )
        self._normalize_chapter_order(book_id, old_volume_id)
        self._normalize_chapter_order(book_id, volume_id)
        self.connection.commit()

    def move_chapter(self, chapter_id: int, direction: int) -> bool:
        if direction == 0:
            return False
        current = self.connection.execute(
            """
            SELECT id, book_id, volume_id, sort_order
            FROM chapters
            WHERE id = ?
            """,
            (chapter_id,),
        ).fetchone()
        if not current:
            return False

        with self.connection:
            comparator = "<" if direction < 0 else ">"
            order = "DESC" if direction < 0 else "ASC"
            clause, params = self._build_volume_clause(current["volume_id"])
            neighbor = self.connection.execute(
                f"""
                SELECT id, sort_order
                FROM chapters
                WHERE book_id = ? AND {clause} AND sort_order {comparator} ?
                ORDER BY sort_order {order}, id {order}
                LIMIT 1
                """,
                (int(current["book_id"]), *params, int(current["sort_order"])),
            ).fetchone()
            if not neighbor:
                return False

            self.connection.execute(
                "UPDATE chapters SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(neighbor["sort_order"]), chapter_id),
            )
            self.connection.execute(
                "UPDATE chapters SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(current["sort_order"]), int(neighbor["id"])),
            )
            self._normalize_chapter_order(int(current["book_id"]), current["volume_id"])
        return True

    # ================================================================
    #  伏笔（foreshadows）CRUD
    # ================================================================

    _FORESHADOW_STATUS_VALUES = {"pending", "resolved", "abandoned"}
    _FORESHADOW_PRIORITY_VALUES = {"high", "medium", "low"}
    _FORESHADOW_SOURCE_VALUES = {"auto", "manual"}

    def list_foreshadows(
        self,
        book_id: int,
        *,
        status: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        """列出书籍的伏笔，可按状态筛选。"""
        if status and status not in self._FORESHADOW_STATUS_VALUES:
            status = None
        if status:
            sql = (
                "SELECT f.*, "
                "sc.title AS setup_chapter_title, "
                "pc.title AS payoff_chapter_title "
                "FROM foreshadows f "
                "LEFT JOIN chapters sc ON f.setup_chapter_id = sc.id "
                "LEFT JOIN chapters pc ON f.payoff_chapter_id = pc.id "
                "WHERE f.book_id = ? AND f.status = ? "
                "ORDER BY f.created_at DESC LIMIT ?"
            )
            rows = self.connection.execute(sql, (book_id, status, limit)).fetchall()
        else:
            sql = (
                "SELECT f.*, "
                "sc.title AS setup_chapter_title, "
                "pc.title AS payoff_chapter_title "
                "FROM foreshadows f "
                "LEFT JOIN chapters sc ON f.setup_chapter_id = sc.id "
                "LEFT JOIN chapters pc ON f.payoff_chapter_id = pc.id "
                "WHERE f.book_id = ? "
                "ORDER BY f.created_at DESC LIMIT ?"
            )
            rows = self.connection.execute(sql, (book_id, limit)).fetchall()
        return rows

    def get_foreshadow(self, foreshadow_id: int) -> sqlite3.Row | None:
        """获取单个伏笔。"""
        return self.connection.execute(
            "SELECT * FROM foreshadows WHERE id = ?",
            (foreshadow_id,),
        ).fetchone()

    def create_foreshadow(
        self,
        book_id: int,
        description: str,
        *,
        status: str = "pending",
        priority: str = "medium",
        source: str = "manual",
        setup_chapter_id: int | None = None,
        payoff_chapter_id: int | None = None,
        resolution_note: str = "",
        fact_uid: str = "",
    ) -> int:
        """新增伏笔。"""
        if status not in self._FORESHADOW_STATUS_VALUES:
            status = "pending"
        if priority not in self._FORESHADOW_PRIORITY_VALUES:
            priority = "medium"
        if source not in self._FORESHADOW_SOURCE_VALUES:
            source = "manual"
        cursor = self.connection.execute(
            """
            INSERT INTO foreshadows
                (book_id, description, status, priority, source,
                 setup_chapter_id, payoff_chapter_id, resolution_note, fact_uid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                description,
                status,
                priority,
                source,
                setup_chapter_id,
                payoff_chapter_id,
                resolution_note,
                fact_uid,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_foreshadow(self, foreshadow_id: int, **fields) -> sqlite3.Row | None:
        """更新伏笔字段（仅允许白名单字段）。"""
        allowed = {
            "description", "status", "priority",
            "setup_chapter_id", "payoff_chapter_id",
            "resolution_note",
        }
        updates = []
        params = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "status" and value not in self._FORESHADOW_STATUS_VALUES:
                continue
            if key == "priority" and value not in self._FORESHADOW_PRIORITY_VALUES:
                continue
            updates.append(f"{key} = ?")
            params.append(value)
        if not updates:
            return self.get_foreshadow(foreshadow_id)
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(foreshadow_id)
        self.connection.execute(
            f"UPDATE foreshadows SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self.connection.commit()
        return self.get_foreshadow(foreshadow_id)

    def delete_foreshadow(self, foreshadow_id: int) -> bool:
        """删除伏笔，返回是否删除成功。"""
        cursor = self.connection.execute(
            "DELETE FROM foreshadows WHERE id = ?",
            (foreshadow_id,),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def find_foreshadow_by_fact_uid(self, book_id: int, fact_uid: str) -> sqlite3.Row | None:
        """根据 fact_uid 查找伏笔（用于去重）。"""
        if not fact_uid:
            return None
        return self.connection.execute(
            "SELECT * FROM foreshadows WHERE book_id = ? AND fact_uid = ?",
            (book_id, fact_uid),
        ).fetchone()

    def create_snapshot(
        self,
        chapter_id: int,
        label: str,
        outline: str,
        content: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO chapter_snapshots (chapter_id, label, outline, content)
            VALUES (?, ?, ?, ?)
            """,
            (chapter_id, label, outline, content),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_snapshots(self, chapter_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT id, label, created_at
            FROM chapter_snapshots
            WHERE chapter_id = ?
            ORDER BY id DESC
            """,
            (chapter_id,),
        )
        return list(cursor.fetchall())

    def get_snapshot(self, snapshot_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT id, chapter_id, label, outline, content, created_at
            FROM chapter_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        )
        return cursor.fetchone()
