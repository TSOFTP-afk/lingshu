from __future__ import annotations

from novel_app.analysis.probe_planner import SUPPORTED_PROBE_TYPES, ProbePlanner


def test_probe_planner_generates_four_probe_types_with_stable_evidence() -> None:
    facts = [
        _fact("F-foreshadow", "E-hero", "foreshadowing", 1, "Lin Yi finds a hidden clue."),
        _fact("F-payoff", "E-hero", "event", 5, "The hidden clue reveals the gate answer."),
        _fact("F-state", "E-hero", "state", 1, "Lin Yi is alive."),
        _fact("F-state-next", "E-hero", "state", 3, "Lin Yi is awake."),
        _fact("F-rule", "E-world", "world_rule", 2, "The gate cannot open without blood.", memory_type="foundation"),
        _fact("F-rule-next", "E-world", "world_rule", 6, "The gate cannot open without blood during eclipse.", memory_type="foundation"),
        _fact("F-relation", "E-hero", "relation", 2, "Lin Yi helps Mei."),
        _fact("F-relation-next", "E-hero", "relation", 4, "Mei helps Lin Yi."),
    ]
    entities = [
        {"entity_uid": "E-hero", "canonical_name": "Lin Yi", "entity_type": "character"},
        {"entity_uid": "E-world", "canonical_name": "Gate Rule", "entity_type": "concept"},
    ]

    planner = ProbePlanner()
    first = planner.plan(book_id=1, run_id=2, facts=facts, entities=entities)
    second = planner.plan(book_id=1, run_id=2, facts=facts, entities=entities)

    assert {item["probe_type"] for item in first} == SUPPORTED_PROBE_TYPES
    assert [item["probe_uid"] for item in first] == [item["probe_uid"] for item in second]
    assert all(item["plan"]["source_evidence"] for item in first)
    assert all("target_evidence" in item["plan"] for item in first)
    assert all(item["plan"]["metadata"]["formal_writeback"] is False for item in first)


def _fact(
    fact_uid: str,
    entity_uid: str,
    fact_type: str,
    chapter_id: int,
    quote_text: str,
    *,
    memory_type: str = "evidence",
) -> dict:
    return {
        "fact_uid": fact_uid,
        "subject_entity_uid": entity_uid,
        "fact_type": fact_type,
        "value": {"summary": quote_text, "subject_name": entity_uid},
        "quote_text": quote_text,
        "chapter_id": chapter_id,
        "block_uid": f"B-{chapter_id}",
        "confidence": 0.8,
        "memory_scope": "long_term" if chapter_id < 4 else "short_term",
        "memory_importance": "high",
        "memory_type": memory_type,
        "importance_score": 0.8,
        "status": "candidate",
        "metadata": {},
    }
