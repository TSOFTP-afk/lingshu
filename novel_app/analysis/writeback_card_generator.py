"""LLM refinement layer for V3 writeback cards.

This module sits between the V3 writeback schema gate and the actual
business-table mutation. It turns mechanically assembled card facts into the
target writeback fields expected by character, world-entry, and book writes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from novel_app.database import Database


SYSTEM_PROMPT_WRITEBACK_CARD = """你是一名专业的长篇小说设定整理助手。你的任务是把自动分析卡片转换为正式写回字段。

规则：
- 只返回纯 JSON 对象，不要 Markdown、注释或解释。
- 只能依据输入 facts、summary 与已有业务数据整理，不要编造未被支持的剧情。
- 不要重复已有业务数据；如果已有内容已经包含某信息，请只补充新信息。
- 保持输出字段简洁、可直接写入正式资料库。
- 人物和世界条目的 name 必须保持输入中的原始目标名，不要改名。
- character 输出字段：name, role, profile_text。
- world_entry 输出字段：name, category, content_text。
- book 输出字段：outline_text, world_text。
"""


TARGET_FIELD_NAMES: dict[str, tuple[str, ...]] = {
    "character": ("name", "role", "profile_text"),
    "world_entry": ("name", "category", "content_text"),
    "book": ("outline_text", "world_text"),
}


class WritebackCardGenerationError(RuntimeError):
    """Raised when LLM writeback refinement cannot produce safe fields."""


@dataclass(frozen=True)
class WritebackCardGenerationResult:
    """Refined fields and trace metadata returned by the LLM layer."""

    target: str
    fields: dict[str, Any]
    metadata: dict[str, Any]


class WritebackCardGenerator:
    """Generate polished writeback fields from a V3 analysis card."""

    PROMPT_VERSION = "writeback_card_generator_v1"
    SCHEMA_VERSION = "analysis_v3_writeback_card_v1"

    def __init__(self, ai_provider: Any) -> None:
        self.ai_provider = ai_provider

    def generate(
        self,
        database: Database,
        book_id: int,
        card: dict[str, Any],
        *,
        payload: dict[str, Any] | None = None,
    ) -> WritebackCardGenerationResult:
        payload = payload if isinstance(payload, dict) else _extract_payload(card)
        if not payload:
            raise WritebackCardGenerationError("卡片无 payload，无法生成写回字段")

        target = str(payload.get("writeback_target") or "").strip()
        if target not in TARGET_FIELD_NAMES:
            raise WritebackCardGenerationError(f"不支持的写回目标: {target or 'empty'}")

        original_fields = payload.get("writeback_fields")
        if not isinstance(original_fields, dict):
            raise WritebackCardGenerationError("writeback_fields 不是字典")
        original_fields = dict(original_fields)

        input_payload = self._build_input_payload(database, int(book_id), card, payload, target, original_fields)
        output = self.ai_provider._call_llm(
            stage="writeback_card_generator",
            input_payload=input_payload,
            system_prompt=SYSTEM_PROMPT_WRITEBACK_CARD,
            user_prompt=self._build_user_prompt(target, input_payload),
            temperature=0.15,
        )

        fields = self._normalize_output(target, original_fields, output)
        metadata = {
            "used": True,
            "source": "llm",
            "generator": self.__class__.__name__,
            "prompt_version": self.PROMPT_VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "target": target,
            "card_uid": str(card.get("card_uid") or ""),
            "original_writeback_fields": original_fields,
            "changed_fields": sorted(
                key for key, value in fields.items()
                if str(original_fields.get(key) or "") != str(value or "")
            ),
        }
        return WritebackCardGenerationResult(target=target, fields=fields, metadata=metadata)

    def _build_input_payload(
        self,
        database: Database,
        book_id: int,
        card: dict[str, Any],
        payload: dict[str, Any],
        target: str,
        original_fields: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "prompt_version": self.PROMPT_VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "book_id": book_id,
            "target": target,
            "card": {
                "card_uid": str(card.get("card_uid") or ""),
                "card_type": str(card.get("card_type") or payload.get("card_type") or ""),
                "entity_uid": str(card.get("entity_uid") or payload.get("entity_uid") or ""),
                "title": str(payload.get("title") or ""),
                "name": str(payload.get("name") or ""),
                "entity_type": str(payload.get("entity_type") or ""),
                "summary": str(payload.get("summary") or ""),
                "fact_count": int(payload.get("fact_count") or 0),
                "facts": _compact_facts(payload.get("facts")),
            },
            "original_writeback_fields": original_fields,
            "existing_business_data": _existing_business_data(database, book_id, target, original_fields),
            "novel_context": _novel_context(database, book_id),
        }

    @staticmethod
    def _build_user_prompt(target: str, input_payload: dict[str, Any]) -> str:
        if target == "character":
            instruction = (
                "请整合 facts 为 1-3 句连贯人物简介，推断 role，profile_text 不要重复已有 profile。"
            )
        elif target == "world_entry":
            instruction = (
                "请整合 facts 为结构化世界观条目。地点写地理和背景，概念写定义和规则，内容用于追加到已有 content。"
            )
        else:
            instruction = (
                "请按章节时间线组织 outline_text，并把 world_rule 类事实整理为 world_text。"
            )
        return (
            f"目标类型：{target}\n"
            f"任务要求：{instruction}\n"
            f"输入 JSON：\n{json.dumps(input_payload, ensure_ascii=False, sort_keys=True)}"
        )

    def _normalize_output(
        self,
        target: str,
        original_fields: dict[str, Any],
        output: Any,
    ) -> dict[str, Any]:
        raw_fields = _output_fields(output)
        if target == "character":
            name = str(original_fields.get("name") or "").strip()
            role = str(raw_fields.get("role") or original_fields.get("role") or "").strip()
            profile_text = str(raw_fields.get("profile_text") or "").strip()
            if not name:
                raise WritebackCardGenerationError("人物写回缺少原始 name")
            if not profile_text:
                raise WritebackCardGenerationError("LLM 未生成 profile_text")
            return {
                "name": name,
                "role": role[:120],
                "profile_text": profile_text,
            }

        if target == "world_entry":
            name = str(original_fields.get("name") or "").strip()
            category = str(raw_fields.get("category") or original_fields.get("category") or "").strip()
            content_text = str(raw_fields.get("content_text") or "").strip()
            if not name:
                raise WritebackCardGenerationError("世界观写回缺少原始 name")
            if not category:
                raise WritebackCardGenerationError("LLM 未生成 category")
            if not content_text:
                raise WritebackCardGenerationError("LLM 未生成 content_text")
            return {
                "name": name,
                "category": category[:80],
                "content_text": content_text,
            }

        if target == "book":
            outline_text = str(raw_fields.get("outline_text") or "").strip()
            world_text = str(raw_fields.get("world_text") or "").strip()
            if not outline_text and not world_text:
                raise WritebackCardGenerationError("LLM 未生成 outline_text 或 world_text")
            return {
                "outline_text": outline_text,
                "world_text": world_text,
            }

        raise WritebackCardGenerationError(f"不支持的写回目标: {target}")


def _output_fields(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        raise WritebackCardGenerationError(f"LLM 返回非 JSON 对象: {type(output).__name__}")
    nested = output.get("writeback_fields")
    if isinstance(nested, dict):
        return nested
    return output


def _compact_facts(raw_facts: Any, *, limit: int = 80) -> list[dict[str, Any]]:
    if not isinstance(raw_facts, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in raw_facts[:limit]:
        if not isinstance(item, dict):
            continue
        value = item.get("value") if isinstance(item.get("value"), dict) else {}
        compact.append({
            "fact_uid": str(item.get("fact_uid") or ""),
            "fact_type": str(item.get("fact_type") or ""),
            "summary": str(value.get("summary") or item.get("summary") or "")[:300],
            "quote_text": str(item.get("quote_text") or "")[:300],
            "chapter_id": item.get("chapter_id"),
            "block_uid": str(item.get("block_uid") or ""),
            "confidence": item.get("confidence"),
        })
    return compact


def _existing_business_data(
    database: Database,
    book_id: int,
    target: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if target == "character":
        character = _find_character_by_name(database, book_id, str(fields.get("name") or ""))
        if not character:
            return {}
        data = _row_to_dict(character)
        character_id = _safe_int(data.get("id"))
        if character_id is not None:
            try:
                data["profile_form"] = database.get_character_profile_form(character_id)
            except Exception:
                pass
        return _trim_dict(data)

    if target == "world_entry":
        entry = _find_world_entry_by_name(database, book_id, str(fields.get("name") or ""))
        return _trim_dict(_row_to_dict(entry)) if entry else {}

    if target == "book":
        book = database.get_book(book_id)
        data = _row_to_dict(book)
        return {
            "title": str(data.get("title") or ""),
            "outline_text": str(data.get("outline_text") or "")[:6000],
            "world_text": str(data.get("world_text") or "")[:6000],
        }

    return {}


def _novel_context(database: Database, book_id: int) -> dict[str, Any]:
    book = _row_to_dict(database.get_book(book_id))
    try:
        chapters = database.list_chapters(book_id)
    except Exception:
        chapters = []
    chapter_titles = [str(_row_value(chapter, "title") or "") for chapter in chapters]
    return {
        "title": str(book.get("title") or ""),
        "chapter_count": len(chapters),
        "first_chapter_title": chapter_titles[0] if chapter_titles else "",
        "last_chapter_title": chapter_titles[-1] if chapter_titles else "",
    }


def _extract_payload(card: dict[str, Any]) -> dict[str, Any] | None:
    payload = card.get("payload")
    if isinstance(payload, dict):
        return payload
    payload_json = card.get("payload_json")
    if isinstance(payload_json, str) and payload_json:
        try:
            loaded = json.loads(payload_json)
        except (TypeError, ValueError):
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


def _find_character_by_name(database: Database, book_id: int, name: str) -> Any | None:
    clean_name = str(name or "").strip()
    if not clean_name:
        return None
    if hasattr(database, "get_character_by_name"):
        return database.get_character_by_name(book_id, clean_name)
    for character in database.list_characters(book_id):
        if str(_row_value(character, "name") or "").strip() == clean_name:
            return character
    return None


def _find_world_entry_by_name(database: Database, book_id: int, name: str) -> Any | None:
    clean_name = str(name or "").strip()
    if not clean_name:
        return None
    if hasattr(database, "get_world_entry_by_name"):
        return database.get_world_entry_by_name(book_id, clean_name)
    for entry in database.list_world_entries(book_id):
        if str(_row_value(entry, "name") or "").strip() == clean_name:
            return entry
    return None


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return {key: row[key] for key in row.keys()}
    except Exception:
        return {}


def _trim_dict(data: dict[str, Any], *, max_chars: int = 6000) -> dict[str, Any]:
    trimmed: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            trimmed[key] = value[:max_chars]
        else:
            trimmed[key] = value
    return trimmed


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
