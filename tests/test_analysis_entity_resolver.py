from __future__ import annotations

from novel_app.analysis.entity_resolver import EntityResolver, normalize_entity_alias, stable_entity_uid


def test_entity_resolver_merges_character_aliases_and_scopes_uids_to_book() -> None:
    payload = {
        "character_cards": [
            {"name": "Lin", "aliases": ["L.", "The Mapkeeper"], "role": "lead"},
            {"name": "The Mapkeeper", "alias": "Lin", "role": "lead"},
        ],
        "locations": [{"name": "Harbor Gate", "category": "location"}],
        "chapter_updates": [{"entity_name": "Map Guild", "entity_type": "organization"}],
    }

    result = EntityResolver().resolve(payload, book_id=42)
    character_entities = result.entities_by_type("character")

    assert len(character_entities) == 1
    assert character_entities[0].entity_uid.startswith("BOOK-42::ENT-P-")
    assert result.entity_uid_for("L.") == character_entities[0].entity_uid
    assert result.entity_uid_for("The Mapkeeper") == character_entities[0].entity_uid
    assert result.entity_uid_for("Harbor Gate", "location").startswith("BOOK-42::ENT-L-")
    assert result.entity_uid_for("Map Guild", "organization").startswith("BOOK-42::ENT-O-")


def test_stable_entity_uid_is_deterministic_and_type_aware() -> None:
    first = stable_entity_uid("character", "Lin", book_id=7)
    second = stable_entity_uid("character", " Lin ", book_id=7)
    world = stable_entity_uid("world", "Lin", book_id=7)

    assert first == second
    assert first != world
    assert first.startswith("BOOK-7::ENT-P-")
    assert normalize_entity_alias("The Map-keeper!") == "themapkeeper"
