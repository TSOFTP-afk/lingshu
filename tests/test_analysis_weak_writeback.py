from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from novel_app.analysis import (
    AnalysisCardBuilder,
    AnalysisStore,
    has_formal_writeback_content,
    has_unresolved_analysis_items,
    normalize_book_analysis_payload,
)
from novel_app.analysis.diff_apply import capture_apply_snapshot, card_diff, card_payload, evidence_writeback_gate
from novel_app.analysis.writeback import apply_book_analysis_payload, book_analysis_requires_evidence
from novel_app.database import Database


class AnalysisApplyHarness:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.state = SimpleNamespace(selected_book_title="Weak Evidence Book", selected_chapter_id=None)
        self.current_tree_key = ""
        self.calls: list[tuple[str, int, int | None]] = []
        self.logs: list[str] = []
        self.statuses: list[str] = []

    def _book_outline_volume_specs(self, book_id: int) -> list[dict]:
        return self.database._book_outline_volume_specs(book_id)

    def _analysis_store(self) -> AnalysisStore:
        return AnalysisStore(self.database)

    @staticmethod
    def _book_analysis_requires_evidence(payload: dict) -> bool:
        return book_analysis_requires_evidence(payload)

    def _save_book_analysis_draft(self, book_id: int, run_id: int, payload: dict) -> list[int]:
        payload = normalize_book_analysis_payload(payload)
        drafts = AnalysisCardBuilder(self.database, book_id, run_id=run_id).build(payload)
        card_ids = self._analysis_store().save_cards(book_id, run_id, drafts)
        self._analysis_store().create_audit_log(
            book_id,
            run_id=run_id,
            action="draft_created",
            target_type="analysis_run",
            target_uid=str(run_id),
            new_value={"card_count": len(card_ids), "card_types": [draft.card_type for draft in drafts]},
            reason="全书分析完成后保存为待确认草案",
        )
        return card_ids

    def _book_has_successful_analysis_writeback(self, book_id: int, current_run_id: int | None = None) -> bool:
        params: list[int] = [book_id]
        sql = "SELECT 1 FROM analysis_runs WHERE book_id = ? AND status = 'applied'"
        if current_run_id is not None:
            sql += " AND id != ?"
            params.append(current_run_id)
        sql += " LIMIT 1"
        return self.database.connection.execute(sql, params).fetchone() is not None

    def _handle_book_analysis_payload_as_draft(self, book_id: int, run_id: int, payload: dict) -> None:
        payload = normalize_book_analysis_payload(payload)
        card_ids = self._save_book_analysis_draft(book_id, run_id, payload)
        has_formal_content = has_formal_writeback_content(payload)
        gate = evidence_writeback_gate(
            self.database,
            book_id,
            payload,
            run_id=run_id,
            requires_evidence=self._book_analysis_requires_evidence(payload),
        )
        is_first_analysis_writeback = has_formal_content and not self._book_has_successful_analysis_writeback(book_id, run_id)
        should_auto_apply = (
            is_first_analysis_writeback
            or (
                bool(gate.get("applyable", True))
                and str(gate.get("status") or "") == "trusted"
                and not has_unresolved_analysis_items(payload)
            )
            and has_formal_content
        )
        if should_auto_apply:
            self._analysis_store().update_run_status(
                run_id,
                "awaiting_review",
                summary=f"生成 {len(card_ids)} 张分析草案，正在写回正式卡片",
                meta={
                    "card_count": len(card_ids),
                    "auto_apply": True,
                    "first_analysis_auto_apply": is_first_analysis_writeback,
                    "writeback_gate": gate,
                },
            )
            self._apply_confirmed_analysis_run(
                run_id,
                require_user_confirm=False,
                allow_weak_evidence_override=is_first_analysis_writeback,
                first_analysis_auto_apply=is_first_analysis_writeback,
            )
            return
        self._analysis_store().update_run_status(
            run_id,
            "awaiting_review",
            summary=f"生成 {len(card_ids)} 张分析草案，等待确认写回",
            meta={"card_count": len(card_ids), "writeback_gate": gate},
        )

    def _apply_book_analysis_result(self, book_id: int, payload: dict, *, allow_weak_evidence: bool = False) -> None:
        payload = normalize_book_analysis_payload(payload)
        result = apply_book_analysis_payload(
            self.database,
            book_id,
            payload,
            allow_weak_evidence=allow_weak_evidence,
            requires_evidence=self._book_analysis_requires_evidence(payload),
        )
        self._sync_truth_files(book_id)
        self._index_book_design_for_rag(book_id)
        for chapter_id in sorted(result.updated_chapter_ids):
            self._index_chapter_for_rag(book_id, chapter_id)
            self._sync_chapter_tab_after_external_write(chapter_id, force=False)
        self._load_library_tree(self.current_tree_key)
        self._refresh_drawer()
        self._refresh_structured_markdown_views_after_analysis(book_id)
        self._switch_drawer_tab("overview")
        self._update_word_count()

    def _block_analysis_full_payload(self, run_id: int, book_id: int, full_card, gate: dict) -> None:
        diff = card_diff(full_card)
        diff["applyable"] = False
        diff["manual_applyable"] = False
        diff["requires_user_override"] = False
        diff["evidence_writeback_gate"] = gate
        self.database.update_analysis_card_diff(int(full_card["id"]), diff, status="blocked")
        self.database.update_analysis_run_status(run_id, "awaiting_review", meta={"last_writeback_gate": gate})

    def _apply_confirmed_analysis_run(
        self,
        run_id: int,
        *,
        require_user_confirm: bool = True,
        allow_weak_evidence_override: bool = False,
        first_analysis_auto_apply: bool = False,
    ) -> None:
        run = self.database.get_analysis_run(run_id)
        if not run:
            return
        book_id = int(run["book_id"])
        cards = self.database.list_analysis_cards(run_id)
        draft_cards = [card for card in cards if str(card["status"]) == "draft"]
        full_card = self.database.get_analysis_full_payload_card(run_id)
        if not full_card or str(full_card["status"]) != "draft":
            return
        payload = normalize_book_analysis_payload(card_payload(full_card))
        gate = evidence_writeback_gate(
            self.database,
            book_id,
            payload,
            run_id=run_id,
            requires_evidence=self._book_analysis_requires_evidence(payload),
        )
        manual_applyable = has_formal_writeback_content(payload)
        allow_weak_evidence = False
        if not gate.get("applyable", True):
            if manual_applyable and (require_user_confirm or allow_weak_evidence_override):
                allow_weak_evidence = True
            else:
                self._block_analysis_full_payload(run_id, book_id, full_card, gate)
                return
        snapshot = capture_apply_snapshot(self.database, book_id)
        snapshot_id = self.database.create_analysis_apply_snapshot(
            book_id,
            run_id,
            f"分析写回前快照 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            snapshot,
        )
        self._apply_book_analysis_result(book_id, payload, allow_weak_evidence=allow_weak_evidence)
        if first_analysis_auto_apply and allow_weak_evidence:
            audit_action = "first_analysis_auto_applied_with_weak_evidence"
            audit_reason = "首次解析弱证据自动写入正式库"
        elif first_analysis_auto_apply:
            audit_action = "first_analysis_auto_applied"
            audit_reason = "首次解析自动写入正式库"
        else:
            audit_action = "applied_with_weak_evidence" if allow_weak_evidence else "applied"
            audit_reason = "用户确认弱证据分析草案写回" if allow_weak_evidence else "用户确认应用分析草案"
        audit_ids: list[int] = []
        for card in draft_cards:
            self.database.mark_analysis_card_applied(int(card["id"]), applied_table="analysis_runs", applied_id=run_id)
            audit_ids.append(
                self.database.create_analysis_audit_log(
                    book_id,
                    run_id=run_id,
                    card_id=int(card["id"]),
                    action=audit_action,
                    target_type=str(card["card_type"] or "analysis_card"),
                    target_uid=str(card["card_uid"] or ""),
                    old_value={"snapshot_id": snapshot_id, "evidence_writeback_gate": gate},
                    new_value=card_payload(card),
                    reason=audit_reason,
                )
            )
        self.database.update_analysis_run_status(
            run_id,
            "applied",
            summary=f"已应用 {len(draft_cards)} 张分析草案",
            meta={
                "snapshot_id": snapshot_id,
                "audit_log_ids": audit_ids,
                "auto_applied": not require_user_confirm,
                "first_analysis_auto_apply": first_analysis_auto_apply,
                "weak_evidence_override": allow_weak_evidence,
                "last_writeback_gate": gate,
            },
        )
        self._refresh_analysis_tab()

    def _open_drawer(self, kind: str = "details") -> None:
        self.logs.append(f"open:{kind}")

    def _sync_truth_files(self, book_id: int, chapter_id: int | None = None) -> None:
        self.calls.append(("truth", book_id, chapter_id))

    def _index_book_design_for_rag(self, book_id: int) -> None:
        self.calls.append(("book_design", book_id, None))

    def _index_chapter_for_rag(self, book_id: int, chapter_id: int) -> None:
        self.calls.append(("chapter_rag", book_id, chapter_id))

    def _sync_chapter_tab_after_external_write(self, chapter_id: int, *, activate: bool = False, force: bool = False) -> None:
        self.calls.append(("chapter_tab", chapter_id, int(activate)))

    def _load_library_tree(self, current_key: str = "") -> None:
        self.calls.append(("library_tree", 0, None))

    def _refresh_drawer(self) -> None:
        self.calls.append(("drawer", 0, None))

    def _refresh_structured_markdown_views_after_analysis(self, book_id: int) -> None:
        self.calls.append(("structured_views", book_id, None))

    def _refresh_analysis_tab(self) -> None:
        self.calls.append(("analysis_tab", 0, None))

    def _switch_drawer_tab(self, tab_key: str) -> None:
        self.logs.append(f"switch:{tab_key}")

    def _set_status(self, text: str) -> None:
        self.statuses.append(text)

    def _update_word_count(self) -> None:
        self.calls.append(("word_count", 0, None))

    def _append_task_log(self, text: str) -> None:
        self.logs.append(text)


