from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.diff_apply import (
    build_book_analysis_diff,
    card_payload,
    evidence_writeback_gate,
    split_book_analysis_payload,
)
from novel_app.analysis.entity_resolver import (
    EntityResolutionResult,
    EntityResolver,
    ResolvedEntity,
    stable_entity_uid,
)
from novel_app.analysis.models import AnalysisCardDraft
from novel_app.database import Database


@dataclass(frozen=True)
class BuiltAnalysisCards:
    drafts: list[AnalysisCardDraft]
    entity_resolution: EntityResolutionResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "card_count": len(self.drafts),
            "entity_resolution": self.entity_resolution.as_dict(),
            "card_types": [draft.card_type for draft in self.drafts],
        }


class AnalysisCardBuilder:
    def __init__(
        self,
        database: Database,
        book_id: int,
        *,
        run_id: int | None = None,
        entity_resolver: EntityResolver | None = None,
    ) -> None:
        self.database = database
        self.book_id = int(book_id)
        self.run_id = run_id
        self.entity_resolver = entity_resolver or EntityResolver()

    def build(self, payload: dict[str, Any]) -> list[AnalysisCardDraft]:
        return self.build_result(payload).drafts

    def build_result(self, payload: dict[str, Any]) -> BuiltAnalysisCards:
        normalized_payload = dict(payload) if isinstance(payload, dict) else {}
        resolution = self.entity_resolver.resolve(normalized_payload, book_id=self.book_id)
        requires_evidence = bool(normalized_payload.get("_requires_evidence"))
        drafts: list[AnalysisCardDraft] = []
        for draft in split_book_analysis_payload(normalized_payload):
            entity_uid = self._entity_uid_for_card(draft.card_type, draft.payload, resolution)
            diff = build_book_analysis_diff(
                self.database,
                self.book_id,
                draft,
                run_id=self.run_id,
                requires_evidence=requires_evidence,
            )
            diff = self._enrich_diff(diff, draft.card_type, draft.payload, entity_uid, resolution)
            ars_score = self._ars_score(diff, draft.status)
            diff["ars_score"] = ars_score
            drafts.append(
                AnalysisCardDraft(
                    card_uid=draft.card_uid,
                    card_type=draft.card_type,
                    payload=draft.payload,
                    diff=diff,
                    status=draft.status,
                    entity_uid=entity_uid,
                    ars_score=ars_score,
                )
            )
        return BuiltAnalysisCards(drafts=drafts, entity_resolution=resolution)

    def _enrich_diff(
        self,
        diff: dict[str, Any],
        card_type: str,
        payload: dict[str, Any],
        entity_uid: str,
        resolution: EntityResolutionResult,
    ) -> dict[str, Any]:
        enriched = dict(diff)
        enriched["entity_uid"] = entity_uid
        enriched["entity_resolution"] = self._resolution_for_diff(card_type, resolution)
        enriched["candidate_truth_updates"] = self._candidate_truth_updates(card_type, payload, resolution)
        notes = list(enriched.get("notes", [])) if isinstance(enriched.get("notes"), list) else []
        if resolution.entity_count:
            note = f"Resolved {resolution.entity_count} stable entities for draft review."
            if note not in notes:
                notes.append(note)
        enriched["notes"] = notes
        return enriched

    def _entity_uid_for_card(
        self,
        card_type: str,
        payload: dict[str, Any],
        resolution: EntityResolutionResult,
    ) -> str:
        if card_type == "characters":
            entities = self._entities_for_payload_names(payload, resolution, "character")
            if len(entities) == 1:
                return entities[0].entity_uid
            return stable_entity_uid("group", "characters", book_id=self.book_id)
        if card_type == "world":
            entities = self._entities_for_payload_names(payload, resolution, "world", "location", "organization", "item", "concept")
            if len(entities) == 1:
                return entities[0].entity_uid
            return stable_entity_uid("group", "world", book_id=self.book_id)
        if card_type == "chapters":
            return stable_entity_uid("group", "chapters", book_id=self.book_id)
        if card_type == "book_summary":
            return stable_entity_uid("book", "book_summary", book_id=self.book_id)
        if card_type == "unresolved":
            return stable_entity_uid("group", "unresolved", book_id=self.book_id)
        return stable_entity_uid("book", "full_payload", book_id=self.book_id)

    def _entities_for_payload_names(
        self,
        payload: dict[str, Any],
        resolution: EntityResolutionResult,
        *entity_types: str,
    ) -> list[ResolvedEntity]:
        names = set(_payload_names(payload))
        if not names:
            return resolution.entities_by_type(*entity_types)
        matched: list[ResolvedEntity] = []
        for entity in resolution.entities_by_type(*entity_types):
            aliases = {entity.canonical_name, *entity.aliases}
            if any(name in aliases for name in names):
                matched.append(entity)
        return matched

    def _resolution_for_diff(self, card_type: str, resolution: EntityResolutionResult) -> dict[str, Any]:
        if card_type == "characters":
            entities = resolution.entities_by_type("character")
        elif card_type == "world":
            entities = resolution.entities_by_type("world", "location", "organization", "item", "concept")
        else:
            entities = resolution.entities_by_type()
        return {
            "entity_count": len(entities),
            "mention_count": resolution.mention_count,
            "entities": [
                {
                    "entity_uid": entity.entity_uid,
                    "entity_type": entity.entity_type,
                    "canonical_name": entity.canonical_name,
                    "aliases": list(entity.aliases),
                    "confidence": entity.confidence,
                }
                for entity in entities
            ],
        }

    def _candidate_truth_updates(
        self,
        card_type: str,
        payload: dict[str, Any],
        resolution: EntityResolutionResult,
    ) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        if card_type in {"full_payload", "book_summary"}:
            if payload.get("book_outline"):
                updates.append(_truth_update("book_outline", "books.outline_text", payload.get("book_outline")))
            if payload.get("book_outline_form"):
                updates.append(_truth_update("book_outline_form", "books.outline_data_json", payload.get("book_outline_form")))
        if card_type in {"full_payload", "world"}:
            world_payload = {
                key: payload.get(key)
                for key in ("world_form", "world_text", "world_entries", "world", "worldbuilding")
                if payload.get(key) not in (None, "", [], {})
            }
            if world_payload:
                updates.append(
                    _truth_update(
                        "world",
                        "books.world_data_json",
                        world_payload,
                        entity_uids=[entity.entity_uid for entity in resolution.entities_by_type("world", "location", "organization", "item", "concept")],
                    )
                )
        if card_type in {"full_payload", "characters"}:
            character_payload = {
                key: payload.get(key)
                for key in ("characters", "character_cards", "character_profiles")
                if payload.get(key) not in (None, "", [], {})
            }
            if character_payload:
                updates.append(
                    _truth_update(
                        "characters",
                        "characters/profile_data_json",
                        character_payload,
                        entity_uids=[entity.entity_uid for entity in resolution.entities_by_type("character")],
                    )
                )
        if card_type in {"full_payload", "chapters"} and payload.get("chapter_updates"):
            updates.append(_truth_update("chapters", "chapters/events/summary", payload.get("chapter_updates")))
        return updates

    @staticmethod
    def _ars_score(diff: dict[str, Any], status: str) -> float:
        gate = diff.get("evidence_writeback_gate") if isinstance(diff.get("evidence_writeback_gate"), dict) else {}
        summary = diff.get("evidence_summary") if isinstance(diff.get("evidence_summary"), dict) else {}
        gate_status = str(gate.get("status") or "").strip()
        evidence_status = str(summary.get("status") or "").strip()
        status_key = evidence_status if gate_status in {"", "not_required"} else gate_status
        base = {
            "trusted": 0.88,
            "weak": 0.56,
            "missing": 0.28,
            "empty": 0.2,
            "not_required": 0.62,
        }.get(status_key, 0.5)
        if diff.get("applyable") is False or status == "blocked":
            base = min(base, 0.34)
        if int(summary.get("unresolved_count", 0) or 0) > 0:
            base -= 0.08
        if int(summary.get("quote_fields", 0) or 0) > 0 and int(summary.get("chunk_or_block_fields", 0) or 0) > 0:
            base += 0.06
        if diff.get("candidate_truth_updates"):
            base += 0.03
        return round(max(0.0, min(1.0, base)), 3)


