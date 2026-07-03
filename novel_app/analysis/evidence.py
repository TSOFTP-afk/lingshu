from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

EVIDENCE_KEYS = {
    "evidence",
    "evidence_ref",
    "evidence_refs",
    "evidence_quote",
    "evidence_quotes",
    "source_quote",
    "source_quotes",
    "source_block_uid",
    "source_blocks",
    "chunk_id",
    "chunk_ids",
    "block_uid",
    "block_uids",
}


@dataclass(frozen=True)
class EvidenceRef:
    source_type: str = "source_text"
    source_id: str = ""
    chapter_id: int | None = None
    block_uid: str = ""
    quote: str = ""
    confidence: str = "weak"
    locator: str = ""
    field_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "chapter_id": self.chapter_id,
            "block_uid": self.block_uid,
            "quote": self.quote,
            "confidence": self.confidence,
            "locator": self.locator,
            "field_path": self.field_path,
        }


@dataclass(frozen=True)
class EvidenceResolution:
    status: str
    refs: list[EvidenceRef]
    trusted_refs: int = 0
    weak_refs: int = 0
    missing_refs: int = 0
    quote_mismatches: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ref_count": len(self.refs),
            "trusted_refs": self.trusted_refs,
            "weak_refs": self.weak_refs,
            "missing_refs": self.missing_refs,
            "quote_mismatches": self.quote_mismatches,
            "refs": [ref.as_dict() for ref in self.refs],
        }


@dataclass(frozen=True)
class EvidenceGateResult:
    status: str
    evidence_fields: int = 0
    quote_fields: int = 0
    chunk_or_block_fields: int = 0
    unresolved_count: int = 0
    dropped_by_gate: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence_fields": self.evidence_fields,
            "quote_fields": self.quote_fields,
            "chunk_or_block_fields": self.chunk_or_block_fields,
            "unresolved_count": self.unresolved_count,
            "dropped_by_gate": self.dropped_by_gate,
        }


