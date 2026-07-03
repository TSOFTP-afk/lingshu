from __future__ import annotations

from novel_app.db.common import *


class LegacyMixin:
    def _legacy_data_dirs_from_env(self) -> list[Path]:
        raw = os.environ.get("SIMPLE_AI_NOVEL_LEGACY_DATA_DIRS", "").strip()
        if not raw:
            return []
        return [Path(item).expanduser() for item in raw.split(os.pathsep) if item.strip()]

    def _known_legacy_data_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        known_names = (
            "灵枢",
            "灵枢v1.2",
            "灵枢-v1.2",
            "SimpleAINovelApp",
        )
        for env_name in ("APPDATA", "LOCALAPPDATA"):
            root_text = os.environ.get(env_name, "").strip()
            if not root_text:
                continue
            root = Path(root_text).expanduser()
            for name in known_names:
                candidates.append(root / name / "data")
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    if "灵枢" in child.name or "SimpleAINovel" in child.name:
                        candidates.append(child / "data")
            except OSError:
                continue
        return candidates

    def _dedupe_legacy_data_dirs(self, legacy_dirs: list[Path]) -> list[Path]:
        result: list[Path] = []
        seen: set[Path] = set()
        for legacy_dir in legacy_dirs:
            try:
                resolved = Path(legacy_dir).expanduser().resolve()
            except OSError:
                continue
            if resolved == self.data_dir.resolve() or resolved in seen:
                continue
            seen.add(resolved)
            result.append(resolved)
        return result

    def _is_pre_v13_data_dir(self, data_dir: Path) -> bool:
        db_path = data_dir / "novels.db"
        if not db_path.exists():
            return False
        try:
            connection = sqlite3.connect(db_path)
            try:
                books_columns = self._table_columns(connection, "books")
                if not books_columns:
                    return False
                if "outline_data_json" not in books_columns or "world_data_json" not in books_columns:
                    return True
                character_columns = self._table_columns(connection, "characters")
                return bool(character_columns and "profile_data_json" not in character_columns)
            finally:
                connection.close()
        except sqlite3.Error:
            return False

    @staticmethod
    def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
        try:
            rows = connection.execute("PRAGMA table_info(" + LegacyMixin._sql_identifier(table_name) + ")").fetchall()
        except sqlite3.Error:
            return set()
        return {str(row[1]) for row in rows}

    @staticmethod
    def _sql_identifier(value: str) -> str:
        text = str(value or "")
        if not text or text[0].isdigit() or not all(char.isalnum() or char == "_" for char in text):
            raise ValueError(f"Unsafe SQL identifier: {text!r}")
        return '"' + text.replace('"', '""') + '"'

    def _data_dir_has_user_data(self, data_dir: Path) -> bool:
        if not data_dir.exists():
            return False
        for filename in ("novels.db", "ai_settings.json", "ui_settings.json"):
            if (data_dir / filename).exists():
                return True
        for dirname in ("media", "references", "exports", "rag_vectors", "ui"):
            directory = data_dir / dirname
            if directory.exists() and any(directory.iterdir()):
                return True
        return any(child.is_dir() and child.name.isdigit() for child in data_dir.iterdir())

    def _ensure_legacy_imports_table(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS legacy_imports (
                source_key TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_size INTEGER NOT NULL DEFAULT 0,
                source_mtime_ns INTEGER NOT NULL DEFAULT 0,
                book_count INTEGER NOT NULL DEFAULT 0,
                imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _legacy_source_signature(self, db_path: Path) -> tuple[str, int, int]:
        resolved = db_path.expanduser().resolve()
        stat = resolved.stat()
        material = f"{resolved}\0{stat.st_size}\0{stat.st_mtime_ns}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest(), int(stat.st_size), int(stat.st_mtime_ns)

    def _legacy_source_imported(self, source_key: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM legacy_imports WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        return row is not None

    def _import_legacy_data_dirs(self) -> None:
        if not self.legacy_data_dirs:
            return
        for legacy_dir in self.legacy_data_dirs:
            db_path = legacy_dir / "novels.db"
            if not db_path.exists():
                continue
            try:
                current_db = self.db_path.expanduser().resolve()
                source_db = db_path.expanduser().resolve()
            except OSError as exc:
                self.legacy_import_errors.append((legacy_dir, str(exc)))
                continue
            if source_db == current_db:
                continue
            try:
                source_key, source_size, source_mtime_ns = self._legacy_source_signature(source_db)
                if self._legacy_source_imported(source_key):
                    continue
                book_count = self._import_legacy_database(legacy_dir, source_db)
                self._copy_legacy_sidecar_files(legacy_dir)
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO legacy_imports
                        (source_key, source_path, source_size, source_mtime_ns, book_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (source_key, str(source_db), source_size, source_mtime_ns, book_count),
                )
                self.imported_legacy_data_dirs.append(legacy_dir.expanduser().resolve())
            except Exception as exc:  # noqa: BLE001
                self.legacy_import_errors.append((legacy_dir, str(exc)))

    def _copy_legacy_sidecar_files(self, legacy_dir: Path) -> None:
        for filename in ("ai_settings.json", "ui_settings.json"):
            source = legacy_dir / filename
            target = self.data_dir / filename
            if source.exists() and not target.exists():
                try:
                    shutil.copy2(source, target)
                except OSError as exc:
                    self.legacy_import_errors.append((source, str(exc)))

    def _import_legacy_database(self, legacy_dir: Path, source_db: Path) -> int:
        source = sqlite3.connect(source_db)
        source.row_factory = sqlite3.Row
        try:
            book_rows = self._legacy_rows(source, "books", ("id",))
            if not book_rows:
                return 0
            book_id_map: dict[int, int] = {}
            volume_id_map: dict[int, int] = {}
            chapter_id_map: dict[int, int] = {}
            character_id_map: dict[int, int] = {}

            # 批量导入优化：临时降低同步级别，使用事务批量提交
            self.connection.execute("PRAGMA synchronous = OFF")
            try:
                with self.connection:
                    for row in book_rows:
                        old_book_id = self._safe_int(self._legacy_value(row, "id"), 0)
                        if old_book_id <= 0:
                            continue
                        book_id_map[old_book_id] = self._insert_legacy_book(row)

                    for row in self._legacy_rows(source, "volumes", ("book_id", "sort_order", "id")):
                        old_book_id = self._safe_int(self._legacy_value(row, "book_id"), 0)
                        new_book_id = book_id_map.get(old_book_id)
                        if not new_book_id:
                            continue
                        old_volume_id = self._safe_int(self._legacy_value(row, "id"), 0)
                        new_volume_id = self._insert_legacy_volume(new_book_id, row)
                        if old_volume_id > 0:
                            volume_id_map[old_volume_id] = new_volume_id

                    for row in self._legacy_rows(source, "chapters", ("book_id", "volume_id", "sort_order", "id")):
                        old_book_id = self._safe_int(self._legacy_value(row, "book_id"), 0)
                        new_book_id = book_id_map.get(old_book_id)
                        if not new_book_id:
                            continue
                        old_volume_id = self._safe_int(self._legacy_value(row, "volume_id"), 0)
                        new_volume_id = volume_id_map.get(old_volume_id) if old_volume_id > 0 else None
                        old_chapter_id = self._safe_int(self._legacy_value(row, "id"), 0)
                        new_chapter_id = self._insert_legacy_chapter(new_book_id, new_volume_id, row)
                        if old_chapter_id > 0:
                            chapter_id_map[old_chapter_id] = new_chapter_id

                    self._import_legacy_world_entries(source, book_id_map)
                    self._refresh_imported_book_outlines(book_id_map.values())

                    for row in self._legacy_rows(source, "characters", ("book_id", "id")):
                        old_book_id = self._safe_int(self._legacy_value(row, "book_id"), 0)
                        new_book_id = book_id_map.get(old_book_id)
                        if not new_book_id:
                            continue
                        old_character_id = self._safe_int(self._legacy_value(row, "id"), 0)
                        new_character_id = self._insert_legacy_character(new_book_id, row)
                        if old_character_id > 0:
                            character_id_map[old_character_id] = new_character_id

                    self._import_legacy_relationships(source, book_id_map, character_id_map)
                    self._import_legacy_chapter_tags(source, chapter_id_map)
                    self._import_legacy_chapter_events(source, book_id_map, chapter_id_map)
            finally:
                self.connection.execute("PRAGMA synchronous = NORMAL")
            return len(book_id_map)
        finally:
            source.close()

    def _legacy_rows(self, source: sqlite3.Connection, table_name: str, order_columns: tuple[str, ...]) -> list[sqlite3.Row]:
        columns = self._table_columns(source, table_name)
        if not columns:
            return []
        order = [column for column in order_columns if column in columns]
        table_sql = self._sql_identifier(table_name)
        order_sql = " ORDER BY " + ", ".join(self._sql_identifier(column) for column in order) if order else ""
        return list(source.execute("SELECT * FROM " + table_sql + order_sql).fetchall())

    @staticmethod
    def _legacy_value(row: sqlite3.Row, key: str, default: Any = "") -> Any:
        return row.get(key, default)

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _insert_legacy_book(self, row: sqlite3.Row) -> int:
        title = str(self._legacy_value(row, "title", "") or "").strip() or "旧版书籍"
        volume_specs: list[dict[str, Any]] = []
        outline_data = self._book_outline_json_to_data(str(self._legacy_value(row, "outline_data_json", "") or ""), title, volume_specs)
        if outline_data is None:
            outline_data = book_outline_markdown_to_form(str(self._legacy_value(row, "outline_text", "") or ""), title, volume_specs)
        outline_text = book_outline_form_to_markdown(outline_data, title, volume_specs)

        world_data = self._world_form_json_to_data(str(self._legacy_value(row, "world_data_json", "") or ""))
        if world_data is None:
            world_text_source = str(self._legacy_value(row, "world_text", "") or "")
            world_data = world_markdown_to_form(world_text_source) if world_text_source.strip() else world_form_defaults()
        world_text = world_form_to_markdown(world_data)
        cursor = self.connection.execute(
            """
            INSERT INTO books (title, outline_text, outline_data_json, world_text, world_data_json, cover_image_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                outline_text,
                self._book_outline_data_to_json(outline_data, title, volume_specs),
                world_text,
                self._world_form_data_to_json(world_data),
                "",
            ),
        )
        return int(cursor.lastrowid)

    def _insert_legacy_volume(self, book_id: int, row: sqlite3.Row) -> int:
        title = str(self._legacy_value(row, "title", "") or "").strip() or "旧版分卷"
        sort_order = self._safe_int(self._legacy_value(row, "sort_order"), self._next_volume_sort_order(book_id))
        cursor = self.connection.execute(
            """
            INSERT INTO volumes (book_id, title, outline_text, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (book_id, title, str(self._legacy_value(row, "outline_text", "") or ""), sort_order),
        )
        return int(cursor.lastrowid)

    def _insert_legacy_chapter(self, book_id: int, volume_id: int | None, row: sqlite3.Row) -> int:
        title = str(self._legacy_value(row, "title", "") or "").strip() or "旧版章节"
        sort_order = self._safe_int(self._legacy_value(row, "sort_order"), self._next_chapter_sort_order(book_id, volume_id))
        cursor = self.connection.execute(
            """
            INSERT INTO chapters (
                book_id, volume_id, title, outline, content, summary_text,
                ai_probability, ai_probability_level, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                volume_id,
                title,
                str(self._legacy_value(row, "outline", "") or ""),
                str(self._legacy_value(row, "content", "") or ""),
                str(self._legacy_value(row, "summary_text", "") or ""),
                self._safe_int(self._legacy_value(row, "ai_probability"), 0),
                str(self._legacy_value(row, "ai_probability_level", "none") or "none"),
                sort_order,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_legacy_character(self, book_id: int, row: sqlite3.Row) -> int:
        name = str(self._legacy_value(row, "name", "") or "").strip() or "旧版人物"
        role = str(self._legacy_value(row, "role", "") or "")
        profile_data = self._character_profile_json_to_data(str(self._legacy_value(row, "profile_data_json", "") or ""), name, role)
        if profile_data is None:
            profile_text, profile_data_json = self._character_profile_payload_from_text(
                str(self._legacy_value(row, "profile_text", "") or ""),
                name,
                role,
            )
        else:
            profile_text = character_profile_form_to_markdown(profile_data, name, role)
            profile_data_json = self._character_profile_data_to_json(profile_data, name, role)
        cursor = self.connection.execute(
            """
            INSERT INTO characters (
                book_id, name, role, profile_text, profile_data_json,
                image_path, graph_x, graph_y, pinned
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                name,
                role,
                profile_text,
                profile_data_json,
                "",
                self._safe_float(self._legacy_value(row, "graph_x"), 0.0),
                self._safe_float(self._legacy_value(row, "graph_y"), 0.0),
                self._safe_int(self._legacy_value(row, "pinned"), 0),
            ),
        )
        return int(cursor.lastrowid)

    def _import_legacy_world_entries(self, source: sqlite3.Connection, book_id_map: dict[int, int]) -> None:
        grouped: dict[int, list[str]] = {}
        for row in self._legacy_rows(source, "world_entries", ("book_id", "id")):
            old_book_id = self._safe_int(self._legacy_value(row, "book_id"), 0)
            new_book_id = book_id_map.get(old_book_id)
            if not new_book_id:
                continue
            name = str(self._legacy_value(row, "name", "") or "").strip() or "旧版世界观"
            category = str(self._legacy_value(row, "category", "") or "").strip()
            content = str(self._legacy_value(row, "content_text", "") or "").strip()
            if not content:
                continue
            header = f"### {name}"
            if category:
                header += f"（{category}）"
            grouped.setdefault(new_book_id, []).append(f"{header}\n\n{content}")
        for book_id, chunks in grouped.items():
            book = self.get_book(book_id)
            if not book:
                continue
            data = self._world_form_json_to_data(str(book["world_data_json"] or "")) or world_form_defaults()
            data = merge_world_supplement(data, "\n\n".join(chunks), supplement_title="旧版世界观")
            self.connection.execute(
                "UPDATE books SET world_text = ?, world_data_json = ? WHERE id = ?",
                (world_form_to_markdown(data), self._world_form_data_to_json(data), book_id),
            )

    def _refresh_imported_book_outlines(self, book_ids: Any) -> None:
        for book_id in book_ids:
            self._refresh_book_outline_volume_plans(int(book_id))

    def _import_legacy_relationships(
        self,
        source: sqlite3.Connection,
        book_id_map: dict[int, int],
        character_id_map: dict[int, int],
    ) -> None:
        rows = self._legacy_rows(source, "character_relationships", ("book_id", "id"))
        batch: list[tuple[int, int, int, str, str]] = []
        for row in rows:
            old_book_id = self._safe_int(self._legacy_value(row, "book_id"), 0)
            source_old_id = self._safe_int(self._legacy_value(row, "source_character_id"), 0)
            target_old_id = self._safe_int(self._legacy_value(row, "target_character_id"), 0)
            new_book_id = book_id_map.get(old_book_id)
            source_new_id = character_id_map.get(source_old_id)
            target_new_id = character_id_map.get(target_old_id)
            if not new_book_id or not source_new_id or not target_new_id:
                continue
            batch.append((
                new_book_id,
                source_new_id,
                target_new_id,
                str(self._legacy_value(row, "relationship_type", "") or ""),
                str(self._legacy_value(row, "description", "") or ""),
            ))
        if batch:
            self.connection.executemany(
                """
                INSERT INTO character_relationships (
                    book_id, source_character_id, target_character_id, relationship_type, description
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                batch,
            )

    def _import_legacy_chapter_tags(self, source: sqlite3.Connection, chapter_id_map: dict[int, int]) -> None:
        rows = self._legacy_rows(source, "chapter_tags", ("chapter_id", "tag"))
        batch: list[tuple[int, str]] = []
        for row in rows:
            old_chapter_id = self._safe_int(self._legacy_value(row, "chapter_id"), 0)
            new_chapter_id = chapter_id_map.get(old_chapter_id)
            tag = str(self._legacy_value(row, "tag", "") or "").strip()
            if not new_chapter_id or not tag:
                continue
            batch.append((new_chapter_id, tag))
        if batch:
            self.connection.executemany(
                "INSERT OR IGNORE INTO chapter_tags (chapter_id, tag) VALUES (?, ?)",
                batch,
            )

    def _import_legacy_chapter_events(
        self,
        source: sqlite3.Connection,
        book_id_map: dict[int, int],
        chapter_id_map: dict[int, int],
    ) -> None:
        rows = self._legacy_rows(source, "chapter_events", ("book_id", "chapter_id", "sort_order", "id"))
        batch: list[tuple[int, int, str, str, int]] = []
        for row in rows:
            old_book_id = self._safe_int(self._legacy_value(row, "book_id"), 0)
            old_chapter_id = self._safe_int(self._legacy_value(row, "chapter_id"), 0)
            new_book_id = book_id_map.get(old_book_id)
            new_chapter_id = chapter_id_map.get(old_chapter_id)
            label = str(self._legacy_value(row, "label", "") or "").strip()
            if not new_book_id or not new_chapter_id or not label:
                continue
            batch.append((
                new_book_id,
                new_chapter_id,
                label,
                str(self._legacy_value(row, "description", "") or ""),
                self._safe_int(self._legacy_value(row, "sort_order"), 0),
            ))
        if batch:
            self.connection.executemany(
                """
                INSERT INTO chapter_events (book_id, chapter_id, label, description, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                batch,
            )
