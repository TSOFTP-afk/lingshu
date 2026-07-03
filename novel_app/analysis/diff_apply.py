from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from novel_app.analysis.evidence import evidence_summary, resolve_evidence_refs
from novel_app.analysis.models import AnalysisApplyResult, AnalysisCardDraft
from novel_app.analysis.payload_normalizer import has_formal_writeback_content, normalize_book_analysis_payload
from novel_app.analysis.writeback import apply_book_analysis_payload, book_analysis_requires_evidence
from novel_app.database import Database

WRITEBACK_GATE_IGNORED_KEYS = {
    "_meta",
    "_requires_evidence",
    "analysis_unresolved",
    "source_request",
    "source_requests",
    "verification_request",
    "verification_requests",
}


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_array(raw: str) -> list[Any]:
    try:
        value = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _non_empty_dict(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def _payload_has_content(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, dict):
        return any(_payload_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_payload_has_content(item) for item in value)
    return True


def writeback_payload_for_evidence_gate(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in WRITEBACK_GATE_IGNORED_KEYS and _payload_has_content(value)
    }


def _base_diff(card_type: str, payload: dict[str, Any], *, applyable: bool = True) -> dict[str, Any]:
    summary = evidence_summary(payload)
    manual_applyable = bool(applyable and card_type != "unresolved" and has_formal_writeback_content(payload))
    return {
        "card_type": card_type,
        "applyable": applyable,
        "manual_applyable": manual_applyable,
        "requires_user_override": False,
        "change_count": max(1, len([key for key, value in payload.items() if value not in (None, "", [], {})])),
        "changed_paths": sorted(key for key, value in payload.items() if value not in (None, "", [], {})),
        "evidence_summary": summary,
        "candidate_truth_updates": [],
        "notes": [],
    }


def split_book_analysis_payload(payload: dict[str, Any]) -> list[AnalysisCardDraft]:
    payload = normalize_book_analysis_payload(dict(payload))
    drafts: list[AnalysisCardDraft] = [
        AnalysisCardDraft(
            card_uid="full_payload",
            card_type="full_payload",
            payload=payload,
            diff=_base_diff("full_payload", payload, applyable=True),
        )
    ]

    book_summary = _non_empty_dict(payload, ("book_outline", "book_outline_form"))
    if book_summary:
        drafts.append(
            AnalysisCardDraft(
                card_uid="book_summary",
                card_type="book_summary",
                payload=book_summary,
                diff=_base_diff("book_summary", book_summary, applyable=True),
            )
        )

    world_payload = _non_empty_dict(payload, ("world_form", "world_text", "world_entries", "world", "worldbuilding"))
    if world_payload:
        drafts.append(
            AnalysisCardDraft(
                card_uid="world",
                card_type="world",
                payload=world_payload,
                diff=_base_diff("world", world_payload, applyable=True),
            )
        )

    characters_payload = _non_empty_dict(payload, ("characters", "character_cards", "character_profiles"))
    if characters_payload:
        drafts.append(
            AnalysisCardDraft(
                card_uid="characters",
                card_type="characters",
                payload=characters_payload,
                diff=_base_diff("characters", characters_payload, applyable=True),
            )
        )

    chapters_payload = _non_empty_dict(payload, ("chapter_updates",))
    if chapters_payload:
        drafts.append(
            AnalysisCardDraft(
                card_uid="chapters",
                card_type="chapters",
                payload=chapters_payload,
                diff=_base_diff("chapters", chapters_payload, applyable=True),
            )
        )

    unresolved_payload = _non_empty_dict(payload, ("analysis_unresolved",))
    if unresolved_payload:
        drafts.append(
            AnalysisCardDraft(
                card_uid="unresolved",
                card_type="unresolved",
                payload=unresolved_payload,
                diff=_base_diff("unresolved", unresolved_payload, applyable=False),
                status="blocked",
            )
        )
    return drafts


def _evidence_resolution_summary(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    run_id: int | None,
) -> dict[str, Any]:
    if run_id is None:
        return {}

    def lookup(block_uid: str) -> Any:
        return database.get_analysis_block(book_id, block_uid, run_id=run_id)

    return resolve_evidence_refs(payload, lookup).as_dict()


def evidence_writeback_gate(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    *,
    run_id: int | None = None,
    requires_evidence: bool = False,
) -> dict[str, Any]:
    gate_payload = writeback_payload_for_evidence_gate(payload)
    summary = evidence_summary(gate_payload)
    result: dict[str, Any] = {
        "requires_evidence": bool(requires_evidence),
        "status": "not_required",
        "applyable": True,
        "reason": "",
        "evidence_summary": summary,
    }
    if not requires_evidence:
        return result
    if not _payload_has_content(gate_payload):
        result.update(
            {
                "status": "empty",
                "applyable": False,
                "reason": "No writeback fields remain after evidence filtering.",
            }
        )
        return result

    if run_id is None:
        applyable = (
            summary.get("status") == "trusted"
            and int(summary.get("quote_fields", 0) or 0) > 0
            and int(summary.get("chunk_or_block_fields", 0) or 0) > 0
        )
        result.update(
            {
                "status": "trusted" if applyable else "weak",
                "applyable": applyable,
                "reason": "" if applyable else "Evidence needs both quote and block/chunk locator before writeback.",
            }
        )
        return result

    resolution = _evidence_resolution_summary(database, book_id, gate_payload, run_id)
    status = str(resolution.get("status") or "missing")
    applyable = status == "trusted" and int(resolution.get("trusted_refs", 0) or 0) > 0
    result.update(
        {
            "status": status,
            "applyable": applyable,
            "reason": "" if applyable else "Evidence references could not be verified against analysis_blocks.",
            "evidence_resolution": resolution,
        }
    )
    return result


def build_book_analysis_diff(
    database: Database,
    book_id: int,
    card: AnalysisCardDraft,
    *,
    run_id: int | None = None,
    requires_evidence: bool | None = None,
) -> dict[str, Any]:
    diff = dict(card.diff)
    payload = card.payload
    card_type = card.card_type
    changed_paths = set(diff.get("changed_paths", []))
    notes: list[str] = list(diff.get("notes", []))

    if card_type in {"full_payload", "book_summary"}:
        book = database.get_book(book_id)
        if book:
            if payload.get("book_outline") and str(payload.get("book_outline") or "") != str(book["outline_text"] or ""):
                changed_paths.add("books.outline_text")
            if payload.get("book_outline_form"):
                changed_paths.add("books.outline_data_json")
    if card_type in {"full_payload", "world"} and any(
        key in payload for key in ("world_form", "world_text", "world_entries", "world", "worldbuilding")
    ):
        changed_paths.add("books.world_data_json")
    if card_type in {"full_payload", "characters"}:
        character_items = payload.get("character_cards") or payload.get("characters") or payload.get("character_profiles") or []
        if isinstance(character_items, list):
            changed_paths.add(f"characters[{len(character_items)}]")
    if card_type in {"full_payload", "chapters"}:
        chapter_updates = payload.get("chapter_updates") or []
        if isinstance(chapter_updates, list):
            changed_paths.add(f"chapter_updates[{len(chapter_updates)}]")
    if card_type == "unresolved":
        notes.append("证据不足或需要人工确认，P0 不自动写回。")
        diff["applyable"] = False

    gate_requires_evidence = bool(payload.get("_requires_evidence")) if requires_evidence is None else bool(requires_evidence)
    gate = evidence_writeback_gate(
        database,
        book_id,
        payload,
        run_id=run_id,
        requires_evidence=gate_requires_evidence,
    )
    diff["evidence_writeback_gate"] = gate
    if gate_requires_evidence and not gate.get("applyable", False):
        diff["applyable"] = False
        reason = str(gate.get("reason") or "Evidence writeback gate failed.")
        if reason and reason not in notes:
            notes.append(reason)

    manual_applyable = bool(card_type != "unresolved" and has_formal_writeback_content(payload))
    diff["manual_applyable"] = manual_applyable
    diff["requires_user_override"] = bool(manual_applyable and not diff.get("applyable", False))

    diff["changed_paths"] = sorted(changed_paths)
    diff["change_count"] = len(changed_paths)
    diff["notes"] = notes
    diff["evidence_summary"] = evidence_summary(payload)
    resolution = _evidence_resolution_summary(database, book_id, payload, run_id)
    if resolution:
        diff["evidence_resolution"] = resolution
    return diff


def build_drafts_with_diffs(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    *,
    run_id: int | None = None,
) -> list[AnalysisCardDraft]:
    drafts: list[AnalysisCardDraft] = []
    requires_evidence = bool(payload.get("_requires_evidence"))
    for draft in split_book_analysis_payload(payload):
        drafts.append(
            AnalysisCardDraft(
                card_uid=draft.card_uid,
                card_type=draft.card_type,
                payload=draft.payload,
                diff=build_book_analysis_diff(
                    database,
                    book_id,
                    draft,
                    run_id=run_id,
                    requires_evidence=requires_evidence,
                ),
                status=draft.status,
                entity_uid=draft.entity_uid,
                ars_score=draft.ars_score,
            )
        )
    return drafts


def capture_apply_snapshot(database: Database, book_id: int) -> dict[str, Any]:
    book = database.get_book(book_id)
    chapters = database.connection.execute(
        """
        SELECT id, title, outline, summary_text, ai_probability, ai_probability_level
        FROM chapters
        WHERE book_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (book_id,),
    ).fetchall()
    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "book": dict(book) if book else {},
        "characters": [dict(item) for item in database.list_characters(book_id)],
        "relationships": [dict(item) for item in database.list_relationships(book_id)],
        "world_entries": [dict(item) for item in database.list_world_entries(book_id)],
        "chapter_events": [dict(item) for item in database.list_chapter_events(book_id)],
        "chapters": [dict(item) for item in chapters],
    }


def card_payload(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return _json_object(str(row.get("payload_json", "{}")))
    return _json_object(str(row["payload_json"] or "{}"))


def card_diff(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return _json_object(str(row.get("diff_json", "{}")))
    return _json_object(str(row["diff_json"] or "{}"))


def apply_analysis_cards(
    database: Database,
    book_id: int,
    run_id: int,
    card_ids: list[int],
    *,
    allow_weak_evidence: bool = False,
) -> AnalysisApplyResult:
    requested_ids = [int(card_id) for card_id in card_ids]
    if not requested_ids:
        return AnalysisApplyResult(applied_cards=0, skipped_cards=0, snapshot_id=None, audit_log_ids=[])

    rows: list[Any] = []
    skipped = 0
    for card_id in requested_ids:
        row = database.get_analysis_card(card_id)
        if not row or int(row["book_id"]) != book_id or int(row["run_id"]) != run_id:
            skipped += 1
            continue
        rows.append(row)

    full_card = next(
        (
            row
            for row in rows
            if str(row["card_type"] or "") == "full_payload" and str(row["status"] or "") == "draft"
        ),
        None,
    )
    if full_card is None:
        return AnalysisApplyResult(applied_cards=0, skipped_cards=skipped + len(rows), snapshot_id=None, audit_log_ids=[])

    payload = normalize_book_analysis_payload(card_payload(full_card))
    requires_evidence = book_analysis_requires_evidence(payload)
    gate = evidence_writeback_gate(
        database,
        book_id,
        payload,
        run_id=run_id,
        requires_evidence=requires_evidence,
    )
    if not has_formal_writeback_content(payload):
        return AnalysisApplyResult(applied_cards=0, skipped_cards=skipped + len(rows), snapshot_id=None, audit_log_ids=[])
    if not gate.get("applyable", False) and not allow_weak_evidence:
        diff = card_diff(full_card)
        diff["evidence_writeback_gate"] = gate
        diff["applyable"] = False
        diff["manual_applyable"] = True
        diff["requires_user_override"] = True
        database.update_analysis_card_diff(int(full_card["id"]), diff)
        return AnalysisApplyResult(applied_cards=0, skipped_cards=skipped + len(rows), snapshot_id=None, audit_log_ids=[])

    snapshot = capture_apply_snapshot(database, book_id)
    snapshot_id = database.create_analysis_apply_snapshot(
        book_id,
        run_id,
        f"分析写回前快照 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        snapshot,
    )
    writeback_result = apply_book_analysis_payload(
        database,
        book_id,
        payload,
        allow_weak_evidence=allow_weak_evidence,
        requires_evidence=requires_evidence,
    )

    applied = 0
    audit_ids: list[int] = []
    weak_override = bool(allow_weak_evidence and not gate.get("applyable", False))
    action = "applied_with_weak_evidence" if weak_override else "applied"
    reason = "用户确认弱证据分析草案写回" if weak_override else "用户确认应用分析草案"
    for row in rows:
        if str(row["status"] or "") != "draft":
            skipped += 1
            continue
        database.mark_analysis_card_applied(
            int(row["id"]),
            applied_table="analysis_runs",
            applied_id=run_id,
        )
        audit_ids.append(
            database.create_analysis_audit_log(
                book_id,
                run_id=run_id,
                card_id=int(row["id"]),
                action=action,
                target_type=str(row["card_type"] or "analysis_card"),
                target_uid=str(row["card_uid"] or ""),
                old_value={
                    "snapshot_id": snapshot_id,
                    "evidence_writeback_gate": gate,
                    "writeback_result": {
                        "updated_chapter_ids": sorted(writeback_result.updated_chapter_ids),
                        "processed_chapters": writeback_result.processed_chapters,
                    },
                },
                new_value=card_payload(row),
                reason=reason,
            )
        )
        applied += 1

    database.update_analysis_run_status(
        run_id,
        "applied",
        summary=f"已应用 {applied} 张分析草案" + ("（弱证据确认）" if weak_override else ""),
        meta={
            "snapshot_id": snapshot_id,
            "audit_log_ids": audit_ids,
            "weak_evidence_override": weak_override,
            "last_writeback_gate": gate,
        },
    )
    return AnalysisApplyResult(
        applied_cards=applied,
        skipped_cards=skipped,
        snapshot_id=snapshot_id,
        audit_log_ids=audit_ids,
        updated_chapter_ids=set(writeback_result.updated_chapter_ids),
        processed_chapters=writeback_result.processed_chapters,
        unresolved_count=writeback_result.unresolved_count,
        evidence_gate_dropped=writeback_result.evidence_gate_dropped,
        weak_evidence_override=weak_override,
    )
