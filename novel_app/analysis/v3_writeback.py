"""V3 分析卡片写回引擎 — 将分析卡片内容写回到业务表。

写回前执行：
1. Schema gate：验证 writeback_fields 符合目标表的 schema 约束
2. 快照创建：写回前自动创建 analysis_apply_snapshots 记录
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.json_safety import safe_json_loads
from novel_app.database import Database

logger = logging.getLogger(__name__)


# Schema gate：每种 writeback_target 的必填字段
_SCHEMA_REQUIREMENTS: dict[str, dict[str, type]] = {
    "character": {
        "name": str,
    },
    "world_entry": {
        "name": str,
        "category": str,
    },
    "book": {},
}

# 白名单：每种 writeback_target 允许的字段
_WRITEBACK_FIELDS_ALLOWLIST: dict[str, set[str]] = {
    "character": {"name", "role", "profile_text"},
    "world_entry": {"name", "category", "content_text"},
    "book": {"outline_text", "world_text"},
}


@dataclass(frozen=True)
class WritebackResult:
    """写回结果。"""
    success: bool
    applied_table: str  # "characters" / "world_entries" / "books"
    applied_id: int | None  # 写回记录的 ID
    detail: str = ""
    snapshot_id: int | None = None
    generation_used: bool = False
    writeback_fields: dict[str, Any] | None = None
    generation_metadata: dict[str, Any] | None = None


def validate_schema_gate(card: dict[str, Any]) -> list[str]:
    """Schema gate 校验：检查 writeback_fields 是否符合目标表约束。

    返回错误列表，空列表表示通过。
    """
    payload = _extract_payload(card)
    if not payload:
        return ["卡片无 payload"]

    writeback_target = str(payload.get("writeback_target") or "")
    writeback_fields = payload.get("writeback_fields")

    if not writeback_target:
        return ["缺少 writeback_target"]
    if not isinstance(writeback_fields, dict):
        return ["writeback_fields 不是字典"]

    requirements = _SCHEMA_REQUIREMENTS.get(writeback_target)
    if requirements is None:
        return [f"未知的 writeback_target: {writeback_target}"]

    errors: list[str] = []
    for field_name, field_type in requirements.items():
        value = writeback_fields.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"必填字段 '{field_name}' 缺失或为空")
        elif not isinstance(value, field_type):
            errors.append(f"字段 '{field_name}' 类型错误：期望 {field_type.__name__}，实际 {type(value).__name__}")

    # 白名单过滤：移除不在允许列表中的额外字段
    allowed_fields = _WRITEBACK_FIELDS_ALLOWLIST.get(writeback_target, set())
    extra_keys = set(writeback_fields.keys()) - allowed_fields
    if extra_keys:
        logger.warning("writeback_fields 白名单过滤：移除不允许的字段 %s (target=%s)", extra_keys, writeback_target)
        for key in extra_keys:
            del writeback_fields[key]

    return errors


def create_writeback_snapshot(database: Database, book_id: int, card: dict[str, Any]) -> int | None:
    """写回前创建快照，记录当前业务数据状态。返回 snapshot ID。"""
    payload = _extract_payload(card)
    if not payload:
        return None
    writeback_target = str(payload.get("writeback_target") or "")
    entity_uid = str(card.get("entity_uid") or "")
    card_uid = str(card.get("card_uid") or "")

    snapshot_data: dict[str, Any] = {
        "card_uid": card_uid,
        "entity_uid": entity_uid,
        "writeback_target": writeback_target,
        "writeback_fields": payload.get("writeback_fields", {}),
    }
    generation_metadata = payload.get("writeback_generation")
    if isinstance(generation_metadata, dict):
        snapshot_data["writeback_generation"] = generation_metadata
        original_fields = generation_metadata.get("original_writeback_fields")
        if isinstance(original_fields, dict):
            snapshot_data["original_writeback_fields"] = original_fields

    # 记录当前业务数据状态
    if writeback_target == "character":
        try:
            character_name = str(payload.get("writeback_fields", {}).get("name") or "")
            if character_name:
                existing = _find_character_by_name(database, book_id, character_name)
                if existing:
                    snapshot_data["before_state"] = dict(existing)
        except Exception:
            pass
    elif writeback_target == "world_entry":
        try:
            entry_name = str(payload.get("writeback_fields", {}).get("name") or "")
            if entry_name:
                existing = _find_world_entry_by_name(database, book_id, entry_name)
                if existing:
                    snapshot_data["before_state"] = dict(existing)
        except Exception:
            pass
    elif writeback_target == "book":
        try:
            book = database.get_book(book_id)
            if book:
                snapshot_data["before_state"] = {
                    "outline_text": str(_row_value(book, "outline_text") or ""),
                    "world_text": str(_row_value(book, "world_text") or ""),
                }
        except Exception:
            pass

    try:
        run_id = _int_or_none(card.get("run_id"))
        label = f"V3 写回前快照 · {card_uid or writeback_target or 'card'}"
        snapshot_id = database.create_analysis_apply_snapshot(
            book_id,
            run_id,
            label,
            snapshot_data,
        )
        return snapshot_id
    except Exception as exc:
        logger.warning("Failed to create writeback snapshot: %s", exc)
        return None


def writeback_v3_card(
    database: Database,
    book_id: int,
    card: dict[str, Any],
    *,
    writeback_generator: Any | None = None,
    require_generator: bool = False,
) -> WritebackResult:
    """根据卡片类型和 payload 中的 writeback_target 执行写回。

    写回前执行 Schema gate 校验、可选 LLM 字段精炼和快照创建。
    """
    # Schema gate 校验
    schema_errors = validate_schema_gate(card)
    if schema_errors:
        return WritebackResult(False, "", None, f"Schema gate 校验失败: {'; '.join(schema_errors)}")

    payload = _extract_payload(card)
    if not payload:
        return WritebackResult(False, "", None, "卡片无 payload")

    writeback_target = str(payload.get("writeback_target") or "")
    writeback_fields = payload.get("writeback_fields")

    if not isinstance(writeback_fields, dict) or not writeback_target:
        return WritebackResult(False, "", None, "卡片无 writeback_target 或 writeback_fields")

    generation_used = False
    generation_metadata: dict[str, Any] | None = None
    if writeback_generator is not None or require_generator:
        if writeback_generator is None:
            return WritebackResult(False, "", None, "AI 写回卡片生成器不可用")
        try:
            generated = writeback_generator.generate(database, book_id, card, payload=payload)
        except Exception as exc:
            logger.warning("Writeback card generation failed for card %s: %s", card.get("card_uid"), exc)
            return WritebackResult(False, "", None, "AI 写回卡片生成失败")

        if generated.target != writeback_target:
            return WritebackResult(False, "", None, "AI 写回卡片生成目标不一致")

        refined_payload = dict(payload)
        refined_payload["writeback_fields"] = dict(generated.fields)
        refined_payload["writeback_generation"] = dict(generated.metadata)
        refined_card = dict(card)
        refined_card["payload"] = refined_payload
        refined_card["payload_json"] = json.dumps(refined_payload, ensure_ascii=False)

        refined_schema_errors = validate_schema_gate(refined_card)
        if refined_schema_errors:
            return WritebackResult(False, "", None, f"AI 写回字段二次校验失败: {'; '.join(refined_schema_errors)}")

        card = refined_card
        payload = refined_payload
        writeback_fields = dict(generated.fields)
        generation_used = True
        generation_metadata = dict(generated.metadata)

    # 写回前创建快照
    snapshot_id = create_writeback_snapshot(database, book_id, card)
    if snapshot_id:
        logger.info("Created writeback snapshot %s for card %s", snapshot_id, card.get("card_uid"))

    if writeback_target == "character":
        result = _writeback_character(database, book_id, writeback_fields)
    elif writeback_target == "world_entry":
        result = _writeback_world_entry(database, book_id, writeback_fields)
    elif writeback_target == "book":
        result = _writeback_book(database, book_id, writeback_fields)
    else:
        return WritebackResult(False, "", None, f"未知的 writeback_target: {writeback_target}")

    # 写回失败时记录快照 ID 以便回滚
    if not result.success and snapshot_id:
        logger.warning("Writeback failed for card %s, snapshot %s available for rollback", card.get("card_uid"), snapshot_id)

    return WritebackResult(
        result.success,
        result.applied_table,
        result.applied_id,
        result.detail,
        snapshot_id,
        generation_used,
        dict(writeback_fields),
        generation_metadata,
    )


def _extract_payload(card: dict[str, Any]) -> dict[str, Any] | None:
    """从卡片记录中提取 payload 字典。"""
    payload = card.get("payload")
    if isinstance(payload, dict):
        return payload
    payload_json = card.get("payload_json")
    if isinstance(payload_json, str) and payload_json:
        try:
            return safe_json_loads(payload_json)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def _find_character_by_id(database: Database, book_id: int, character_id: int) -> Any | None:
    """通过 ID 查找人物，确保 ID 和 book_id 匹配。"""
    try:
        character = database.get_character(character_id)
        if character and int(_row_value(character, "book_id") or 0) == book_id:
            return character
    except Exception:
        pass
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


def _find_world_entry_by_id(database: Database, book_id: int, entry_id: int) -> Any | None:
    """通过 ID 查找世界观条目，确保 ID 和 book_id 匹配。"""
    try:
        entry = database.get_world_entry(entry_id)
        if entry and int(_row_value(entry, "book_id") or 0) == book_id:
            return entry
    except Exception:
        pass
    return None


def _find_world_entry_by_name(database: Database, book_id: int, name: str) -> Any | None:
    clean_name = str(name or "").strip()
    if not clean_name:
        return None
    if hasattr(database, "get_world_entry_by_name"):
        return database.get_world_entry_by_name(book_id, clean_name)
    for entry in database.list_world_entries(book_id):
        if int(_row_value(entry, "id") or 0) > 0 and str(_row_value(entry, "name") or "").strip() == clean_name:
            return entry
    return None


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _writeback_character(database: Database, book_id: int, fields: dict[str, Any]) -> WritebackResult:
    """人物卡写回 — 写入 characters 表 + 状态机三轴字段。

    写回流程在 database.transaction() 上下文内执行，保证多表写入的原子性：
    1. 匹配/创建 character（原有逻辑）
    2. 状态机写回（新）：facts → 三轴字段 + 主循环日志
    3. 旧 supplement 写回（过渡兼容）：merge_character_profile_supplement
    4. update_character_form（原有逻辑）

    状态机写回失败时记录日志并降级到旧 supplement 逻辑，不影响主流程。
    """
    from novel_app.analysis.state_machine_writeback import writeback_to_state_machine
    from novel_app.structured_templates.base import merge_character_profile_supplement

    name = str(fields.get("name") or "").strip()
    if not name:
        return WritebackResult(False, "characters", None, "人物卡缺少 name 字段")

    role = str(fields.get("role") or "").strip()
    profile_text = str(fields.get("profile_text") or "").strip()

    # 优先使用 id 匹配（如果 writeback_fields 中包含 id 字段）
    target_id = _int_or_none(fields.get("id"))
    existing_id = None
    if target_id is not None:
        matched = _find_character_by_id(database, book_id, target_id)
        if matched is not None:
            existing_id = int(_row_value(matched, "id") or target_id)
            logger.info("人物写回 ID 匹配: book_id=%d, id=%d, name=%s", book_id, existing_id, name)
        else:
            logger.warning("人物写回 ID 匹配失败（ID 不存在或不属于当前作品）: book_id=%d, id=%d, name=%s", book_id, target_id, name)

    # ID 未匹配时回退到 name 匹配
    if existing_id is None:
        existing_characters = database.list_characters(book_id)
        matched_count = 0
        for ch in existing_characters:
            if str(ch["name"] or "").strip() == name:
                matched_count += 1
                if existing_id is None:
                    existing_id = int(ch["id"])
        if matched_count > 1:
            logger.warning("人物写回 name 匹配到多个条目（拒绝写回，要求提供 id）: book_id=%d, name=%s, matched_count=%d", book_id, name, matched_count)
            return WritebackResult(False, "characters", None, f"name '{name}' 匹配到 {matched_count} 个条目，请提供 id 字段指定具体更新对象")
        if existing_id is not None:
            logger.info("人物写回 name 匹配: book_id=%d, id=%d, name=%s", book_id, existing_id, name)

    # 构造 facts：fields.facts 优先；否则用 profile_text 整体作为 analysis_summary
    raw_facts = fields.get("facts")
    if isinstance(raw_facts, list):
        facts = [f for f in raw_facts if isinstance(f, dict)]
    elif profile_text:
        facts = [{"fact_type": "analysis_summary", "content": profile_text}]
    else:
        facts = []

    # 多表写入（characters + character_state_machines + character_cycles + 快照）
    # 必须在 transaction 内执行，保证原子性
    with database.transaction():
        if existing_id is not None:
            # 更新已有人物 — 合并分析摘要到已有 profile
            existing = database.get_character(existing_id)
            if existing:
                role = role or str(existing["role"] or "")

            # 状态机写回（新）— 失败时降级到旧逻辑，不影响主流程
            try:
                sm_result = writeback_to_state_machine(database, book_id, existing_id, facts)
                if sm_result.get("axis_updates"):
                    logger.info(
                        "状态机写回 character_id=%s 字段=%s cycle_id=%s",
                        existing_id, list(sm_result["axis_updates"].keys()),
                        sm_result.get("cycle_id"),
                    )
            except Exception as exc:
                logger.warning(
                    "状态机写回失败 character_id=%s，降级到旧 supplement 逻辑: %s",
                    existing_id, exc,
                )

            # 旧 supplement 写回（过渡兼容）
            existing_form = database.get_character_profile_form(existing_id)
            if profile_text:
                merged_form = merge_character_profile_supplement(
                    existing_form, name, role, profile_text, supplement_title="V3 分析摘要"
                )
            else:
                merged_form = existing_form
            database.update_character_form(existing_id, name, role, merged_form, image_path=None)
            return WritebackResult(True, "characters", existing_id, f"更新人物: {name}")
        else:
            # 创建新人物 — create_character 内部自动初始化空状态机
            character_id = database.create_character(book_id, name)

            # 状态机写回（新）— 失败时降级到旧逻辑，不影响主流程
            try:
                sm_result = writeback_to_state_machine(database, book_id, character_id, facts)
                if sm_result.get("axis_updates"):
                    logger.info(
                        "状态机写回（新建）character_id=%s 字段=%s cycle_id=%s",
                        character_id, list(sm_result["axis_updates"].keys()),
                        sm_result.get("cycle_id"),
                    )
            except Exception as exc:
                logger.warning(
                    "状态机写回失败（新建）character_id=%s，降级到旧 supplement 逻辑: %s",
                    character_id, exc,
                )

            # 旧 supplement 写回（过渡兼容）
            if role or profile_text:
                from novel_app.structured_templates.base import character_profile_form_defaults
                base_form = character_profile_form_defaults(name, role)
                if profile_text:
                    merged_form = merge_character_profile_supplement(
                        base_form, name, role, profile_text, supplement_title="V3 分析摘要"
                    )
                else:
                    merged_form = base_form
                database.update_character_form(character_id, name, role, merged_form, image_path=None)
            return WritebackResult(True, "characters", character_id, f"创建人物: {name}")


def _writeback_world_entry(database: Database, book_id: int, fields: dict[str, Any]) -> WritebackResult:
    """世界卡写回 — 写入 world_entries 表。"""
    name = str(fields.get("name") or "").strip()
    if not name:
        return WritebackResult(False, "world_entries", None, "世界卡缺少 name 字段")

    category = str(fields.get("category") or "设定").strip()
    content_text = str(fields.get("content_text") or "").strip()

    # 优先使用 id 匹配（如果 writeback_fields 中包含 id 字段）
    target_id = _int_or_none(fields.get("id"))
    existing_id = None
    if target_id is not None:
        matched = _find_world_entry_by_id(database, book_id, target_id)
        if matched is not None:
            existing_id = int(_row_value(matched, "id") or target_id)
            logger.info("世界观写回 ID 匹配: book_id=%d, id=%d, name=%s", book_id, existing_id, name)
        else:
            logger.warning("世界观写回 ID 匹配失败（ID 不存在或不属于当前作品）: book_id=%d, id=%d, name=%s", book_id, target_id, name)

    # ID 未匹配时回退到 name 匹配
    if existing_id is None:
        existing_entries = database.list_world_entries(book_id)
        matched_count = 0
        for entry in existing_entries:
            if str(entry["name"] or "").strip() == name:
                matched_count += 1
                if existing_id is None:
                    existing_id = int(entry["id"])
        if matched_count > 1:
            logger.warning("世界观写回 name 匹配到多个条目（拒绝写回，要求提供 id）: book_id=%d, name=%s, matched_count=%d", book_id, name, matched_count)
            return WritebackResult(False, "world_entry", None, f"name '{name}' 匹配到 {matched_count} 个条目，请提供 id 字段指定具体更新对象")
        if existing_id is not None:
            logger.info("世界观写回 name 匹配: book_id=%d, id=%d, name=%s", book_id, existing_id, name)

    if existing_id is not None:
        # 更新已有条目 — 追加内容
        existing = database.get_world_entry(existing_id)
        if existing and content_text:
            old_content = str(existing["content_text"] or "").strip()
            if old_content:
                # 避免重复追加
                content_text = old_content + "\n\n" + content_text if content_text not in old_content else old_content
        if content_text:
            database.update_world_entry(existing_id, name=name, category=category, content_text=content_text)
        return WritebackResult(True, "world_entries", existing_id, f"更新世界观: {name}")
    else:
        # 创建新条目 — create_world_entry 不接受 content_text，需先创建再更新
        entry_id = database.create_world_entry(book_id, name, category=category)
        if content_text:
            database.update_world_entry(entry_id, name=name, category=category, content_text=content_text)
        return WritebackResult(True, "world_entries", entry_id, f"创建世界观: {name}")


def _writeback_book(database: Database, book_id: int, fields: dict[str, Any]) -> WritebackResult:
    """书籍卡写回 — 更新 books 表的 outline/world 字段。"""
    outline_text = str(fields.get("outline_text") or "").strip()
    world_text = str(fields.get("world_text") or "").strip()

    if not outline_text and not world_text:
        return WritebackResult(False, "books", None, "书籍卡无 outline/world 内容")

    book = database.get_book(book_id)
    if not book:
        return WritebackResult(False, "books", None, f"书籍 {book_id} 不存在")

    # 合并更新 outline
    if outline_text:
        old_outline = str(book["outline_text"] or "").strip()
        if old_outline and outline_text not in old_outline:
            outline_text = old_outline + "\n\n---\n\n" + outline_text
        elif old_outline:
            outline_text = old_outline
        database.connection.execute(
            "UPDATE books SET outline_text = ? WHERE id = ?",
            (outline_text, book_id),
        )

    # 合并更新 world
    if world_text:
        old_world = str(book["world_text"] or "").strip()
        if old_world and world_text not in old_world:
            world_text = old_world + "\n\n---\n\n" + world_text
        elif old_world:
            world_text = old_world
        database.connection.execute(
            "UPDATE books SET world_text = ? WHERE id = ?",
            (world_text, book_id),
        )

    database.connection.commit()
    return WritebackResult(True, "books", book_id, "更新书籍 outline/world")
