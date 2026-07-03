from __future__ import annotations

from novel_app.analysis.memory_classifier import MemoryClassifier
from novel_app.analysis.memory_compressor import MemoryCompressor
from novel_app.analysis.memory_window import MemoryWindowBuilder


def _fact(index: int, *, fact_type: str = "event", confidence: float = 0.7) -> dict:
    return {
        "fact_uid": f"FACT-{index}",
        "subject_entity_uid": "ENT-1",
        "fact_type": fact_type,
        "value": {"summary": f"fact {index}", "subject_name": "林一"},
        "quote_text": f"林一事件 {index}。",
        "chapter_id": index,
        "block_uid": f"block-{index}",
        "confidence": confidence,
        "status": "candidate",
        "metadata": {},
    }


def test_memory_classifier_marks_recent_facts_short_term_and_foundation_high() -> None:
    facts = [_fact(1), _fact(2), _fact(3, fact_type="world_rule"), _fact(4, fact_type="foreshadowing")]

    classified = MemoryClassifier(short_term_chapter_window=2).classify_facts(facts)
    by_uid = {fact["fact_uid"]: fact for fact in classified}

    assert by_uid["FACT-1"]["memory_scope"] == "long_term"
    assert by_uid["FACT-1"]["memory_type"] == "cache"
    assert by_uid["FACT-3"]["memory_scope"] == "short_term"
    assert by_uid["FACT-3"]["memory_type"] == "foundation"
    assert by_uid["FACT-3"]["memory_importance"] == "high"
    assert by_uid["FACT-4"]["memory_type"] == "evidence"
    assert by_uid["FACT-4"]["memory_importance"] == "high"
    assert by_uid["FACT-4"]["metadata"]["memory_classification"]["never_compress"] is True


def test_memory_window_selects_recent_foundation_and_high_importance_context() -> None:
    classified = MemoryClassifier(short_term_chapter_window=2).classify_facts(
        [
            _fact(1),
            _fact(2, fact_type="world_rule"),
            _fact(3),
            _fact(4, fact_type="foreshadowing"),
        ]
    )

    selected = MemoryWindowBuilder(short_term_chapter_window=2).select_context_facts(classified)
    selected_uids = {fact["fact_uid"] for fact in selected}

    assert "FACT-1" not in selected_uids
    assert {"FACT-2", "FACT-3", "FACT-4"}.issubset(selected_uids)


def test_memory_compressor_preserves_source_facts_and_adds_summary_with_source_links() -> None:
    facts = MemoryClassifier(short_term_chapter_window=2).classify_facts([_fact(i) for i in range(1, 7)])

    compressed = MemoryCompressor(cache_threshold=3).compress(facts)
    summaries = [fact for fact in compressed if fact["fact_type"] == "memory_summary"]
    source_facts = [fact for fact in compressed if fact["fact_type"] != "memory_summary"]

    assert len(source_facts) == 6
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["memory_type"] == "summary_cache"
    assert summary["memory_scope"] == "long_term"
    assert summary["metadata"]["source_fact_uids"] == ["FACT-1", "FACT-2", "FACT-3", "FACT-4"]
    assert summary["value"]["source_fact_uids"] == ["FACT-1", "FACT-2", "FACT-3", "FACT-4"]
