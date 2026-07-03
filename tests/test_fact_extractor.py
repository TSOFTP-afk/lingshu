from __future__ import annotations

from novel_app.analysis.fact_extractor import FactExtractor


def test_fact_extractor_builds_stable_quote_backed_facts() -> None:
    content = "林一进入城市。\n\n林一留下《星火伏笔》。"
    blocks = [
        {
            "block_uid": "analysis-v3-chapter-1-part-0001",
            "chapter_id": 1,
            "char_start": 0,
            "char_end": len(content),
            "text": content,
        }
    ]
    mentions = [
        {
            "mention_uid": "m1",
            "entity_uid": "BOOK-1::ENT-P-LINYI",
            "entity_type": "character",
            "quote_text": "林一",
            "chapter_id": 1,
            "block_uid": "analysis-v3-chapter-1-part-0001",
            "char_start": 0,
            "char_end": 2,
            "confidence": 0.9,
            "source_rule": "formal_character",
        },
        {
            "mention_uid": "m2",
            "entity_uid": "BOOK-1::ENT-P-LINYI",
            "entity_type": "character",
            "quote_text": "林一",
            "chapter_id": 1,
            "block_uid": "analysis-v3-chapter-1-part-0001",
            "char_start": content.rfind("林一"),
            "char_end": content.rfind("林一") + 2,
            "confidence": 0.9,
            "source_rule": "formal_character",
        },
    ]
    entities = [
        {
            "entity_uid": "BOOK-1::ENT-P-LINYI",
            "entity_type": "character",
            "canonical_name": "林一",
            "confidence": 0.9,
        }
    ]

    first = FactExtractor().extract_from_context(book_id=1, run_id=9, blocks=blocks, mentions=mentions, entities=entities)
    second = FactExtractor().extract_from_context(book_id=1, run_id=9, blocks=blocks, mentions=mentions, entities=entities)

    assert [item.fact_uid for item in first] == [item.fact_uid for item in second]
    assert len(first) == 2
    assert {item.fact_type for item in first} == {"event", "foreshadowing"}
    for fact in first:
        assert fact.subject_entity_uid == "BOOK-1::ENT-P-LINYI"
        assert fact.quote_text in content
        assert fact.value["subject_name"] == "林一"
        assert fact.confidence >= 0.55
        assert fact.status == "candidate"
        assert fact.metadata["char_start"] >= 0


def test_fact_extractor_rejects_unbound_or_unverifiable_mentions() -> None:
    blocks = [
        {
            "block_uid": "b1",
            "chapter_id": 1,
            "char_start": 0,
            "char_end": 6,
            "text": "林一出现。",
        }
    ]
    entities = [{"entity_uid": "e1", "canonical_name": "林一", "confidence": 0.9}]
    mentions = [
        {
            "mention_uid": "missing-entity",
            "entity_uid": "",
            "quote_text": "林一",
            "block_uid": "b1",
            "char_start": 0,
            "char_end": 2,
            "confidence": 0.9,
        },
        {
            "mention_uid": "bad-quote",
            "entity_uid": "e1",
            "quote_text": "不存在",
            "block_uid": "b1",
            "char_start": 0,
            "char_end": 3,
            "confidence": 0.9,
        },
    ]

    assert FactExtractor().extract_from_context(book_id=1, run_id=1, blocks=blocks, mentions=mentions, entities=entities) == []