def build_analysis_card_drafts(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    *,
    run_id: int | None = None,
) -> list[AnalysisCardDraft]:
    return AnalysisCardBuilder(database, book_id, run_id=run_id).build(payload)


def verify_analysis_card_evidence(
    database: Database,
    book_id: int,
    card_or_payload: Any,
    *,
    run_id: int | None = None,
    requires_evidence: bool | None = None,
) -> dict[str, Any]:
    payload = _payload_from_card_or_payload(card_or_payload)
    gate_requires_evidence = bool(payload.get("_requires_evidence")) if requires_evidence is None else bool(requires_evidence)
    return evidence_writeback_gate(
        database,
        int(book_id),
        payload,
        run_id=run_id,
        requires_evidence=gate_requires_evidence,
    )


def _truth_update(
    target: str,
    path: str,
    value: Any,
    *,
    entity_uids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "target": target,
        "path": path,
        "summary": _summarize_value(value),
        "entity_uids": list(dict.fromkeys(entity_uids or [])),
    }


def _summarize_value(value: Any, max_chars: int = 240) -> str:
    text = value.strip() if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."


def _payload_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            name = value.get("name") or value.get("title") or value.get("character_name") or value.get("entity_name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return list(dict.fromkeys(names))


def _payload_from_card_or_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and ("payload_json" in value or "card_type" in value):
        return card_payload(value)
    if hasattr(value, "keys"):
        try:
            if "payload_json" in value:
                return card_payload(value)
        except Exception:
            pass
    return dict(value) if isinstance(value, dict) else {}
