from __future__ import annotations

from novel_app.analysis.coreference import CoreferenceResolver


def test_coreference_groups_mentions_by_type_and_normalized_text() -> None:
    mentions = [
        {
            "mention_uid": "m1",
            "entity_type": "character",
            "normalized_text": "林一",
            "quote_text": "林一",
            "confidence": 0.9,
            "source_rule": "formal_character",
        },
        {
            "mention_uid": "m2",
            "entity_type": "character",
            "normalized_text": "林 一",
            "quote_text": "林一",
            "confidence": 0.8,
            "source_rule": "suffix_pattern",
        },
        {
            "mention_uid": "m3",
            "entity_type": "concept",
            "normalized_text": "林一",
            "quote_text": "林一",
            "confidence": 0.7,
            "source_rule": "quoted_title",
        },
    ]

    first = CoreferenceResolver().resolve_mentions(book_id=3, mentions=mentions)
    second = CoreferenceResolver().resolve_mentions(book_id=3, mentions=mentions)

    assert [item.entity_uid for item in first] == [item.entity_uid for item in second]
    assert len(first) == 2
    character = next(item for item in first if item.entity_type == "character")
    concept = next(item for item in first if item.entity_type == "concept")
    assert character.canonical_name == "林一"
    assert character.mention_uids == ("m1", "m2")
    assert character.confidence == 0.85
    assert character.metadata["mention_count"] == 2
    assert concept.mention_uids == ("m3",)
