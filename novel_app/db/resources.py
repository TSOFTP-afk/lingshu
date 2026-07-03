from __future__ import annotations

from novel_app.db.common import *


class ResourcesMixin:
    def list_chapter_events(self, book_id: int, chapter_id: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT
                e.id,
                e.book_id,
                e.chapter_id,
                e.label,
                e.description,
                e.sort_order,
                c.title AS chapter_title,
                c.sort_order AS chapter_sort_order
            FROM chapter_events AS e
            JOIN chapters AS c ON c.id = e.chapter_id
            WHERE e.book_id = ?
        """
        params: list[Any] = [book_id]
        if chapter_id is not None:
            sql += " AND e.chapter_id = ?"
            params.append(chapter_id)
        sql += " ORDER BY c.sort_order ASC, e.sort_order ASC, e.id ASC"
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def create_chapter_event(
        self,
        book_id: int,
        chapter_id: int,
        label: str,
        description: str = "",
        sort_order: int | None = None,
    ) -> int:
        if sort_order is None:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM chapter_events WHERE chapter_id = ?",
                (chapter_id,),
            ).fetchone()
            sort_order = int(row["next_order"]) if row else 1
        cursor = self.connection.execute(
            """
            INSERT INTO chapter_events (book_id, chapter_id, label, description, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (book_id, chapter_id, label, description, sort_order),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_chapter_event(
        self,
        event_id: int,
        label: str,
        description: str = "",
        sort_order: int | None = None,
    ) -> None:
        if sort_order is None:
            self.connection.execute(
                """
                UPDATE chapter_events
                SET label = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (label, description, event_id),
            )
        else:
            self.connection.execute(
                """
                UPDATE chapter_events
                SET label = ?, description = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (label, description, sort_order, event_id),
            )
        self.connection.commit()

    def delete_chapter_event(self, event_id: int) -> None:
        self.connection.execute("DELETE FROM chapter_events WHERE id = ?", (event_id,))
        self.connection.commit()

    def list_reference_sources(self) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                id,
                title,
                author,
                source_path,
                rights_note,
                source_type,
                source_url,
                source_license,
                reusable_level,
                attribution_note,
                created_at
            FROM reference_sources
            ORDER BY id DESC
            """
        )
        return list(cursor.fetchall())

    def create_reference_source(
        self,
        title: str,
        source_path: str,
        author: str = "",
        rights_note: str = "",
        source_type: str = "book",
        source_url: str = "",
        source_license: str = "",
        reusable_level: str = "pattern_only",
        attribution_note: str = "",
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO reference_sources (
                title,
                author,
                source_path,
                rights_note,
                source_type,
                source_url,
                source_license,
                reusable_level,
                attribution_note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                author,
                source_path,
                rights_note,
                source_type,
                source_url,
                source_license,
                reusable_level,
                attribution_note,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def get_reference_source(self, source_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT
                id,
                title,
                author,
                source_path,
                rights_note,
                source_type,
                source_url,
                source_license,
                reusable_level,
                attribution_note,
                created_at
            FROM reference_sources
            WHERE id = ?
            """,
            (source_id,),
        )
        return cursor.fetchone()

    def delete_reference_source(self, source_id: int) -> None:
        self.connection.execute("DELETE FROM reference_sources WHERE id = ?", (source_id,))
        self.connection.commit()

    def get_reference_source_by_url(self, source_url: str) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT
                id,
                title,
                author,
                source_path,
                rights_note,
                source_type,
                source_url,
                source_license,
                reusable_level,
                attribution_note,
                created_at
            FROM reference_sources
            WHERE source_url = ?
            """,
            (source_url,),
        )
        return cursor.fetchone()

    def bind_reference_source_to_book(
        self,
        book_id: int,
        source_id: int,
        *,
        role: str = "style_reference",
        import_mode: str = "base_data",
        notes: str = "",
    ) -> int:
        role = str(role or "style_reference").strip() or "style_reference"
        import_mode = str(import_mode or "base_data").strip() or "base_data"
        notes = str(notes or "").strip()
        cursor = self.connection.execute(
            """
            INSERT INTO book_reference_sources (book_id, source_id, role, import_mode, notes, enabled)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(book_id, source_id) DO UPDATE SET
                role = excluded.role,
                import_mode = excluded.import_mode,
                notes = excluded.notes,
                enabled = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (book_id, source_id, role, import_mode, notes),
        )
        self.connection.commit()
        if cursor.lastrowid:
            return int(cursor.lastrowid)
        row = self.connection.execute(
            "SELECT id FROM book_reference_sources WHERE book_id = ? AND source_id = ?",
            (book_id, source_id),
        ).fetchone()
        return int(row["id"]) if row else 0

    def list_book_reference_sources(self, book_id: int, enabled_only: bool = True) -> list[sqlite3.Row]:
        sql = """
            SELECT
                brs.id,
                brs.book_id,
                brs.source_id,
                brs.role,
                brs.import_mode,
                brs.notes,
                brs.enabled,
                brs.created_at,
                brs.updated_at,
                rs.title AS source_title,
                rs.author AS source_author,
                rs.source_path AS source_path,
                rs.rights_note AS rights_note,
                rs.source_type AS source_type,
                rs.source_url AS source_url,
                rs.source_license AS source_license,
                rs.reusable_level AS reusable_level,
                rs.attribution_note AS attribution_note
            FROM book_reference_sources AS brs
            JOIN reference_sources AS rs ON rs.id = brs.source_id
            WHERE brs.book_id = ?
        """
        params: list[Any] = [book_id]
        if enabled_only:
            sql += " AND brs.enabled = 1"
        sql += " ORDER BY brs.enabled DESC, brs.updated_at DESC, brs.id DESC"
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def update_book_reference_binding(
        self,
        book_id: int,
        source_id: int,
        *,
        role: str | None = None,
        enabled: bool | None = None,
        notes: str | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[Any] = []
        if role is not None:
            updates.append("role = ?")
            params.append(str(role or "style_reference").strip() or "style_reference")
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if notes is not None:
            updates.append("notes = ?")
            params.append(str(notes or "").strip())
        if not updates:
            return
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([book_id, source_id])
        self.connection.execute(
            f"""
            UPDATE book_reference_sources
            SET {", ".join(updates)}
            WHERE book_id = ? AND source_id = ?
            """,
            params,
        )
        self.connection.commit()

    def unbind_reference_source_from_book(self, book_id: int, source_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM book_reference_segments WHERE book_id = ? AND source_id = ?",
                (book_id, source_id),
            )
            self.connection.execute(
                "DELETE FROM book_reference_sources WHERE book_id = ? AND source_id = ?",
                (book_id, source_id),
            )

    def create_book_reference_segments(
        self,
        book_id: int,
        source_id: int,
        segments: list[dict[str, Any]],
    ) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM book_reference_segments WHERE book_id = ? AND source_id = ?",
                (book_id, source_id),
            )
            for index, segment in enumerate(segments, start=1):
                if not isinstance(segment, dict):
                    continue
                content = str(segment.get("content") or segment.get("text") or "").strip()
                if not content:
                    continue
                segment_index = self._book_reference_int(segment.get("segment_index"), index)
                title = str(segment.get("title") or segment.get("chapter_title") or "").strip()
                summary = str(segment.get("summary") or "").strip()
                metadata = segment.get("metadata") if isinstance(segment.get("metadata"), dict) else {}
                self.connection.execute(
                    """
                    INSERT INTO book_reference_segments (
                        book_id, source_id, segment_index, title, content, summary, content_hash, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        source_id,
                        segment_index,
                        title,
                        content,
                        summary,
                        hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        self._json_payload(metadata),
                    ),
                )

    def list_book_reference_segments(
        self,
        book_id: int,
        source_id: int | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT
                brseg.id,
                brseg.book_id,
                brseg.source_id,
                brseg.segment_index,
                brseg.title,
                brseg.content,
                brseg.summary,
                brseg.content_hash,
                brseg.metadata_json,
                brseg.created_at,
                brs.role AS role,
                brs.enabled AS enabled,
                rs.title AS source_title,
                rs.author AS source_author,
                rs.source_path AS source_path,
                rs.source_type AS source_type
            FROM book_reference_segments AS brseg
            JOIN reference_sources AS rs ON rs.id = brseg.source_id
            LEFT JOIN book_reference_sources AS brs
                ON brs.book_id = brseg.book_id AND brs.source_id = brseg.source_id
            WHERE brseg.book_id = ?
        """
        params: list[Any] = [book_id]
        if source_id is not None:
            sql += " AND brseg.source_id = ?"
            params.append(source_id)
        sql += " ORDER BY brseg.source_id ASC, brseg.segment_index ASC, brseg.id ASC LIMIT ?"
        params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def build_book_reference_context(self, book_id: int, max_chars: int = 3000) -> str:
        max_total = max(200, int(max_chars))
        bindings = self.list_book_reference_sources(book_id, enabled_only=True)
        if not bindings:
            return ""
        lines = ["【参考书基础数据】"]
        total_chars = len(lines[0])
        for binding in bindings:
            source_id = int(binding["source_id"])
            role = str(binding["role"] or "style_reference")
            role_label = self._book_reference_role_label(role)
            source_title = str(binding["source_title"] or "未命名参考书").strip()
            segments = self.list_book_reference_segments(book_id, source_id=source_id, limit=24)
            if not segments:
                note = str(binding["notes"] or "").strip()
                line = f"- [{role_label}]《{source_title}》：已绑定，尚未分段" + (f"；备注：{note[:120]}" if note else "")
                total_chars = self._append_book_reference_context_line(lines, line, total_chars, max_total)
                if total_chars >= max_total:
                    break
                continue
            for segment in segments:
                title = str(segment["title"] or "").strip()
                label = title or f"第 {int(segment['segment_index'])} 段"
                text = str(segment["summary"] or segment["content"] or "").strip()
                if not text:
                    continue
                line = f"- [{role_label}]《{source_title}》{label}：{text[:420]}"
                total_chars = self._append_book_reference_context_line(lines, line, total_chars, max_total)
                if total_chars >= max_total:
                    break
            if total_chars >= max_total:
                break
        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _append_book_reference_context_line(
        lines: list[str],
        line: str,
        total_chars: int,
        max_total: int,
    ) -> int:
        remaining = max_total - total_chars - 1
        if remaining <= 0:
            return max_total
        if len(line) > remaining:
            line = line[: max(0, remaining - 1)] + "…"
        if line.strip():
            lines.append(line)
            total_chars += len(line) + 1
        return total_chars

    @staticmethod
    def _book_reference_role_label(role: str) -> str:
        return {
            "style_reference": "文风参考",
            "canon_reference": "设定参考",
            "structure_reference": "结构参考",
            "avoid_reference": "规避参考",
        }.get(str(role or "").strip(), str(role or "参考书").strip() or "参考书")

    @staticmethod
    def _book_reference_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def replace_skills_for_source(self, source_id: int, skills: list[dict[str, Any]]) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM distilled_skills WHERE source_id = ?",
                (source_id,),
            )

            for skill in skills:
                self.connection.execute(
                    """
                    INSERT INTO distilled_skills (
                        source_id,
                        name,
                        category,
                        summary,
                        instruction_text,
                        use_cases_text,
                        risk_note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        skill["name"],
                        skill["category"],
                        skill["summary"],
                        skill["instruction"],
                        skill.get("use_cases", ""),
                        skill.get("risk_note", ""),
                    ),
                )

    def list_skills(self, source_id: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT
                ds.id,
                ds.source_id,
                ds.name,
                ds.category,
                ds.summary,
                ds.instruction_text,
                ds.use_cases_text,
                ds.risk_note,
                rs.title AS source_title,
                rs.source_type AS source_type,
                rs.source_url AS source_url,
                rs.source_license AS source_license,
                rs.reusable_level AS reusable_level,
                rs.attribution_note AS attribution_note
            FROM distilled_skills AS ds
            JOIN reference_sources AS rs ON rs.id = ds.source_id
        """
        params: tuple[Any, ...] = ()
        if source_id is not None:
            sql += " WHERE ds.source_id = ?"
            params = (source_id,)
        sql += " ORDER BY ds.id DESC"
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def delete_skill(self, skill_id: int) -> None:
        self.connection.execute("DELETE FROM distilled_skills WHERE id = ?", (skill_id,))
        self.connection.commit()

    def bind_skill_to_book(self, book_id: int, skill_id: int, weight: float = 1.0) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO skill_bindings (scope_type, scope_id, skill_id, weight)
            VALUES ('book', ?, ?, ?)
            """,
            (book_id, skill_id, weight),
        )
        self.connection.commit()

    def bind_skill_to_global(self, skill_id: int, weight: float = 1.0) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO skill_bindings (scope_type, scope_id, skill_id, weight)
            VALUES ('global', 0, ?, ?)
            """,
            (skill_id, weight),
        )
        self.connection.commit()

    def unbind_skill_from_global(self, skill_id: int) -> None:
        self.connection.execute(
            """
            DELETE FROM skill_bindings
            WHERE scope_type = 'global' AND scope_id = 0 AND skill_id = ?
            """,
            (skill_id,),
        )
        self.connection.commit()

    def list_bound_skills_for_global(self) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                ds.id,
                ds.source_id,
                ds.name,
                ds.category,
                ds.summary,
                ds.instruction_text,
                ds.use_cases_text,
                ds.risk_note,
                sb.weight,
                rs.title AS source_title,
                rs.source_type AS source_type,
                rs.source_url AS source_url,
                rs.source_license AS source_license,
                rs.reusable_level AS reusable_level,
                rs.attribution_note AS attribution_note
            FROM skill_bindings AS sb
            JOIN distilled_skills AS ds ON ds.id = sb.skill_id
            JOIN reference_sources AS rs ON rs.id = ds.source_id
            WHERE sb.scope_type = 'global' AND sb.scope_id = 0
            ORDER BY sb.id DESC
            """
        )
        return list(cursor.fetchall())

    def unbind_skill_from_book(self, book_id: int, skill_id: int) -> None:
        self.connection.execute(
            """
            DELETE FROM skill_bindings
            WHERE scope_type = 'book' AND scope_id = ? AND skill_id = ?
            """,
            (book_id, skill_id),
        )
        self.connection.commit()

    def list_bound_skills_for_book(self, book_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                ds.id,
                ds.source_id,
                ds.name,
                ds.category,
                ds.summary,
                ds.instruction_text,
                ds.use_cases_text,
                ds.risk_note,
                sb.weight,
                rs.title AS source_title,
                rs.source_type AS source_type,
                rs.source_url AS source_url,
                rs.source_license AS source_license,
                rs.reusable_level AS reusable_level,
                rs.attribution_note AS attribution_note
            FROM skill_bindings AS sb
            JOIN distilled_skills AS ds ON ds.id = sb.skill_id
            JOIN reference_sources AS rs ON rs.id = ds.source_id
            WHERE sb.scope_type = 'book' AND sb.scope_id = ?
            ORDER BY sb.id DESC
            """,
            (book_id,),
        )
        return list(cursor.fetchall())

    def bind_skill_to_chapter(self, chapter_id: int, skill_id: int, weight: float = 1.0) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO skill_bindings (scope_type, scope_id, skill_id, weight)
            VALUES ('chapter', ?, ?, ?)
            """,
            (chapter_id, skill_id, weight),
        )
        self.connection.commit()

    def unbind_skill_from_chapter(self, chapter_id: int, skill_id: int) -> None:
        self.connection.execute(
            """
            DELETE FROM skill_bindings
            WHERE scope_type = 'chapter' AND scope_id = ? AND skill_id = ?
            """,
            (chapter_id, skill_id),
        )
        self.connection.commit()

    def list_bound_skills_for_chapter(self, chapter_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                ds.id,
                ds.source_id,
                ds.name,
                ds.category,
                ds.summary,
                ds.instruction_text,
                ds.use_cases_text,
                ds.risk_note,
                sb.weight,
                rs.title AS source_title,
                rs.source_type AS source_type,
                rs.source_url AS source_url,
                rs.source_license AS source_license,
                rs.reusable_level AS reusable_level,
                rs.attribution_note AS attribution_note
            FROM skill_bindings AS sb
            JOIN distilled_skills AS ds ON ds.id = sb.skill_id
            JOIN reference_sources AS rs ON rs.id = ds.source_id
            WHERE sb.scope_type = 'chapter' AND sb.scope_id = ?
            ORDER BY sb.id DESC
            """,
            (chapter_id,),
        )
        return list(cursor.fetchall())
