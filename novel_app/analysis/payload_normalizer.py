from __future__ import annotations

import json
from typing import Any

from novel_app.structured_templates import (
    BOOK_OUTLINE_FORM_SCHEMA,
    WORLD_FORM_SCHEMA,
    character_profile_schema_for_role,
)

_BOOK_TEXT_KEYS = (
    "book_outline",
    "book_summary",
    "book_card",
    "book_profile",
    "story_summary",
    "summary",
    "作品卡",
    "书籍卡",
    "书籍总结",
)
_BOOK_FORM_KEYS = ("book_outline_form", "book_form", "book_outline_data", "book_card", "作品卡", "书籍卡")
_WORLD_TEXT_KEYS = (
    "world_text",
    "world_summary",
    "worldview_text",
    "world_setting_text",
    "world_card",
    "worldview",
    "world_setting",
    "world_settings",
    "世界卡",
    "世界观",
)
_WORLD_FORM_KEYS = (
    "world_form",
    "world_data",
    "world_fields",
    "worldview_form",
    "world_setting_form",
    "world_card",
    "世界卡",
    "世界观",
)
_CHARACTER_KEYS = (
    "characters",
    "character_cards",
    "character_profiles",
    "character_profile",
    "character_data",
    "people",
    "人物卡",
    "角色卡",
    "人物",
)
_CHAPTER_KEYS = ("chapter_updates", "chapters", "章节更新")


def normalize_book_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map AI/provider aliases into the app's formal writeback schema."""
    if not isinstance(payload, dict):
        return {}
    result: dict[str, Any] = {
        key: value
        for key, value in payload.items()
        if key.startswith("_")
        or key in {
            "analysis_unresolved",
            "source_request",
            "source_requests",
            "verification_request",
            "verification_requests",
        }
    }

    book_field_ids = _schema_field_ids(BOOK_OUTLINE_FORM_SCHEMA)
    book_form = _first_form(payload, _BOOK_FORM_KEYS, book_field_ids)
    if book_form:
        result["book_outline_form"] = book_form
    book_outline = _first_text_payload(payload, _BOOK_TEXT_KEYS, skip_form_like=True, field_ids=book_field_ids)
    if book_outline:
        result["book_outline"] = book_outline

    world_field_ids = _schema_field_ids(WORLD_FORM_SCHEMA)
    world_form = _first_form(payload, _WORLD_FORM_KEYS, world_field_ids)
    if world_form:
        result["world_form"] = world_form
    world_text = _first_text_payload(payload, _WORLD_TEXT_KEYS, skip_form_like=True, field_ids=world_field_ids)
    if world_text:
        result["world_text"] = world_text
    world_entries = payload.get("world_entries") or payload.get("world_cards") or payload.get("世界观条目")
    if isinstance(world_entries, list) and world_entries:
        result["world_entries"] = world_entries

    characters = _character_items(payload)
    if characters:
        result["characters"] = characters

    chapter_updates = _chapter_updates(payload)
    if chapter_updates:
        result["chapter_updates"] = chapter_updates

    return result


def has_unresolved_analysis_items(payload: dict[str, Any]) -> bool:
    value = payload.get("analysis_unresolved")
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    return _has_content(value)


def has_formal_writeback_content(payload: dict[str, Any]) -> bool:
    normalized = normalize_book_analysis_payload(payload)
    for key in ("book_outline", "book_outline_form", "world_form", "world_text", "world_entries", "characters", "chapter_updates"):
        if _has_content(normalized.get(key)):
            return True
    return False


def _schema_field_ids(schema: list[dict[str, Any]]) -> set[str]:
    field_ids: set[str] = set()
    for section in schema:
        for item in section.get("items", []):
            if isinstance(item, dict) and item.get("id"):
                field_ids.add(str(item["id"]))
    return field_ids


def _first_form(payload: dict[str, Any], keys: tuple[str, ...], field_ids: set[str]) -> dict[str, Any]:
    for key in keys:
        form = _coerce_form(payload.get(key), field_ids)
        if form:
            return form
    form = _coerce_form(payload, field_ids)
    return form or {}