def analysis_value_has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, dict):
        return any(analysis_value_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(analysis_value_has_content(item) for item in value)
    return bool(value)


def walk_analysis_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for item in value.values():
            values.extend(walk_analysis_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(walk_analysis_values(item))
    return values


def extract_evidence_refs(value: Any) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]" if path else f"[{index}]")
            return
        if not isinstance(node, dict):
            return

        inline_refs = _inline_refs_from_dict(node, path)
        refs.extend(inline_refs)
        if not inline_refs:
            for key in ("evidence_ref", "evidence_refs"):
                if key in node:
                    refs.extend(_refs_from_value(node.get(key), path))
        for key, item in node.items():
            if key in {"evidence_ref", "evidence_refs"}:
                continue
            walk(item, f"{path}.{key}" if path else str(key))

    walk(value, "")
    return _dedupe_refs(refs)


def resolve_evidence_refs(
    value: Any,
    block_lookup: Callable[[str], Any],
) -> EvidenceResolution:
    refs = extract_evidence_refs(value)
    if not refs:
        return EvidenceResolution(status="missing", refs=[])

    trusted = 0
    weak = 0
    missing = 0
    mismatches = 0
    resolved_refs: list[EvidenceRef] = []
    for ref in refs:
        block_uid = ref.block_uid.strip()
        quote = ref.quote.strip()
        if not block_uid:
            weak += 1
            resolved_refs.append(_ref_with_confidence(ref, "weak"))
            continue
        block = block_lookup(block_uid)
        block_text = _block_text(block)
        if not block_text:
            missing += 1
            resolved_refs.append(_ref_with_confidence(ref, "missing"))
            continue
        if quote and quote not in block_text:
            weak += 1
            mismatches += 1
            resolved_refs.append(_ref_with_confidence(ref, "weak"))
            continue
        if quote:
            trusted += 1
            resolved_refs.append(_ref_with_confidence(ref, "trusted"))
        else:
            weak += 1
            resolved_refs.append(_ref_with_confidence(ref, "weak"))

    if missing:
        status = "missing"
    elif weak:
        status = "weak"
    else:
        status = "trusted"
    return EvidenceResolution(
        status=status,
        refs=resolved_refs,
        trusted_refs=trusted,
        weak_refs=weak,
        missing_refs=missing,
        quote_mismatches=mismatches,
    )


def has_evidence(value: Any) -> bool:
    if isinstance(value, list):
        return any(has_evidence(item) for item in value)
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if str(key).strip() in EVIDENCE_KEYS and analysis_value_has_content(item):
            return True
    return any(has_evidence(item) for item in value.values())


def has_direct_evidence(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        str(key).strip() in EVIDENCE_KEYS and analysis_value_has_content(item)
        for key, item in value.items()
    )


def evidence_gate_result(payload: dict[str, Any]) -> EvidenceGateResult:
    evidence_count = 0
    quote_count = 0
    chunk_count = 0
    for value in walk_analysis_values(payload):
        if not isinstance(value, dict):
            continue
        for key, item in value.items():
            normalized = str(key).strip()
            if normalized not in EVIDENCE_KEYS or not analysis_value_has_content(item):
                continue
            evidence_count += 1
            if "quote" in normalized:
                quote_count += 1
            if "chunk" in normalized or "block" in normalized:
                chunk_count += 1
    unresolved = payload.get("analysis_unresolved", [])
    unresolved_count = len(unresolved) if isinstance(unresolved, list) else 0
    meta = payload.get("_meta", {}) if isinstance(payload.get("_meta"), dict) else {}
    dropped = int(meta.get("evidence_gate_dropped", 0) or 0)
    if dropped or unresolved_count:
        status = "weak"
    elif evidence_count:
        status = "trusted"
    else:
        status = "missing"
    return EvidenceGateResult(
        status=status,
        evidence_fields=evidence_count,
        quote_fields=quote_count,
        chunk_or_block_fields=chunk_count,
        unresolved_count=unresolved_count,
        dropped_by_gate=dropped,
    )


def evidence_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return evidence_gate_result(payload).as_dict()


def _refs_from_value(value: Any, path: str) -> list[EvidenceRef]:
    if isinstance(value, list):
        refs: list[EvidenceRef] = []
        for index, item in enumerate(value):
            refs.extend(_refs_from_value(item, f"{path}.evidence_refs[{index}]" if path else f"evidence_refs[{index}]"))
        return refs
    if isinstance(value, dict):
        return [_ref_from_dict(value, path)]
    text = str(value or "").strip()
    if not text:
        return []
    return [EvidenceRef(source_id=text, confidence="weak", field_path=path)]


def _inline_refs_from_dict(value: dict[str, Any], path: str) -> list[EvidenceRef]:
    quotes = _first_string_list(value, ("quote", "evidence_quote", "evidence_quotes", "source_quote", "source_quotes"))
    block_uids = _first_string_list(value, ("source_block_uid", "block_uid", "block_uids"))
    chunk_ids = _first_string_list(value, ("chunk_id", "chunk_ids"))
    if not quotes and not block_uids and not chunk_ids:
        return []
    count = max(len(quotes), len(block_uids), len(chunk_ids), 1)
    refs: list[EvidenceRef] = []
    for index in range(count):
        refs.append(
            EvidenceRef(
                source_type=str(value.get("source_type") or "source_text").strip() or "source_text",
                source_id=str(value.get("source_id") or _pick(chunk_ids, index) or "").strip(),
                chapter_id=_int_or_none(value.get("chapter_id")),
                block_uid=_pick(block_uids, index),
                quote=_pick(quotes, index),
                confidence=str(value.get("confidence") or "weak").strip() or "weak",
                locator=str(value.get("locator") or value.get("location_hint") or "").strip(),
                field_path=path,
            )
        )
    return refs


def _ref_from_dict(value: dict[str, Any], path: str) -> EvidenceRef:
    block_uid = str(
        value.get("block_uid")
        or value.get("source_block_uid")
        or value.get("block")
        or ""
    ).strip()
    quote = str(
        value.get("quote")
        or value.get("evidence_quote")
        or value.get("source_quote")
        or ""
    ).strip()
    return EvidenceRef(
        source_type=str(value.get("source_type") or "source_text").strip() or "source_text",
        source_id=str(value.get("source_id") or value.get("chunk_id") or value.get("fact_id") or "").strip(),
        chapter_id=_int_or_none(value.get("chapter_id")),
        block_uid=block_uid,
        quote=quote,
        confidence=str(value.get("confidence") or "weak").strip() or "weak",
        locator=str(value.get("locator") or value.get("location_hint") or "").strip(),
        field_path=path,
    )


def _first_string_list(value: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        if key in value:
            return _string_list(value.get(key))
    return []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _pick(values: list[str], index: int) -> str:
    if not values:
        return ""
    if index < len(values):
        return values[index]
    return values[-1]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _block_text(block: Any) -> str:
    if block is None:
        return ""
    if isinstance(block, dict):
        return "\n".join(str(block.get(key, "") or "") for key in ("text", "summary", "content_snippet"))
    try:
        return "\n".join(str(block[key] or "") for key in ("text", "summary"))
    except Exception:
        return str(block or "")


def _ref_with_confidence(ref: EvidenceRef, confidence: str) -> EvidenceRef:
    return EvidenceRef(
        source_type=ref.source_type,
        source_id=ref.source_id,
        chapter_id=ref.chapter_id,
        block_uid=ref.block_uid,
        quote=ref.quote,
        confidence=confidence,
        locator=ref.locator,
        field_path=ref.field_path,
    )


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.block_uid, ref.quote, ref.source_id, ref.field_path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped
