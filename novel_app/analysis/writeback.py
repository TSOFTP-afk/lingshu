from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from novel_app.analysis.evidence import has_direct_evidence, has_evidence
from novel_app.analysis.json_safety import safe_json_loads
from novel_app.analysis.models import AnalysisWritebackResult
from novel_app.analysis.payload_normalizer import normalize_book_analysis_payload
from novel_app.structured_templates import (
    WORLD_FORM_SCHEMA,
    book_outline_form_defaults,
    book_outline_markdown_to_form,
    character_profile_form_defaults,
    character_profile_markdown_to_form,
    character_profile_schema_for_role,
    merge_book_outline_supplement,
    normalize_book_outline_form,
    normalize_character_profile_form,
    normalize_world_form,
    world_markdown_to_form,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from novel_app.database import Database


def _verify_book_chapter_ownership(
    database: "Database",
    book_id: int,
    payload: dict[str, Any],
    user_id: int | None,
) -> None:
    """服务端所有权校验（V5-L04）。

    1. 若提供 user_id，校验 book_id 归属当前用户；
    2. 校验 payload 中所有 chapter_id 反查的 book_id 与传入 book_id 一致，
       防止攻击者在 chapter_updates 中混入其他书籍的章节 ID。
    校验失败抛 ValueError。
    """
    if user_id is not None:
        if not database.check_book_ownership(book_id, user_id):
            raise ValueError(f"用户 {user_id} 无权操作书籍 {book_id}")
    chapter_items = payload.get("chapter_updates", [])
    if not isinstance(chapter_items, list):
        return
    for item in chapter_items:
        if not isinstance(item, dict):
            continue
        raw_chapter_id = item.get("chapter_id")
        if raw_chapter_id is None:
            continue
        try:
            chapter_id = int(raw_chapter_id)
        except (TypeError, ValueError):
            continue
        chapter = database.get_chapter(chapter_id)
        if not chapter:
            raise ValueError(f"章节 {chapter_id} 不存在")
        if int(chapter["book_id"]) != book_id:
            raise ValueError(
                f"章节 {chapter_id} 不属于书籍 {book_id}（实际属于 {chapter['book_id']}）"
            )


def apply_book_analysis_payload(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    *,
    allow_weak_evidence: bool = False,
    requires_evidence: bool | None = None,
    verify_ownership: bool = True,
    user_id: int | None = None,
) -> AnalysisWritebackResult:
    payload = normalize_book_analysis_payload(payload)
    resolved_requires_evidence = book_analysis_requires_evidence(payload) if requires_evidence is None else bool(requires_evidence)
    if resolved_requires_evidence and not allow_weak_evidence:
        payload = filter_untrusted_book_analysis_payload(payload, requires_evidence=True)

    if verify_ownership:
        _verify_book_chapter_ownership(database, book_id, payload, user_id)

    updated_chapter_ids: set[int] = set()
    with database.transaction():
        _writeback_book_outline(database, book_id, payload, resolved_requires_evidence)
        _writeback_characters(database, book_id, payload, resolved_requires_evidence)
        _writeback_world(database, book_id, payload, resolved_requires_evidence)
        updated_chapter_ids = _writeback_chapters(database, book_id, payload)

    meta = payload.get("_meta", {}) if isinstance(payload.get("_meta", {}), dict) else {}
    unresolved_items = payload.get("analysis_unresolved", [])
    chapter_items = payload.get("chapter_updates", [])
    return AnalysisWritebackResult(
        updated_chapter_ids=updated_chapter_ids,
        processed_chapters=int(meta.get("processed_chapters", 0) or 0) or len(chapter_items if isinstance(chapter_items, list) else []),
        unresolved_count=len(unresolved_items) if isinstance(unresolved_items, list) else 0,
        evidence_gate_dropped=int(meta.get("evidence_gate_dropped", 0) or 0),
    )


def _writeback_book_outline(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    requires_evidence: bool,
) -> None:
    """写回书籍大纲到 books.outline_text / outline_data_json。"""
    book = database.get_book(book_id)
    book_title = str(book["title"] or "") if book else ""
    book_outline = str(payload.get("book_outline", "") or "").strip()
    if not book:
        return
    volume_specs = database._book_outline_volume_specs(book_id)
    outline_form = payload.get("book_outline_form")
    if isinstance(outline_form, dict):
        if requires_evidence:
            outline_data = overlay_sparse_analysis_form(database.get_book_outline_form(book_id), outline_form)
        else:
            outline_data = outline_form
        outline_data = normalize_book_outline_form(outline_data, book_title, volume_specs)
    elif book_outline:
        if "# 书籍级模板" in book_outline or "# 书籍大纲模板" in book_outline or "## 1." in book_outline:
            outline_data = book_outline_markdown_to_form(book_outline, book_title, volume_specs)
        else:
            outline_data = merge_book_outline_supplement(
                book_outline_form_defaults(book_title, volume_specs),
                book_title,
                book_outline,
                supplement_title=f"AI分析覆盖 · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )
    else:
        outline_data = database.get_book_outline_form(book_id)
    database.update_book_outline_form(book_id, normalize_book_outline_form(outline_data, book_title, volume_specs))


# V1 人物卡 → 状态机 facts 提取映射
# item 中常见字段名 → fact_type 关键词（须命中 state_machine_writeback._FACT_TO_AXIS_MAP 的 keywords）
_CHARACTER_FACT_FIELD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("motivation", "desire", "欲望", "执念", "目标", "动机"), "motivation"),
    (("fear", "恐惧", "害怕", "畏惧"), "fear"),
    (("strategy", "cognition", "认知", "策略", "行动模式", "行事"), "cognition strategy"),
    (("blindspot", "盲点", "忽略", "盲区"), "blindspot"),
    (("limitation", "fate", "命理", "约束", "悖论", "代价", "宿命"), "fate limitation"),
    (("belief", "信条", "底线", "道德", "信念"), "belief"),
]


def _extract_facts_from_character_item(item: dict[str, Any], profile_text: str) -> list[dict]:
    """从 V1 人物卡 item 中提取 facts，供状态机写回使用。

    提取顺序：
    1. item["facts"]（若为 list 则直接用）
    2. 按 _CHARACTER_FACT_FIELD_MAP 从 item 提取结构化字段，构造带 fact_type 的 facts
    3. 兜底：用 profile_text 作为 analysis_summary
    """
    raw_facts = item.get("facts")
    if isinstance(raw_facts, list):
        facts = [f for f in raw_facts if isinstance(f, dict)]
        if facts:
            return facts

    facts: list[dict] = []
    for keys, fact_type in _CHARACTER_FACT_FIELD_MAP:
        for key in keys:
            if key in item:
                value = item.get(key)
                if isinstance(value, (dict, list, tuple)):
                    continue
                text = str(value or "").strip()
                if text:
                    facts.append({"fact_type": fact_type, "content": text})
                    break

    if not facts and profile_text:
        facts.append({"fact_type": "analysis_summary", "content": profile_text})
    return facts


def _writeback_characters(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    requires_evidence: bool,
) -> None:
    """写回人物到 characters 表（新建或更新 profile）+ 同步人物状态机。

    与 V3 路径（v3_writeback._writeback_character）保持一致：
    在 update_character_form 之前调用 writeback_to_state_machine，将分析 facts
    映射到状态机三轴字段与循环日志。状态机写回失败时降级，不影响主流程。
    """
    from novel_app.analysis.state_machine_writeback import writeback_to_state_machine

    existing_characters = {
        str(item["name"]).strip(): int(item["id"])
        for item in database.list_characters(book_id)
        if str(item["name"]).strip()
    }
    for item in analysis_character_items(payload):
        name = analysis_first_text(item, ("name", "character_name", "姓名", "角色名"))
        if not name:
            continue
        role = analysis_first_text(item, ("role", "character_role", "position", "定位", "角色定位"))
        profile = analysis_character_profile_text(item)
        character_id = existing_characters.get(name)
        if character_id is None:
            character_id = database.create_character(book_id, name)
            existing_characters[name] = character_id
        else:
            existing = database.get_character(character_id)
            if existing:
                role = role or str(existing["role"] or "")
        profile_form = analysis_character_profile_form(item, role)
        if isinstance(profile_form, dict):
            if requires_evidence:
                profile_data = overlay_sparse_analysis_form(database.get_character_profile_form(character_id), profile_form)
            else:
                profile_data = profile_form
            profile_data = normalize_character_profile_form(profile_data, name, role)
        elif profile:
            profile_data = character_profile_markdown_to_form(profile, name, role)
        else:
            profile_data = character_profile_form_defaults(name, role)

        # 状态机写回（与 V3 路径一致）— 失败时降级，不影响主流程
        facts = _extract_facts_from_character_item(item, profile)
        try:
            sm_result = writeback_to_state_machine(database, book_id, character_id, facts)
            if sm_result.get("axis_updates"):
                logger.info(
                    "V1 写回状态机 character_id=%s 字段=%s cycle_id=%s",
                    character_id, list(sm_result["axis_updates"].keys()),
                    sm_result.get("cycle_id"),
                )
        except Exception as exc:
            logger.warning(
                "V1 写回状态机失败 character_id=%s，降级跳过: %s",
                character_id, exc,
            )

        database.update_character_form(character_id, name, role, profile_data, image_path=None)


def _writeback_world(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
    requires_evidence: bool,
) -> None:
    """写回世界观到 books.world_text / world_data_json。"""
    world_form = analysis_world_form(payload)
    world_text = analysis_world_text(payload)
    world_entries = payload.get("world_entries", [])
    if isinstance(world_form, dict):
        if requires_evidence:
            world_data = overlay_sparse_analysis_form(database.get_book_world_form(book_id), world_form)
        else:
            world_data = world_form
        world_data = normalize_world_form(world_data)
    elif world_text or (isinstance(world_entries, list) and world_entries):
        combined_world_parts: list[str] = []
        if world_text:
            combined_world_parts.append(world_text)
        if isinstance(world_entries, list):
            for entry in world_entries:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("name") or entry.get("title") or entry.get("category") or "世界观").strip()
                content = str(entry.get("content") or entry.get("description") or "").strip()
                if content:
                    combined_world_parts.append(f"## {title}\n{content}")
        world_data = world_markdown_to_form("\n\n".join(combined_world_parts))
    else:
        world_data = database.get_book_world_form(book_id)
    database.update_book_world_form(book_id, world_data)


def _writeback_chapters(
    database: Database,
    book_id: int,
    payload: dict[str, Any],
) -> set[int]:
    """写回章节大纲和事件，返回已更新章节 ID 集合。"""
    chapter_items = payload.get("chapter_updates", [])
    if not isinstance(chapter_items, list):
        chapter_items = []
    updated_chapter_ids: set[int] = set()
    existing_events: dict[int, list[int]] = {}
    for event in database.list_chapter_events(book_id):
        existing_events.setdefault(int(event["chapter_id"]), []).append(int(event["id"]))

    for item in chapter_items:
        if not isinstance(item, dict):
            continue
        try:
            chapter_id = int(item.get("chapter_id"))
        except (TypeError, ValueError):
            continue
        chapter = database.get_chapter(chapter_id)
        if not chapter or int(chapter["book_id"]) != book_id:
            continue
        outline = str(item.get("outline", "")).strip()
        if outline:
            database.update_chapter(chapter_id, outline=outline, content=str(chapter["content"] or ""), summary_text="")
            updated_chapter_ids.add(chapter_id)
        events = item.get("events", [])
        if isinstance(events, list):
            # 批量删除旧事件
            old_event_ids = existing_events.get(chapter_id, [])
            if old_event_ids:
                database.connection.executemany(
                    "DELETE FROM chapter_events WHERE id = ?",
                    [(eid,) for eid in old_event_ids],
                )
            # 批量插入新事件（去重，最多 6 条）
            written: set[str] = set()
            new_events: list[tuple] = []
            for event_label in events[:6]:
                label = str(event_label).strip()
                if label and label not in written:
                    new_events.append((book_id, chapter_id, label))
                    written.add(label)
            if new_events:
                database.connection.executemany(
                    "INSERT INTO chapter_events (book_id, chapter_id, label) VALUES (?, ?, ?)",
                    new_events,
                )
            updated_chapter_ids.add(chapter_id)

    return updated_chapter_ids


def filter_untrusted_book_analysis_payload(
    payload: dict[str, Any],
    *,
    requires_evidence: bool | None = None,
) -> dict[str, Any]:
    payload = normalize_book_analysis_payload(payload)
    resolved_requires_evidence = book_analysis_requires_evidence(payload) if requires_evidence is None else bool(requires_evidence)
    if not resolved_requires_evidence:
        return payload
    filtered = deepcopy(payload)
    dropped = 0
    unresolved = filtered.get("analysis_unresolved", [])
    if not isinstance(unresolved, list):
        unresolved = []
    for key in ("book_outline_form", "world_form"):
        value = filtered.get(key)
        if isinstance(value, dict):
            pruned, count = prune_untrusted_analysis_form(value)
            dropped += count
            if analysis_form_has_content(pruned):
                filtered[key] = pruned
            else:
                filtered.pop(key, None)
    if filtered.get("book_outline") and not has_direct_evidence(filtered):
        filtered.pop("book_outline", None)
        dropped += 1
    if filtered.get("world_text") and not has_direct_evidence(filtered):
        filtered.pop("world_text", None)
        dropped += 1

    characters = analysis_character_items(filtered)
    if characters:
        kept_characters: list[dict[str, Any]] = []
        for item in characters:
            role = analysis_first_text(item, ("role", "character_role", "position", "定位", "角色定位"))
            profile_form = analysis_character_profile_form(item, role)
            item_copy = deepcopy(item)
            has_trusted_content = False
            if isinstance(profile_form, dict):
                pruned_form, count = prune_untrusted_analysis_form(profile_form)
                dropped += count
                for key in (
                    "character_form",
                    "character_profile_form",
                    "profile_form",
                    "profile_data",
                    "profile_data_json",
                    "character_profile",
                    "profile_fields",
                    "fields",
                    "form",
                    "profile",
                ):
                    item_copy.pop(key, None)
                if analysis_form_has_content(pruned_form):
                    item_copy["profile_form"] = pruned_form
                    has_trusted_content = True
            profile_text = analysis_character_profile_text(item)
            if profile_text:
                if has_evidence(item):
                    item_copy["profile_text"] = profile_text
                    has_trusted_content = True
                else:
                    item_copy.pop("profile_text", None)
                    item_copy.pop("profile_markdown", None)
                    dropped += 1
            if has_trusted_content:
                kept_characters.append(item_copy)
            else:
                dropped += 1
        filtered["characters"] = kept_characters
        for key in ("character_cards", "character_profiles", "character_profile", "character_data"):
            filtered.pop(key, None)

    chapter_items = filtered.get("chapter_updates", [])
    if isinstance(chapter_items, list):
        kept_updates: list[dict[str, Any]] = []
        for item in chapter_items:
            if isinstance(item, dict) and has_evidence(item):
                kept_updates.append(item)
            elif isinstance(item, dict):
                dropped += 1
        filtered["chapter_updates"] = kept_updates
    if dropped:
        unresolved.append({"title": "证据门禁剔除", "content": f"{dropped} 个字段或条目缺少证据，未写入。"})
    filtered["analysis_unresolved"] = unresolved
    meta = filtered.get("_meta", {})
    if not isinstance(meta, dict):
        meta = {}
    meta["evidence_gate_dropped"] = dropped
    filtered["_meta"] = meta
    return filtered


def book_analysis_requires_evidence(payload: dict[str, Any]) -> bool:
    if bool(payload.get("_requires_evidence")):
        return True
    meta = payload.get("_meta", {})
    return isinstance(meta, dict) and str(meta.get("analysis_pipeline", "")).startswith("three_level_pyramid_v2")


