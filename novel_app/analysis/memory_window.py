from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_SHORT_TERM_CHAPTER_WINDOW = 3


@dataclass(frozen=True)
class MemoryWindow:
    latest_chapter_id: int
    short_term_chapter_ids: tuple[int, ...]

    def contains_chapter(self, chapter_id: int | None) -> bool:
        if chapter_id is None:
            return True
        return int(chapter_id) in self.short_term_chapter_ids


class MemoryWindowBuilder:
    def __init__(self, *, short_term_chapter_window: int = DEFAULT_SHORT_TERM_CHAPTER_WINDOW) -> None:
        self.short_term_chapter_window = max(1, int(short_term_chapter_window))

    def build(self, facts: Iterable[dict[str, Any]]) -> MemoryWindow:
        chapter_ids = sorted(
            {
                int(fact.get("chapter_id") or 0)
                for fact in facts
                if _int_or_none(fact.get("chapter_id")) is not None
            }
        )
        if not chapter_ids:
            return MemoryWindow(latest_chapter_id=0, short_term_chapter_ids=())
        latest = chapter_ids[-1]
        short_term = tuple(chapter_ids[-self.short_term_chapter_window :])
        return MemoryWindow(latest_chapter_id=latest, short_term_chapter_ids=short_term)

    def select_context_facts(
        self,
        facts: Iterable[dict[str, Any]],
        *,
        include_cache: bool = False,
    ) -> list[dict[str, Any]]:
        window = self.build(facts)
        selected: list[dict[str, Any]] = []
        for fact in facts:
            memory_type = str(fact.get("memory_type") or "")
            if memory_type == "cache" and not include_cache:
                continue
            if window.contains_chapter(_int_or_none(fact.get("chapter_id"))):
                selected.append(dict(fact))
                continue
            if str(fact.get("memory_type") or "") == "foundation":
                selected.append(dict(fact))
                continue
            if str(fact.get("memory_importance") or "") == "high":
                selected.append(dict(fact))
        return selected

    def migrate_expired_short_term(
        self,
        facts: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """滑动窗口迁移：将超出短期窗口的 short_term 事实降级为 long_term。

        降级规则：
        1. chapter_id 不在当前短期窗口内 → memory_scope = long_term
        2. 降级时按重要性重新分类 memory_type
        3. 伏笔事实永不降级（is_foreshadowing = true）
        4. foundation 类型永不降级
        """
        source = [dict(f) for f in facts]
        if not source:
            return source
        window = self.build(source)
        migrated: list[dict[str, Any]] = []
        for fact in source:
            chapter_id = _int_or_none(fact.get("chapter_id"))
            memory_scope = str(fact.get("memory_scope") or "")
            fact_type = str(fact.get("fact_type") or "")
            is_foreshadowing = bool(fact.get("is_foreshadowing"))
            memory_type = str(fact.get("memory_type") or "")

            # 永不降级
            if is_foreshadowing or memory_type == "foundation" or fact_type in {"foreshadowing", "world_rule"}:
                migrated.append(fact)
                continue

            # 需要降级
            if memory_scope == "short_term" and not window.contains_chapter(chapter_id):
                fact["memory_scope"] = "long_term"
                # 重新分类 memory_type
                memory_importance = str(fact.get("memory_importance") or "normal")
                if fact_type in {"event", "relation"} and memory_importance != "high":
                    fact["memory_type"] = "cache"
                fact["metadata"] = dict(fact.get("metadata") or {})
                fact["metadata"]["migration"] = {
                    "from_scope": "short_term",
                    "to_scope": "long_term",
                    "previous_memory_type": memory_type,
                    "new_memory_type": fact.get("memory_type", memory_type),
                }

            migrated.append(fact)
        return migrated


def _int_or_none(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
