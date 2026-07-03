from __future__ import annotations

from novel_app.db.common import *


class StructuredMixin:
    def _book_outline_volume_specs(self, book_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, title, sort_order
            FROM volumes
            WHERE book_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (book_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _book_outline_json_to_data(
        self,
        raw_json: str,
        title: str,
        volume_specs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        raw_json = str(raw_json or "").strip()
        if not raw_json:
            return None
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return normalize_book_outline_form(payload, title, volume_specs)

    def _book_outline_data_to_json(
        self,
        data: dict[str, Any] | None,
        title: str,
        volume_specs: list[dict[str, Any]] | None = None,
    ) -> str:
        normalized = normalize_book_outline_form(data, title, volume_specs)
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))

    def _book_outline_payload_from_text(
        self,
        outline_text: str,
        title: str,
        volume_specs: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str]:
        data = book_outline_markdown_to_form(outline_text, title, volume_specs)
        return str(outline_text or ""), self._book_outline_data_to_json(data, title, volume_specs)

    def _refresh_book_outline_volume_plans(self, book_id: int) -> None:
        book = self.get_book(book_id)
        if not book:
            return
        title = str(book["title"] or "")
        volume_specs = self._book_outline_volume_specs(book_id)
        data = self._book_outline_json_to_data(str(book["outline_data_json"] or ""), title, volume_specs)
        if data is None:
            data = book_outline_markdown_to_form(str(book["outline_text"] or ""), title, volume_specs)
        markdown = book_outline_form_to_markdown(data, title, volume_specs)
        self.connection.execute(
            """
            UPDATE books
            SET outline_text = ?, outline_data_json = ?
            WHERE id = ?
            """,
            (markdown, self._book_outline_data_to_json(data, title, volume_specs), book_id),
        )

    def _world_form_json_to_data(self, raw_json: str) -> dict[str, Any] | None:
        raw_json = str(raw_json or "").strip()
        if not raw_json:
            return None
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return normalize_world_form(payload)

    def _world_form_data_to_json(self, data: dict[str, Any] | None) -> str:
        return json.dumps(normalize_world_form(data), ensure_ascii=False, separators=(",", ":"))

    def _world_payload_from_text(self, world_text: str) -> tuple[str, str]:
        data = world_markdown_to_form(world_text)
        return str(world_text or ""), self._world_form_data_to_json(data)

    def _character_profile_json_to_data(self, raw_json: str, name: str, role: str) -> dict[str, Any] | None:
        raw_json = str(raw_json or "").strip()
        if not raw_json:
            return None
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return normalize_character_profile_form(payload, name, role)

    def _character_profile_data_to_json(self, data: dict[str, Any] | None, name: str, role: str) -> str:
        normalized = normalize_character_profile_form(data, name, role)
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))

    def _character_profile_payload_from_text(self, profile_text: str, name: str, role: str) -> tuple[str, str]:
        data = character_profile_markdown_to_form(profile_text, name, role)
        markdown = character_profile_form_to_markdown(data, name, role)
        return markdown, self._character_profile_data_to_json(data, name, role)