def _coerce_form(value: Any, field_ids: set[str]) -> dict[str, Any]:
    parsed = _json_dict(value)
    if not parsed:
        return {}
    if isinstance(parsed.get("fields"), dict) or isinstance(parsed.get("supplements"), list):
        return parsed
    fields: dict[str, Any] = {}
    for key, item in parsed.items():
        if str(key) in field_ids:
            fields[str(key)] = _coerce_field_value(item)
    if fields:
        return {"fields": fields}
    return {}


def _coerce_field_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if "value" in value or "checked" in value:
            return dict(value)
        return {"value": _value_text(value)}
    if isinstance(value, bool):
        return {"checked": value}
    return {"value": str(value or "").strip()}


def _first_text_payload(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    *,
    skip_form_like: bool,
    field_ids: set[str],
) -> str:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
            continue
        parsed = _json_dict(value)
        if parsed:
            if skip_form_like and _coerce_form(parsed, field_ids):
                continue
            text = _dict_text(parsed)
            if text:
                return text
    return ""


def _character_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in _CHARACTER_KEYS:
        value = payload.get(key)
        records = _coerce_character_records(value)
        if records:
            return records
    return []


def _coerce_character_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [_normalize_character_item(item) for item in value if isinstance(item, dict)]
    parsed = _json_dict(value)
    if not parsed:
        return []
    if _looks_like_character_record(parsed):
        return [_normalize_character_item(parsed)]
    records: list[dict[str, Any]] = []
    for name, item in parsed.items():
        if isinstance(item, dict):
            record = dict(item)
            record.setdefault("name", str(name))
            records.append(_normalize_character_item(record))
        else:
            text = str(item or "").strip()
            if text:
                records.append({"name": str(name), "profile_text": text})
    return records


def _normalize_character_item(item: dict[str, Any]) -> dict[str, Any]:
    record = dict(item)
    name = str(record.get("name") or record.get("character_name") or record.get("姓名") or "").strip()
    if name:
        record["name"] = name
    role = str(record.get("role") or record.get("character_role") or record.get("position") or record.get("定位") or "").strip()
    if role:
        record["role"] = role
    if "profile_form" not in record:
        profile_form = _character_profile_form(record, role)
        if profile_form:
            record["profile_form"] = profile_form
    if "profile_text" not in record:
        text = _character_profile_text(record)
        if text:
            record["profile_text"] = text
    return record


def _character_profile_form(item: dict[str, Any], role: str) -> dict[str, Any]:
    schema_key = str(item.get("schema") or item.get("profile_schema") or "")
    field_ids = _schema_field_ids(character_profile_schema_for_role(role, schema_key))
    for key in ("character_form", "character_profile_form", "profile_form", "profile_data", "profile_data_json", "profile_fields", "fields", "form"):
        form = _coerce_form(item.get(key), field_ids)
        if form:
            return form
    return _coerce_form(item, field_ids)


def _character_profile_text(item: dict[str, Any]) -> str:
    for key in ("profile_text", "profile_markdown", "markdown", "content", "description", "summary", "profile"):
        value = item.get(key)
        if isinstance(value, (dict, list, tuple)):
            continue
        text = str(value or "").strip()
        if text:
            return text
    generic = {
        key: value
        for key, value in item.items()
        if key
        not in {
            "name",
            "character_name",
            "role",
            "character_role",
            "profile_form",
            "character_profile_form",
            "profile_data",
            "fields",
        }
    }
    return _dict_text(generic)


def _looks_like_character_record(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "name",
            "character_name",
            "姓名",
            "role",
            "profile_text",
            "profile_form",
            "character_profile_form",
            "profile_data",
            "fields",
        )
    )


def _chapter_updates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in _CHAPTER_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dict_text(value: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, item in value.items():
        if item in (None, "", [], {}):
            continue
        lines.append(f"{key}: {_value_text(item)}")
    return "\n".join(lines).strip()


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "").strip()


def _has_content(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    return True