def analysis_world_text(payload: dict[str, Any]) -> str:
    for key in (
        "world_text",
        "world_markdown",
        "worldview_markdown",
        "world_setting_markdown",
        "world_settings_markdown",
        "world_form",
        "world",
        "worldview",
        "world_setting",
        "world_settings",
        "world_summary",
        "世界观",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            text = analysis_world_dict_text(value)
            if text:
                return text
            continue
        if isinstance(value, (list, tuple)):
            continue
        text = str(value or "").strip()
        if text.startswith("{"):
            try:
                parsed = safe_json_loads(text)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                parsed_text = analysis_world_dict_text(parsed)
                if parsed_text:
                    return parsed_text
                continue
        if text:
            return text
    return ""


def analysis_world_schema_field_ids() -> set[str]:
    field_ids: set[str] = set()
    for section in WORLD_FORM_SCHEMA:
        for item in section.get("items", []):
            if isinstance(item, dict) and item.get("id"):
                field_ids.add(str(item["id"]))
    return field_ids


def analysis_world_dict_text(value: dict[str, Any]) -> str:
    field_ids = analysis_world_schema_field_ids()
    if isinstance(value.get("fields"), dict) or any(str(key) in field_ids for key in value):
        return ""
    lines: list[str] = []
    ignored = {"id", "book_id", "created_at", "updated_at"}
    for key, item in value.items():
        if key in ignored or item is None:
            continue
        if isinstance(item, (dict, list, tuple)):
            item_text = json.dumps(item, ensure_ascii=False)
        else:
            item_text = str(item or "").strip()
        if item_text:
            lines.append(f"{key}: {item_text}")
    return "\n".join(lines).strip()


def analysis_world_form(payload: dict[str, Any]) -> dict[str, Any] | None:
    field_ids = analysis_world_schema_field_ids()
    for key in (
        "world_form",
        "world_data",
        "world_data_json",
        "world_fields",
        "worldview_form",
        "world_setting_form",
        "world_settings_form",
        "world",
        "worldview",
        "world_setting",
        "world_settings",
        "世界观",
    ):
        if key not in payload:
            continue
        parsed = analysis_json_dict(payload.get(key))
        if parsed is not None and (
            isinstance(parsed.get("fields"), dict)
            or isinstance(parsed.get("supplements"), list)
            or any(str(field_key) in field_ids for field_key in parsed)
        ):
            return parsed
    if any(str(key) in field_ids for key in payload):
        return payload
    return None


def analysis_first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, (dict, list, tuple)):
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def analysis_json_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not text.startswith("{"):
        return None
    try:
        parsed = safe_json_loads(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def analysis_character_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in (
        "characters",
        "character_cards",
        "character_profiles",
        "character_profile",
        "character_data",
        "人物卡",
        "角色卡",
        "人物",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            if any(
                marker in value
                for marker in (
                    "name",
                    "character_name",
                    "profile_form",
                    "profile_data",
                    "profile_data_json",
                    "profile_text",
                    "profile_markdown",
                )
            ):
                return [value]
            records: list[dict[str, Any]] = []
            for name, record in value.items():
                if isinstance(record, dict):
                    item = dict(record)
                    item.setdefault("name", str(name))
                    records.append(item)
                else:
                    text = str(record or "").strip()
                    if text:
                        records.append({"name": str(name), "profile_text": text})
            if records:
                return records
    return []


def analysis_character_schema_field_ids(role: str, schema_key: str = "") -> set[str]:
    field_ids: set[str] = set()
    for section in character_profile_schema_for_role(role, schema_key):
        for item in section.get("items", []):
            if isinstance(item, dict) and item.get("id"):
                field_ids.add(str(item["id"]))
    return field_ids


def analysis_character_profile_form(item: dict[str, Any], role: str) -> dict[str, Any] | None:
    for key in (
        "character_form",
        "character_profile_form",
        "profile_form",
        "profile_data",
        "profile_data_json",
        "character_profile",
        "profile_fields",
        "fields",
        "form",
        "profile",
    ):
        if key not in item:
            continue
        parsed = analysis_json_dict(item.get(key))
        if parsed is not None:
            return parsed
    schema_key = str(item.get("schema", "") or item.get("profile_schema", "") or "")
    field_ids = analysis_character_schema_field_ids(role, schema_key)
    if any(str(key) in field_ids for key in item):
        return item
    return None


def analysis_character_profile_text(item: dict[str, Any]) -> str:
    for key in (
        "profile_text",
        "profile_markdown",
        "markdown",
        "content",
        "description",
        "summary",
        "profile",
    ):
        value = item.get(key)
        if isinstance(value, (dict, list, tuple)):
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def analysis_field_has_written_content(field: dict[str, Any]) -> bool:
    if bool(field.get("checked", False)):
        return True
    return bool(str(field.get("value", "") or "").strip())


def analysis_form_has_content(form: dict[str, Any] | None) -> bool:
    if not isinstance(form, dict):
        return False
    fields = form.get("fields", {})
    if isinstance(fields, dict):
        for field in fields.values():
            if isinstance(field, dict) and analysis_field_has_written_content(field):
                return True
    for plan in form.get("volume_plans", []) if isinstance(form.get("volume_plans"), list) else []:
        if not isinstance(plan, dict):
            continue
        plan_fields = plan.get("fields", {})
        if isinstance(plan_fields, dict):
            for field in plan_fields.values():
                if isinstance(field, dict) and str(field.get("value", "") or "").strip():
                    return True
    supplements = form.get("supplements", [])
    if isinstance(supplements, list):
        for supplement in supplements:
            if isinstance(supplement, dict) and str(supplement.get("content", "") or "").strip():
                return True
    return False


def prune_untrusted_analysis_form(form: dict[str, Any]) -> tuple[dict[str, Any], int]:
    pruned = deepcopy(form)
    dropped = 0
    fields = pruned.get("fields", {})
    if isinstance(fields, dict):
        for field_id in list(fields.keys()):
            field = fields.get(field_id)
            if not isinstance(field, dict):
                fields.pop(field_id, None)
                continue
            if not analysis_field_has_written_content(field):
                fields.pop(field_id, None)
                continue
            if not has_evidence(field):
                fields.pop(field_id, None)
                dropped += 1
    volume_plans = pruned.get("volume_plans", [])
    if isinstance(volume_plans, list):
        kept_plans: list[dict[str, Any]] = []
        for plan in volume_plans:
            if not isinstance(plan, dict):
                continue
            plan_copy = deepcopy(plan)
            plan_fields = plan_copy.get("fields", {})
            if isinstance(plan_fields, dict):
                for field_id in list(plan_fields.keys()):
                    field = plan_fields.get(field_id)
                    if not isinstance(field, dict) or not str(field.get("value", "") or "").strip():
                        plan_fields.pop(field_id, None)
                        continue
                    if not has_evidence(field):
                        plan_fields.pop(field_id, None)
                        dropped += 1
            if analysis_form_has_content({"fields": {}, "volume_plans": [plan_copy], "supplements": []}):
                kept_plans.append(plan_copy)
        pruned["volume_plans"] = kept_plans
    supplements = pruned.get("supplements", [])
    if isinstance(supplements, list):
        kept_supplements: list[dict[str, Any]] = []
        for supplement in supplements:
            if not isinstance(supplement, dict):
                continue
            if not str(supplement.get("content", "") or "").strip():
                continue
            if has_evidence(supplement):
                kept_supplements.append(supplement)
            else:
                dropped += 1
        pruned["supplements"] = kept_supplements
    return pruned, dropped


def overlay_sparse_analysis_form(base: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base) if isinstance(base, dict) else {}
    for key in ("version", "schema", "name", "role"):
        if key in incoming and str(incoming.get(key, "") or "").strip():
            result[key] = incoming[key]
    incoming_fields = incoming.get("fields", {})
    if isinstance(incoming_fields, dict):
        result_fields = result.setdefault("fields", {})
        if not isinstance(result_fields, dict):
            result["fields"] = result_fields = {}
        for field_id, field in incoming_fields.items():
            if not isinstance(field, dict):
                continue
            target = result_fields.setdefault(str(field_id), {})
            if not isinstance(target, dict):
                target = {}
                result_fields[str(field_id)] = target
            if "checked" in field:
                target["checked"] = bool(field.get("checked", False))
            if "value" in field:
                target["value"] = str(field.get("value", "") or "")
    incoming_plans = incoming.get("volume_plans", [])
    if isinstance(incoming_plans, list):
        result_plans = result.setdefault("volume_plans", [])
        if not isinstance(result_plans, list):
            result["volume_plans"] = result_plans = []
        by_id = {str(plan.get("volume_id", "")): plan for plan in result_plans if isinstance(plan, dict)}
        for incoming_plan in incoming_plans:
            if not isinstance(incoming_plan, dict):
                continue
            key = str(incoming_plan.get("volume_id", ""))
            target_plan = by_id.get(key)
            if target_plan is None:
                target_plan = {
                    "volume_id": incoming_plan.get("volume_id", len(result_plans) + 1),
                    "volume_title": incoming_plan.get("volume_title", ""),
                    "sort_order": incoming_plan.get("sort_order", len(result_plans) + 1),
                    "fields": {},
                }
                result_plans.append(target_plan)
                by_id[key] = target_plan
            target_fields = target_plan.setdefault("fields", {})
            if not isinstance(target_fields, dict):
                target_plan["fields"] = target_fields = {}
            incoming_fields = incoming_plan.get("fields", {})
            if not isinstance(incoming_fields, dict):
                continue
            for field_id, field in incoming_fields.items():
                if isinstance(field, dict) and "value" in field:
                    target_fields[str(field_id)] = {"value": str(field.get("value", "") or "")}
    incoming_supplements = incoming.get("supplements", [])
    if isinstance(incoming_supplements, list):
        result_supplements = result.setdefault("supplements", [])
        if not isinstance(result_supplements, list):
            result["supplements"] = result_supplements = []
        existing = {
            (str(item.get("title", "") or ""), str(item.get("content", "") or ""))
            for item in result_supplements
            if isinstance(item, dict)
        }
        for supplement in incoming_supplements:
            if not isinstance(supplement, dict):
                continue
            marker = (str(supplement.get("title", "") or ""), str(supplement.get("content", "") or ""))
            if marker not in existing:
                result_supplements.append(supplement)
                existing.add(marker)
    return result