def test_user_confirmed_weak_evidence_writeback_updates_formal_cards_truth_and_rag(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("Weak Evidence Book")
        chapter_id = db.create_chapter(book_id, "Chapter One")
        db.update_chapter(chapter_id, outline="old outline", content="chapter body", summary_text="old summary")
        db.create_chapter_event(book_id, chapter_id, "old event")
        run_id = db.create_analysis_run(book_id, status="awaiting_review")

        payload = {
            "_requires_evidence": True,
            "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "xianxia"}}},
            "world_form": {"fields": {"world_rules_table": {"value": "power depends on gu insects"}}},
            "characters": [
                {
                    "name": "Fang Yuan",
                    "role": "Protagonist",
                    "profile_form": {"fields": {"personality_main": {"value": "calm and decisive"}}},
                }
            ],
            "chapter_updates": [
                {
                    "chapter_id": chapter_id,
                    "outline": "Fang Yuan is reborn.",
                    "events": ["Fang Yuan is reborn"],
                }
            ],
        }
        drafts = AnalysisCardBuilder(db, book_id, run_id=run_id).build(payload)
        AnalysisStore(db).save_cards(book_id, run_id, drafts)

        harness = AnalysisApplyHarness(db)
        harness._apply_confirmed_analysis_run(run_id)

        assert db.get_book_outline_form(book_id)["fields"]["primary_parent_tag_id"]["value"] == "xianxia"
        assert db.get_book_world_form(book_id)["fields"]["world_rules_table"]["value"] == "power depends on gu insects"
        character = db.list_characters(book_id)[0]
        assert character["name"] == "Fang Yuan"
        assert character["role"] == "Protagonist"
        profile = db.get_character_profile_form(int(character["id"]))
        assert profile["fields"]["personality_main"]["value"] == "calm and decisive"
        chapter = db.get_chapter(chapter_id)
        assert chapter["outline"] == "Fang Yuan is reborn."
        assert [event["label"] for event in db.list_chapter_events(book_id, chapter_id)] == ["Fang Yuan is reborn"]

        run = db.get_analysis_run(run_id)
        assert run["status"] == "applied"
        run_meta = json.loads(str(run["meta_json"] or "{}"))
        assert run_meta["weak_evidence_override"] is True
        assert run_meta["last_writeback_gate"]["status"] == "missing"
        logs = db.list_analysis_audit_logs(book_id, run_id)
        assert {log["action"] for log in logs} == {"applied_with_weak_evidence"}
        assert ("truth", book_id, None) in harness.calls
        assert ("book_design", book_id, None) in harness.calls
        assert ("chapter_rag", book_id, chapter_id) in harness.calls
    finally:
        db.close()


def test_first_analysis_auto_applies_weak_evidence_to_formal_database(tmp_path: Path) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("First Analysis Book")
        chapter_id = db.create_chapter(book_id, "Chapter One")
        db.update_chapter(chapter_id, outline="old outline", content="chapter body", summary_text="")
        run_id = db.create_analysis_run(book_id, status="running")
        payload = {
            "_requires_evidence": True,
            "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "xianxia"}}},
            "world_form": {"fields": {"world_rules_table": {"value": "sect law rules the city"}}},
            "characters": [
                {
                    "name": "Lin",
                    "role": "Protagonist",
                    "profile_form": {"fields": {"personality_main": {"value": "patient"}}},
                }
            ],
            "chapter_updates": [{"chapter_id": chapter_id, "outline": "Lin enters the city.", "events": ["Lin enters the city"]}],
        }

        harness = AnalysisApplyHarness(db)
        harness._handle_book_analysis_payload_as_draft(book_id, run_id, payload)

        run = db.get_analysis_run(run_id)
        assert run["status"] == "applied"
        meta = json.loads(str(run["meta_json"] or "{}"))
        assert meta["first_analysis_auto_apply"] is True
        assert meta["weak_evidence_override"] is True
        assert db.get_book_outline_form(book_id)["fields"]["primary_parent_tag_id"]["value"] == "xianxia"
        assert db.get_book_world_form(book_id)["fields"]["world_rules_table"]["value"] == "sect law rules the city"
        assert db.list_characters(book_id)[0]["name"] == "Lin"
        assert db.get_chapter(chapter_id)["outline"] == "Lin enters the city."
        assert [event["label"] for event in db.list_chapter_events(book_id, chapter_id)] == ["Lin enters the city"]
        assert "first_analysis_auto_applied_with_weak_evidence" in {
            log["action"] for log in db.list_analysis_audit_logs(book_id, run_id)
        }
    finally:
        db.close()


def test_weak_evidence_after_successful_analysis_stays_awaiting_review(tmp_path: Path) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("Repeated Analysis Book")
        previous_run_id = db.create_analysis_run(book_id, status="applied")
        run_id = db.create_analysis_run(book_id, status="running")
        payload = {
            "_requires_evidence": True,
            "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "qihuan"}}},
        }

        harness = AnalysisApplyHarness(db)
        harness._handle_book_analysis_payload_as_draft(book_id, run_id, payload)

        assert db.get_analysis_run(previous_run_id)["status"] == "applied"
        run = db.get_analysis_run(run_id)
        assert run["status"] == "awaiting_review"
        meta = json.loads(str(run["meta_json"] or "{}"))
        assert meta.get("first_analysis_auto_apply") is None
        assert db.get_book_outline_form(book_id)["fields"]["primary_parent_tag_id"]["value"] == ""
        assert any(str(card["status"]) == "draft" for card in db.list_analysis_cards(run_id))
    finally:
        db.close()
