from __future__ import annotations

from novel_app.analysis.evidence import (
    evidence_gate_result,
    evidence_summary,
    extract_evidence_refs,
    has_direct_evidence,
    has_evidence,
    resolve_evidence_refs,
)


def test_evidence_summary_classifies_trusted_payload() -> None:
    payload = {
        "characters": [
            {
                "name": "Lin",
                "profile_text": "keeps the hidden map",
                "evidence_quote": "Lin folded the map into his sleeve.",
                "chunk_id": "chunk-0002",
            }
        ]
    }

    summary = evidence_summary(payload)

    assert summary["status"] == "trusted"
    assert summary["evidence_fields"] == 2
    assert summary["quote_fields"] == 1
    assert summary["chunk_or_block_fields"] == 1
    assert has_evidence(payload)
    assert not has_direct_evidence(payload)


def test_evidence_gate_reports_weak_when_unresolved_or_dropped() -> None:
    result = evidence_gate_result(
        {
            "analysis_unresolved": [{"field": "origin"}],
            "_meta": {"evidence_gate_dropped": 2},
        }
    )

    assert result.status == "weak"
    assert result.unresolved_count == 1
    assert result.dropped_by_gate == 2


def test_evidence_refs_resolve_against_analysis_blocks() -> None:
    payload = {
        "characters": [
            {
                "name": "Lin",
                "source_block_uid": "analysis-chapter-1-part-001",
                "evidence_quote": "folded the map",
            }
        ]
    }

    refs = extract_evidence_refs(payload)
    resolution = resolve_evidence_refs(
        payload,
        lambda block_uid: {"text": "Lin folded the map into his sleeve."}
        if block_uid == "analysis-chapter-1-part-001"
        else None,
    )

    assert len(refs) == 1
    assert refs[0].block_uid == "analysis-chapter-1-part-001"
    assert resolution.status == "trusted"
    assert resolution.trusted_refs == 1


def test_inline_block_quote_takes_precedence_over_fact_id_refs() -> None:
    payload = {
        "field": {
            "value": "hidden map",
            "evidence_refs": ["fact-1"],
            "source_block_uid": "analysis-chapter-1-part-001",
            "source_quote": "folded the map",
        }
    }

    resolution = resolve_evidence_refs(
        payload,
        lambda _block_uid: {"text": "Lin folded the map into his sleeve."},
    )

    assert resolution.status == "trusted"
    assert resolution.trusted_refs == 1
    assert resolution.weak_refs == 0


def test_evidence_refs_report_missing_or_weak_locations() -> None:
    missing = resolve_evidence_refs(
        {"source_block_uid": "missing-block", "evidence_quote": "not here"},
        lambda _block_uid: None,
    )
    weak = resolve_evidence_refs(
        {"source_block_uid": "block-1", "evidence_quote": "not here"},
        lambda _block_uid: {"text": "different text"},
    )

    assert missing.status == "missing"
    assert missing.missing_refs == 1
    assert weak.status == "weak"
    assert weak.quote_mismatches == 1
