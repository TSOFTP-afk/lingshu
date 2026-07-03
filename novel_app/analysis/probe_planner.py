from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from novel_app.analysis.schemas_v3 import stable_hash

logger = logging.getLogger(__name__)

# M8 探针规划 4 个子类型并发执行
# _plan_foreshadowing / _plan_entity_state / _plan_world_rules / _plan_relationships
# 各自只读 facts + entity_by_uid，互不修改共享状态，可安全并发
PROBE_PLAN_MAX_WORKERS = int(os.environ.get("LINGSHU_PROBE_PLAN_MAX_WORKERS", "4") or 4)

SUPPORTED_PROBE_TYPES = {
    "foreshadowing_recovery",
    "entity_state",
    "world_rule",
    "relationship_evolution",
}

_PRIORITY_BY_TYPE = {
    "foreshadowing_recovery": 90,
    "world_rule": 85,
    "entity_state": 75,
    "relationship_evolution": 70,
}

_RECOVERY_TOKENS = ("回收", "揭示", "揭开", "答案", "兑现", "reveal", "resolve", "answer", "payoff")

_AI_CONTEXT_MAX_CHARS = 2000


class ProbePlanner:
    def __init__(self, *, max_plans_per_type: int = 12, use_ai: bool = False, ai_provider: Any = None) -> None:
        self.max_plans_per_type = max(1, int(max_plans_per_type))
        self.use_ai = bool(use_ai)
        self.ai_provider = ai_provider
        self._last_engine: str = "rule"
        self._ai_attempted: bool = False
        self._ai_succeeded: bool = False
        # 保护 _ai_attempted / _ai_succeeded 的并发写入（4 个 _plan_* 并发时）
        import threading
        self._ai_flag_lock = threading.Lock()

    def plan(
        self,
        *,
        book_id: int,
        run_id: int,
        facts: Iterable[dict[str, Any]],
        entities: Iterable[dict[str, Any]],
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> list[dict[str, Any]]:
        source_facts = _sorted_facts(fact for fact in facts if str(fact.get("fact_type") or "") != "memory_summary")
        entity_by_uid = {str(entity.get("entity_uid") or ""): dict(entity) for entity in entities}
        effective_use_ai = use_ai or self.use_ai
        effective_ai_provider = ai_provider if ai_provider is not None else self.ai_provider
        self._last_engine = "rule"
        self._ai_attempted = False
        self._ai_succeeded = False

        # 4 个 _plan_* 方法并发执行（各自只读 source_facts + entity_by_uid，互不修改共享状态）
        # _call_ai_probe 内部会写 self._ai_attempted / self._ai_succeeded，需加锁保护
        plan_tasks = [
            ("foreshadowing", self._plan_foreshadowing),
            ("entity_state", self._plan_entity_state),
            ("world_rules", self._plan_world_rules),
            ("relationships", self._plan_relationships),
        ]
        plans: list[dict[str, Any]] = []
        worker_count = max(1, min(len(plan_tasks), PROBE_PLAN_MAX_WORKERS))
        if effective_use_ai and effective_ai_provider is not None:
            logger.info("M8 探针规划: 4 子类型, %d 并发 worker", worker_count)
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="probe-plan") as executor:
            futures = {
                executor.submit(
                    fn, book_id, run_id, source_facts, entity_by_uid,
                    use_ai=effective_use_ai, ai_provider=effective_ai_provider,
                ): name
                for name, fn in plan_tasks
            }
            for future in futures:
                name = futures[future]
                try:
                    partial_plans = future.result()
                    if partial_plans:
                        plans.extend(partial_plans)
                except Exception as exc:
                    logger.warning("M8 probe plan '%s' failed: %s", name, exc)

        if self._ai_attempted:
            self._last_engine = "ai" if self._ai_succeeded else "rule_fallback"
        else:
            self._last_engine = "rule"
        return sorted(plans, key=lambda item: (-int(item.get("priority") or 0), str(item.get("probe_uid") or "")))

    def _plan_foreshadowing(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
        entity_by_uid: dict[str, dict[str, Any]],
        *,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        candidates = [
            fact for fact in facts
            if str(fact.get("fact_type") or "") == "foreshadowing" or _has_any_text(fact, ("伏笔", "线索", "clue", "hint", "secret"))
        ]
        for fact in candidates[: self.max_plans_per_type]:
            targets = [
                item for item in _later_related_facts(fact, facts)
                if str(item.get("fact_uid") or "") != str(fact.get("fact_uid") or "")
            ]
            recovery_targets = [item for item in targets if _has_any_text(item, _RECOVERY_TOKENS)]
            selected_targets = (recovery_targets or targets)[:3]
            question = "伏笔或线索是否在后续章节被回收或解释？"
            expected = "后续证据应能解释该线索的用途、答案或影响。"
            planner_name = "rules_v1"
            if use_ai and ai_provider is not None:
                ai_facts = [fact] + selected_targets
                context = _build_context(ai_facts)
                ai_result = self._call_ai_probe(
                    ai_provider,
                    probe_type="foreshadowing_recovery",
                    facts=ai_facts,
                    context=context,
                    book_id=book_id,
                    run_id=run_id,
                )
                if ai_result is not None:
                    question = ai_result.get("question") or question
                    expected = ai_result.get("expected") or expected
                    planner_name = "ai_llm"
            plans.append(
                self._build_plan(
                    book_id=book_id,
                    run_id=run_id,
                    probe_type="foreshadowing_recovery",
                    subject_entity_uid=str(fact.get("subject_entity_uid") or ""),
                    entity_by_uid=entity_by_uid,
                    source_facts=[fact],
                    target_facts=selected_targets,
                    question=question,
                    expected=expected,
                    planner=planner_name,
                )
            )
        return plans

    def _plan_entity_state(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
        entity_by_uid: dict[str, dict[str, Any]],
        *,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        grouped = _group_by_entity(
            fact for fact in facts
            if str(fact.get("fact_type") or "") == "state" or str(fact.get("memory_type") or "") == "foundation"
        )
        for entity_uid, entity_facts in list(grouped.items())[: self.max_plans_per_type]:
            source = entity_facts[:1]
            targets = entity_facts[1:4]
            question = "实体状态、身份、位置或能力是否前后一致？"
            expected = "后续状态可以演化，但需要有证据承接且不能自相矛盾。"
            planner_name = "rules_v1"
            if use_ai and ai_provider is not None:
                ai_facts = source + targets
                context = _build_context(ai_facts)
                ai_result = self._call_ai_probe(
                    ai_provider,
                    probe_type="entity_state",
                    facts=ai_facts,
                    context=context,
                    book_id=book_id,
                    run_id=run_id,
                )
                if ai_result is not None:
                    question = ai_result.get("question") or question
                    expected = ai_result.get("expected") or expected
                    planner_name = "ai_llm"
            plans.append(
                self._build_plan(
                    book_id=book_id,
                    run_id=run_id,
                    probe_type="entity_state",
                    subject_entity_uid=entity_uid,
                    entity_by_uid=entity_by_uid,
                    source_facts=source,
                    target_facts=targets,
                    question=question,
                    expected=expected,
                    planner=planner_name,
                )
            )
        return plans

    def _plan_world_rules(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
        entity_by_uid: dict[str, dict[str, Any]],
        *,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        grouped = _group_by_entity(
            fact for fact in facts
            if str(fact.get("fact_type") or "") == "world_rule" or str(fact.get("memory_type") or "") == "foundation"
        )
        for entity_uid, entity_facts in list(grouped.items())[: self.max_plans_per_type]:
            source = entity_facts[:1]
            targets = entity_facts[1:4]
            question = "世界规则或体系设定是否保持一致？"
            expected = "规则类事实需要和后续规则证据互相兼容。"
            planner_name = "rules_v1"
            if use_ai and ai_provider is not None:
                ai_facts = source + targets
                context = _build_context(ai_facts)
                ai_result = self._call_ai_probe(
                    ai_provider,
                    probe_type="world_rule",
                    facts=ai_facts,
                    context=context,
                    book_id=book_id,
                    run_id=run_id,
                )
                if ai_result is not None:
                    question = ai_result.get("question") or question
                    expected = ai_result.get("expected") or expected
                    planner_name = "ai_llm"
            plans.append(
                self._build_plan(
                    book_id=book_id,
                    run_id=run_id,
                    probe_type="world_rule",
                    subject_entity_uid=entity_uid,
                    entity_by_uid=entity_by_uid,
                    source_facts=source,
                    target_facts=targets,
                    question=question,
                    expected=expected,
                    planner=planner_name,
                )
            )
        return plans

    def _plan_relationships(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
        entity_by_uid: dict[str, dict[str, Any]],
        *,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        grouped = _group_by_entity(fact for fact in facts if str(fact.get("fact_type") or "") == "relation")
        for entity_uid, entity_facts in list(grouped.items())[: self.max_plans_per_type]:
            source = entity_facts[:1]
            targets = entity_facts[1:4]
            question = "关系变化是否有连续证据支撑？"
            expected = "关系变化需要可追溯的起点、变化和结果证据。"
            planner_name = "rules_v1"
            if use_ai and ai_provider is not None:
                ai_facts = source + targets
                context = _build_context(ai_facts)
                ai_result = self._call_ai_probe(
                    ai_provider,
                    probe_type="relationship_evolution",
                    facts=ai_facts,
                    context=context,
                    book_id=book_id,
                    run_id=run_id,
                )
                if ai_result is not None:
                    question = ai_result.get("question") or question
                    expected = ai_result.get("expected") or expected
                    planner_name = "ai_llm"
            plans.append(
                self._build_plan(
                    book_id=book_id,
                    run_id=run_id,
                    probe_type="relationship_evolution",
                    subject_entity_uid=entity_uid,
                    entity_by_uid=entity_by_uid,
                    source_facts=source,
                    target_facts=targets,
                    question=question,
                    expected=expected,
                    planner=planner_name,
                )
            )
        return plans

    def _call_ai_probe(
        self,
        ai_provider: Any,
        *,
        probe_type: str,
        facts: list[dict[str, Any]],
        context: str,
        book_id: int,
        run_id: int,
    ) -> dict[str, Any] | None:
        """调用 AI 生成探针问题，失败时返回 None（由调用方回退到硬编码模板）。

        同时更新实例级 _ai_attempted / _ai_succeeded 标记，用于 _last_engine 判定。
        4 个 _plan_* 并发时会同时调用此方法，标记写入需加锁保护。
        """
        with self._ai_flag_lock:
            self._ai_attempted = True
        try:
            result = ai_provider.generate_probe_questions(
                probe_type=probe_type,
                facts=facts,
                context=context,
                book_id=book_id,
                run_id=run_id,
            )
        except Exception as exc:
            logger.warning("generate_probe_questions failed for probe_type=%s, falling back to rules: %s", probe_type, exc)
            return None
        if isinstance(result, dict) and str(result.get("question") or "").strip() and str(result.get("expected") or "").strip():
            with self._ai_flag_lock:
                self._ai_succeeded = True
            return result
        return None

    def _build_plan(
        self,
        *,
        book_id: int,
        run_id: int,
        probe_type: str,
        subject_entity_uid: str,
        entity_by_uid: dict[str, dict[str, Any]],
        source_facts: list[dict[str, Any]],
        target_facts: list[dict[str, Any]],
        question: str,
        expected: str,
        planner: str = "rules_v1",
    ) -> dict[str, Any]:
        source_uids = [str(fact.get("fact_uid") or "") for fact in source_facts if str(fact.get("fact_uid") or "")]
        target_uids = [str(fact.get("fact_uid") or "") for fact in target_facts if str(fact.get("fact_uid") or "")]
        uid_seed = "|".join([str(book_id), str(run_id), probe_type, subject_entity_uid, ",".join(source_uids), ",".join(target_uids)])
        probe_uid = f"PROBE-{stable_hash(uid_seed)[:16]}"
        entity = entity_by_uid.get(subject_entity_uid, {})
        plan = {
            "probe_uid": probe_uid,
            "probe_type": probe_type,
            "question": question,
            "expected": expected,
            "subject": {
                "entity_uid": subject_entity_uid,
                "name": str(entity.get("canonical_name") or subject_entity_uid or "unknown"),
                "entity_type": str(entity.get("entity_type") or "unknown"),
            },
            "source_fact_uids": source_uids,
            "target_fact_uids": target_uids,
            "source_evidence": [_fact_evidence(fact) for fact in source_facts],
            "target_evidence": [_fact_evidence(fact) for fact in target_facts],
            "metadata": {
                "planner": planner,
                "formal_writeback": False,
                "manual_review_only": True,
            },
        }
        return {
            "probe_uid": probe_uid,
            "probe_type": probe_type,
            "probe_mode": "passive",
            "subject_entity_uid": subject_entity_uid,
            "plan": plan,
            "status": "planned",
            "priority": _PRIORITY_BY_TYPE.get(probe_type, 50),
        }


def _build_context(facts: list[dict[str, Any]]) -> str:
    """从 facts 的 quote_text 拼接上下文，最多 _AI_CONTEXT_MAX_CHARS 字。"""
    parts: list[str] = []
    total = 0
    for fact in facts:
        text = str(fact.get("quote_text") or "").strip()
        if not text:
            continue
        if total + len(text) > _AI_CONTEXT_MAX_CHARS:
            remaining = _AI_CONTEXT_MAX_CHARS - total
            if remaining > 0:
                parts.append(text[:remaining])
            break
        parts.append(text)
        total += len(text)
    return "\n".join(parts)


def _sorted_facts(facts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(fact) for fact in facts), key=lambda fact: (_int_or_zero(fact.get("chapter_id")), str(fact.get("block_uid") or ""), str(fact.get("fact_uid") or "")))


def _group_by_entity(facts: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in _sorted_facts(facts):
        entity_uid = str(fact.get("subject_entity_uid") or "").strip()
        if not entity_uid:
            continue
        grouped.setdefault(entity_uid, []).append(fact)
    return grouped


def _later_related_facts(source: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_uid = str(source.get("fact_uid") or "")
    source_entity = str(source.get("subject_entity_uid") or "")
    source_chapter = _int_or_zero(source.get("chapter_id"))
    targets: list[dict[str, Any]] = []
    for fact in facts:
        if str(fact.get("fact_uid") or "") == source_uid:
            continue
        if str(fact.get("subject_entity_uid") or "") != source_entity:
            continue
        if _int_or_zero(fact.get("chapter_id")) < source_chapter:
            continue
        targets.append(fact)
    return targets


def _fact_evidence(fact: dict[str, Any]) -> dict[str, Any]:
    value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
    return {
        "fact_uid": str(fact.get("fact_uid") or ""),
        "fact_type": str(fact.get("fact_type") or ""),
        "subject_entity_uid": str(fact.get("subject_entity_uid") or ""),
        "quote_text": str(fact.get("quote_text") or ""),
        "chapter_id": fact.get("chapter_id"),
        "block_uid": str(fact.get("block_uid") or ""),
        "summary": str(value.get("summary") or str(fact.get("quote_text") or ""))[:240],
    }


def _has_any_text(fact: dict[str, Any], tokens: Iterable[str]) -> bool:
    text = " ".join(
        [
            str(fact.get("fact_type") or ""),
            str(fact.get("quote_text") or ""),
            str(fact.get("value") or ""),
        ]
    ).lower()
    return any(str(token).lower() in text for token in tokens)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
