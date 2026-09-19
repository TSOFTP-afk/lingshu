from __future__ import annotations

from novel_app.db.common import *


class CharactersMixin:
    def list_characters(self, book_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT id, name, role, profile_text, profile_data_json, image_path, graph_x, graph_y, pinned
            FROM characters
            WHERE book_id = ?
            ORDER BY pinned DESC, id ASC
            """,
            (book_id,),
        )
        return list(cursor.fetchall())

    def create_character(self, book_id: int, name: str) -> int:
        profile_data = character_profile_form_defaults(name, "")
        profile_text = character_profile_form_to_markdown(profile_data, name, "")
        cursor = self.connection.execute(
            """
            INSERT INTO characters (book_id, name, profile_text, profile_data_json)
            VALUES (?, ?, ?, ?)
            """,
            (book_id, name, profile_text, self._character_profile_data_to_json(profile_data, name, "")),
        )
        self.connection.commit()
        character_id = int(cursor.lastrowid)
        # 自动初始化空状态机（INSERT OR IGNORE 幂等，状态机成为数据源）
        self.create_state_machine(character_id, {})
        return character_id

    def get_character(self, character_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT id, book_id, name, role, profile_text, profile_data_json, image_path, graph_x, graph_y, pinned
            FROM characters
            WHERE id = ?
            """,
            (character_id,),
        )
        return cursor.fetchone()

    def update_character(
        self,
        character_id: int,
        name: str,
        role: str,
        profile_text: str,
        image_path: str | None = None,
    ) -> None:
        existing = self.get_character(character_id)
        existing_text = str(existing["profile_text"] or "") if existing is not None else ""
        incoming_text = str(profile_text or "")
        if existing is not None and incoming_text.strip() == existing_text.strip():
            profile_data = character_profile_form_defaults(name, role)
            profile_text = character_profile_form_to_markdown(profile_data, name, role)
            profile_data_json = self._character_profile_data_to_json(profile_data, name, role)
        else:
            profile_text, profile_data_json = self._character_profile_payload_from_text(incoming_text, name, role)
        pinned = 1 if role in ("男主", "女主") else 0
        if image_path is None:
            self.connection.execute(
                "UPDATE characters SET name = ?, role = ?, profile_text = ?, profile_data_json = ?, pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, role, profile_text, profile_data_json, pinned, character_id),
            )
        else:
            self.connection.execute(
                "UPDATE characters SET name = ?, role = ?, profile_text = ?, profile_data_json = ?, image_path = ?, pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, role, profile_text, profile_data_json, image_path, pinned, character_id),
            )
        self.connection.commit()

    def update_character_form(
        self,
        character_id: int,
        name: str,
        role: str,
        profile_data: dict[str, Any],
        image_path: str | None = None,
    ) -> None:
        """更新人物表单。含状态机字段时代理到状态机更新（状态机为数据源），
        否则保留旧表单编辑链路。基础字段（name/role/image_path/pinned）始终更新到 characters 表。"""
        from novel_app.structured_templates.state_machine_schema import STATE_MACHINE_FIELD_IDS

        data = profile_data or {}
        sm_fields = {k: v for k, v in data.items() if k in STATE_MACHINE_FIELD_IDS}

        if sm_fields:
            # 含状态机字段：代理写入状态机，跳过旧 normalize→markdown→json 链路
            self.update_state_machine(character_id, sm_fields)
            # 同步静态属性到 profile_data_json，避免兼容表单显示空白（同事务，由下方 commit 统一提交）
            self._sync_legacy_profile_static_attrs(character_id, sm_fields)
            pinned = 1 if role in ("男主", "女主") else 0
            if image_path is None:
                self.connection.execute(
                    "UPDATE characters SET name = ?, role = ?, pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, role, pinned, character_id),
                )
            else:
                self.connection.execute(
                    "UPDATE characters SET name = ?, role = ?, image_path = ?, pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, role, image_path, pinned, character_id),
                )
            self.connection.commit()
            return

        # 不含状态机字段：保留原旧表单编辑逻辑
        normalized = normalize_character_profile_form(profile_data, name, role)
        profile_text = character_profile_form_to_markdown(normalized, name, role)
        profile_data_json = self._character_profile_data_to_json(normalized, name, role)
        pinned = 1 if role in ("男主", "女主") else 0
        if image_path is None:
            self.connection.execute(
                "UPDATE characters SET name = ?, role = ?, profile_text = ?, profile_data_json = ?, pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, role, profile_text, profile_data_json, pinned, character_id),
            )
        else:
            self.connection.execute(
                "UPDATE characters SET name = ?, role = ?, profile_text = ?, profile_data_json = ?, image_path = ?, pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, role, profile_text, profile_data_json, image_path, pinned, character_id),
            )
        self.connection.commit()

    def _generate_legacy_form_from_state_machine(self, character_id: int) -> dict[str, Any] | None:
        """从状态机运行态快照生成旧 PROTAGONIST/SUPPORTING 表单格式。

        映射规则（spec）：
        - desire_fear_table ← desire_text + desire_fear_mirror + desire_extreme + desire_origin（主角 3.3）
        - morality_table ← belief_core + belief_taboo（主角 3.6）
        - relationship_table ← desire_anchor（主角 3.7）
        - motivation_table ← desire_text + desire_fear_mirror + desire_anchor（配角 4.4）
        - relationship_arc_table ← desire_anchor（配角 4.6）
        - supplements ← 保留（从旧 profile_data_json 读取，V3 分析摘要仍挂此处）

        以旧 profile_data_json 为基础（保留非映射字段），再用状态机覆盖三轴对应 multiline 字段。
        状态机不存在时返回 None，由调用方回退到旧 profile_data_json 解析（向后兼容）。
        """
        char = self.get_character(character_id)
        if char is None:
            return None
        name = str(char["name"] or "")
        role = str(char["role"] or "")

        sm = self.get_state_machine(character_id)
        if sm is None:
            return None  # 状态机不存在，由调用方回退到旧逻辑

        sm_dict = dict(sm)

        def sm_text(key: str) -> str:
            return str(sm_dict.get(key, "") or "")

        # 以旧 profile_data_json 为基础（保留非映射字段与 supplements），无则用默认表单
        old_data = self._character_profile_json_to_data(
            str(char["profile_data_json"] or ""), name, role
        )
        if old_data is None:
            old_data = character_profile_form_defaults(name, role)
        # 强制以当前 role 推导 schema（旧 JSON 内嵌的 schema 可能已过期，如 role 变更后未同步）
        old_data.pop("schema", None)
        form = normalize_character_profile_form(old_data, name, role)
        fields = form.get("fields", {})

        # 静态属性字段反向映射（仅当状态机字段非空时覆盖旧表单字段值）
        static_attr_fields = [
            ("alias", "alias"),
            ("age", "age"),
            ("gender", "gender"),
            ("appearance_keywords", "appearance_keywords"),
            ("signature_feature", "signature_feature"),
            ("identity_occupation", "identity_occupation"),
        ]
        for sm_field, form_field in static_attr_fields:
            sm_value = sm_text(sm_field).strip()
            if sm_value and form_field in fields:
                fields[form_field]["value"] = sm_value

        desire_text = sm_text("desire_text")
        desire_fear_mirror = sm_text("desire_fear_mirror")
        desire_extreme = sm_text("desire_extreme")
        desire_origin = sm_text("desire_origin")
        desire_anchor = sm_text("desire_anchor")
        belief_core = sm_text("belief_core")
        belief_taboo = sm_text("belief_taboo")

        # 主角 3.3 核心欲望与恐惧 ← desire_text + desire_fear_mirror + desire_extreme + desire_origin
        if "desire_fear_table" in fields and (
            desire_text or desire_fear_mirror or desire_extreme or desire_origin
        ):
            fields["desire_fear_table"]["value"] = "\n".join([
                f"公开目标（主角对外宣称的目标）：{desire_text}",
                f"隐藏欲望（主角内心真正渴望但不愿/不敢承认的）：{desire_extreme}",
                f"核心恐惧（主角最害怕发生的事情）：{desire_fear_mirror}",
                "核心执念（放不下的东西/人/想法）：",
                f"底层驱动力（什么推动主角度过最困难的时刻）：{desire_origin}",
            ])

        # 主角 3.6 道德边界 ← belief_core + belief_taboo
        if "morality_table" in fields and (belief_core or belief_taboo):
            bottom = belief_core
            if belief_taboo:
                bottom = f"{belief_core}（不可触碰：{belief_taboo}）" if belief_core else belief_taboo
            fields["morality_table"]["value"] = "\n".join([
                f"道德底线（绝对不能做的事）：{bottom}",
                "可以被突破的底线（在什么情况下会破例）：",
                "对待敌人的态度：",
                "对待陌生人的态度：",
                "对待朋友/伙伴的态度：",
                "对待背叛者的态度：",
                "是否愿意为大局牺牲少数人：",
            ])

        # 主角 3.7 关系网络 ← desire_anchor
        if "relationship_table" in fields and desire_anchor:
            fields["relationship_table"]["value"] = "\n".join([
                "主角与家人的关系：",
                f"最重要的朋友/伙伴：{desire_anchor}",
                f"最信任的人：{desire_anchor}",
                "会背叛主角的人：",
                "主角心中不可触碰的人（软肋）：",
            ])

        # 配角 4.4 动机与欲望 ← desire_text + desire_fear_mirror + desire_anchor
        if "motivation_table" in fields and (
            desire_text or desire_fear_mirror or desire_anchor
        ):
            fields["motivation_table"]["value"] = "\n".join([
                f"个人目标：{desire_text}",
                "与主角目标一致/冲突的地方：",
                f"为什么跟随/对抗主角：{desire_anchor}",
                f"深层次的欲望与恐惧：{desire_fear_mirror}",
            ])

        # 配角 4.6 与主角的关系线 ← desire_anchor
        if "relationship_arc_table" in fields and desire_anchor:
            fields["relationship_arc_table"]["value"] = "\n".join([
                "初次相遇场景：",
                f"关系起点（敌意/陌生/友善/利用）：{desire_anchor}",
                "关系转折事件：",
                "关系高潮时刻：",
                "当前关系状态：",
                "最终关系走向：",
            ])

        return form

    def _sync_legacy_profile_from_state_machine(self, character_id: int) -> None:
        """从状态机重新生成 profile_text/profile_data_json 兼容视图并写入 characters 表。"""
        char = self.get_character(character_id)
        if char is None:
            return
        name = str(char["name"] or "")
        role = str(char["role"] or "")
        form = self._generate_legacy_form_from_state_machine(character_id)
        if form is None:
            return
        from novel_app.structured_templates.base import (
            character_profile_form_to_markdown,
            character_profile_schema_key,
            normalize_character_profile_form,
        )
        schema_key = character_profile_schema_key(role, form.get("schema", ""))
        form = normalize_character_profile_form(form, name, role, schema_key)
        profile_text = character_profile_form_to_markdown(form, name, role)
        profile_json = self._character_profile_data_to_json(form, name, role)
        self.connection.execute(
            "UPDATE characters SET profile_text = ?, profile_data_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (profile_text, profile_json, character_id),
        )
        self.connection.commit()

    def _sync_legacy_profile_static_attrs(self, character_id: int, sm_fields: dict) -> None:
        """将状态机静态属性字段同步到 characters.profile_data_json，避免兼容表单显示空白。

        仅同步非空值，避免空覆盖。读取当前 profile_data_json，更新对应字段后写回。
        注意：本方法不自行 commit，由调用方（update_character_form）在同事务内统一 commit。
        profile_data_json 结构：{"version":..., "schema":..., "fields": {"alias": {"value":...}, ...}, "supplements":[]}
        """
        static_attr_field_names = {
            "alias", "age", "gender", "appearance_keywords",
            "signature_feature", "identity_occupation",
        }
        sync_fields = {
            k: v for k, v in (sm_fields or {}).items()
            if k in static_attr_field_names and str(v or "").strip()
        }
        if not sync_fields:
            return
        # 读取当前 profile_data_json
        row = self.connection.execute(
            "SELECT profile_data_json FROM characters WHERE id = ?",
            (character_id,),
        ).fetchone()
        if not row:
            return
        try:
            profile_data = json.loads(row[0]) if row[0] else {}
        except (json.JSONDecodeError, TypeError):
            profile_data = {}
        if not isinstance(profile_data, dict):
            return
        # fields 是 dict 结构：{"alias": {"value": "..."}, ...}
        fields_dict = profile_data.get("fields", {})
        if not isinstance(fields_dict, dict):
            return
        for field_id, value in sync_fields.items():
            target = fields_dict.get(field_id)
            if isinstance(target, dict):
                target["value"] = str(value).strip()
        # 重新序列化写回（不 commit，由调用方统一提交）
        self.connection.execute(
            "UPDATE characters SET profile_data_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(profile_data, ensure_ascii=False), character_id),
        )

    def get_character_profile_form(self, character_id: int) -> dict[str, Any]:
        """读取人物表单。优先从状态机生成，回退到旧 profile_data_json 解析。"""
        # 优先从状态机生成
        form = self._generate_legacy_form_from_state_machine(character_id)
        if form is not None:
            return form
        # 回退：旧逻辑（解析 profile_data_json）
        character = self.get_character(character_id)
        if not character:
            return character_profile_form_defaults("", "")
        name = str(character["name"] or "")
        role = str(character["role"] or "")
        data = self._character_profile_json_to_data(str(character["profile_data_json"] or ""), name, role)
        if data is None:
            data = character_profile_form_defaults(name, role)
        return normalize_character_profile_form(data, name, role)

    def update_character_image(self, character_id: int, image_path: str) -> None:
        self.connection.execute(
            """
            UPDATE characters
            SET image_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (image_path, character_id),
        )
        self.connection.commit()

    def update_character_position(self, character_id: int, graph_x: float, graph_y: float) -> None:
        self.connection.execute(
            """
            UPDATE characters
            SET graph_x = ?, graph_y = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (float(graph_x), float(graph_y), character_id),
        )
        self.connection.commit()

    def delete_character(self, character_id: int) -> None:
        self.connection.execute(
            "DELETE FROM characters WHERE id = ?",
            (character_id,),
        )
        self.connection.commit()

    def list_relationships(self, book_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                r.id,
                r.book_id,
                r.source_character_id,
                r.target_character_id,
                r.relationship_type,
                r.description,
                source.name AS source_name,
                target.name AS target_name
            FROM character_relationships AS r
            JOIN characters AS source ON source.id = r.source_character_id
            JOIN characters AS target ON target.id = r.target_character_id
            WHERE r.book_id = ?
            ORDER BY r.id ASC
            """,
            (book_id,),
        )
        return list(cursor.fetchall())

    def get_relationship(self, relationship_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT
                r.id,
                r.book_id,
                r.source_character_id,
                r.target_character_id,
                r.relationship_type,
                r.description,
                source.name AS source_name,
                target.name AS target_name
            FROM character_relationships AS r
            JOIN characters AS source ON source.id = r.source_character_id
            JOIN characters AS target ON target.id = r.target_character_id
            WHERE r.id = ?
            """,
            (relationship_id,),
        )
        return cursor.fetchone()

    def create_relationship(
        self,
        book_id: int,
        source_character_id: int,
        target_character_id: int,
        relationship_type: str = "",
        description: str = "",
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO character_relationships (
                book_id,
                source_character_id,
                target_character_id,
                relationship_type,
                description
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (book_id, source_character_id, target_character_id, relationship_type, description),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def create_chapter_after(
        self,
        after_chapter_id: int,
        title: str,
        outline: str = "",
        content: str = "",
    ) -> int:
        current = self.connection.execute(
            """
            SELECT id, book_id, volume_id, sort_order
            FROM chapters
            WHERE id = ?
            """,
            (after_chapter_id,),
        ).fetchone()
        if not current:
            raise ValueError("Chapter not found.")
        book_id = int(current["book_id"])
        volume_id = current["volume_id"]
        sort_order = int(current["sort_order"])
        clause, params = self._build_volume_clause(volume_id)
        with self.connection:
            self.connection.execute(
                f"""
                UPDATE chapters
                SET sort_order = sort_order + 1, updated_at = CURRENT_TIMESTAMP
                WHERE book_id = ? AND {clause} AND sort_order > ?
                """,
                (book_id, *params, sort_order),
            )
            cursor = self.connection.execute(
                """
                INSERT INTO chapters (book_id, volume_id, title, outline, content, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (book_id, volume_id, title, outline, content, sort_order + 1),
            )
            new_id = int(cursor.lastrowid)
            self._normalize_chapter_order(book_id, volume_id)
        return new_id

    def replace_book_relationships(self, book_id: int, relationships: list[dict[str, Any]]) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM character_relationships WHERE book_id = ?",
                (book_id,),
            )
            for item in relationships:
                source_id = int(item.get("source_character_id", 0) or 0)
                target_id = int(item.get("target_character_id", 0) or 0)
                if not source_id or not target_id or source_id == target_id:
                    continue
                self.connection.execute(
                    """
                    INSERT INTO character_relationships (
                        book_id,
                        source_character_id,
                        target_character_id,
                        relationship_type,
                        description
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        source_id,
                        target_id,
                        str(item.get("relationship_type", "") or "关联").strip(),
                        str(item.get("description", "") or "").strip(),
                    ),
                )

    def update_relationship(
        self,
        relationship_id: int,
        relationship_type: str,
        description: str = "",
    ) -> None:
        self.connection.execute(
            """
            UPDATE character_relationships
            SET relationship_type = ?, description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (relationship_type, description, relationship_id),
        )
        self.connection.commit()

    def delete_relationship(self, relationship_id: int) -> None:
        self.connection.execute(
            "DELETE FROM character_relationships WHERE id = ?",
            (relationship_id,),
        )
        self.connection.commit()

    def list_relationships_by_character(self, character_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                r.id,
                r.book_id,
                r.source_character_id,
                r.target_character_id,
                r.relationship_type,
                r.description,
                source.name AS source_name,
                target.name AS target_name
            FROM character_relationships AS r
            JOIN characters AS source ON source.id = r.source_character_id
            JOIN characters AS target ON target.id = r.target_character_id
            WHERE r.source_character_id = ? OR r.target_character_id = ?
            ORDER BY r.id ASC
            """,
            (character_id, character_id),
        )
        return list(cursor.fetchall())

    def list_world_entries(self, book_id: int) -> list[Any]:
        rows = self.connection.execute(
            """
            SELECT id, book_id, name, category, content_text
            FROM world_entries
            WHERE book_id = ?
            ORDER BY id ASC
            """,
            (book_id,),
        ).fetchall()
        entries = [dict(row) for row in rows]
        book = self.get_book(book_id)
        if book:
            content = str(book["world_text"] or "").strip()
            if not content:
                content = world_form_to_markdown(self.get_book_world_form(book_id))
            if content.strip():
                entries.insert(0, {
                    "id": 0,
                    "book_id": book_id,
                    "name": "世界观总设定",
                    "category": "总设定",
                    "content_text": content,
                })
        return entries

    def create_world_entry(self, book_id: int, name: str, category: str = "设定") -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO world_entries (book_id, name, category, content_text)
            VALUES (?, ?, ?, ?)
            """,
            (book_id, name, category, world_entry_template(name, category)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def get_world_entry(self, entry_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT id, book_id, name, category, content_text
            FROM world_entries
            WHERE id = ?
            """,
            (entry_id,),
        )
        return cursor.fetchone()

    def update_world_entry(
        self,
        entry_id: int,
        name: str,
        category: str,
        content_text: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE world_entries
            SET name = ?, category = ?, content_text = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, category, content_text, entry_id),
        )
        self.connection.commit()

    def delete_world_entry(self, entry_id: int) -> None:
        self.connection.execute(
            "DELETE FROM world_entries WHERE id = ?",
            (entry_id,),
        )
        self.connection.commit()

    def count_book_words(self, book_id: int) -> int:
        rows = self.connection.execute(
            "SELECT content FROM chapters WHERE book_id = ?",
            (book_id,),
        ).fetchall()
        return sum(len(str(row["content"] or "")) for row in rows)

    def count_volume_words(self, volume_id: int) -> int:
        rows = self.connection.execute(
            "SELECT content FROM chapters WHERE volume_id = ?",
            (volume_id,),
        ).fetchall()
        return sum(len(str(row["content"] or "")) for row in rows)

    def get_book_export_data(self, book_id: int) -> dict[str, Any]:
        book = self.get_book(book_id)
        if not book:
            raise ValueError("Book not found.")

        volumes = self.list_volumes(book_id)
        chapters = self.connection.execute(
            """
            SELECT
                c.id,
                c.title,
                c.outline,
                c.content,
                c.summary_text,
                c.sort_order,
                c.volume_id,
                COALESCE(v.title, '未分卷') AS volume_title,
                COALESCE(v.sort_order, 2147483647) AS volume_sort_order
            FROM chapters AS c
            LEFT JOIN volumes AS v ON v.id = c.volume_id
            WHERE c.book_id = ?
            ORDER BY
                CASE WHEN c.volume_id IS NULL THEN 1 ELSE 0 END ASC,
                COALESCE(v.sort_order, 2147483647) ASC,
                c.sort_order ASC,
                c.id ASC
            """,
            (book_id,),
        ).fetchall()

        characters = self.connection.execute(
            """
            SELECT name, role, profile_text
            FROM characters
            WHERE book_id = ?
            ORDER BY id ASC
            """,
            (book_id,),
        ).fetchall()

        return {
            "book": dict(book),
            "volumes": [dict(item) for item in volumes],
            "chapters": [dict(item) for item in chapters],
            "characters": [dict(item) for item in characters],
            "world_entries": [dict(item) for item in self.list_world_entries(book_id)],
            "unassigned_chapter_count": self.count_unassigned_chapters(book_id),
        }

    def list_name_shortcuts(self, book_id: int) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT id, book_id, key_seq, character_name FROM name_shortcuts WHERE book_id = ? ORDER BY id ASC",
            (book_id,),
        ).fetchall()

    def add_name_shortcut(self, book_id: int, key_seq: str, character_name: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO name_shortcuts (book_id, key_seq, character_name) VALUES (?, ?, ?)",
            (book_id, key_seq, character_name),
        )
        self.connection.commit()
        return cursor.lastrowid or 0

    def delete_name_shortcut(self, shortcut_id: int) -> None:
        self.connection.execute("DELETE FROM name_shortcuts WHERE id = ?", (shortcut_id,))
        self.connection.commit()

    def get_node_styles(self, book_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, book_id, name, display_name, background, border_color,
                   border_width, text_color, icon_type, is_preset
            FROM node_styles
            WHERE book_id = ?
            ORDER BY is_preset DESC, name
            """,
            (book_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_relationship_types(self, book_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, book_id, name, display_name, color, line_style,
                   arrow_type, is_directed, is_preset
            FROM relationship_types
            WHERE book_id = ?
            ORDER BY is_preset DESC, name
            """,
            (book_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_character_node_style(self, character_id: int, style_id: int) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO character_node_styles (character_id, style_id) VALUES (?, ?)",
            (character_id, style_id),
        )
        self.connection.commit()

    def get_character_node_style(self, character_id: int) -> int | None:
        row = self.connection.execute(
            "SELECT style_id FROM character_node_styles WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        return int(row["style_id"]) if row else None

    def update_relationship_type_info(
        self, relationship_id: int, relationship_type_id: int | None, description: str = ""
    ) -> None:
        self.connection.execute(
            """
            UPDATE character_relationships
            SET relationship_type_id = ?, description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (relationship_type_id, description, relationship_id),
        )
        self.connection.commit()

    def initialize_book_star_graph_defaults(self, book_id: int) -> None:
        for style in PRESET_NODE_STYLES:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO node_styles
                (book_id, name, display_name, background, border_color, border_width, text_color, icon_type, is_preset)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    book_id,
                    style.name,
                    style.display_name,
                    style.background,
                    style.border_color,
                    style.border_width,
                    style.text_color,
                    style.icon_type,
                ),
            )

        for rtype in PRESET_RELATIONSHIP_TYPES:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO relationship_types
                (book_id, name, display_name, color, line_style, arrow_type, is_directed, is_preset)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    book_id,
                    rtype.name,
                    rtype.display_name,
                    rtype.color,
                    rtype.line_style,
                    rtype.arrow_type,
                    1 if rtype.is_directed else 0,
                ),
            )
        self.connection.commit()

    def create_custom_node_style(
        self,
        book_id: int,
        name: str,
        display_name: str,
        background: str,
        border_color: str,
        border_width: float,
        text_color: str,
        icon_type: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO node_styles
            (book_id, name, display_name, background, border_color, border_width, text_color, icon_type, is_preset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                book_id,
                name,
                display_name,
                background,
                border_color,
                border_width,
                text_color,
                icon_type,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def create_custom_relationship_type(
        self,
        book_id: int,
        name: str,
        display_name: str,
        color: str,
        line_style: str,
        arrow_type: str,
        is_directed: bool,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO relationship_types
            (book_id, name, display_name, color, line_style, arrow_type, is_directed, is_preset)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                book_id,
                name,
                display_name,
                color,
                line_style,
                arrow_type,
                1 if is_directed else 0,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)
