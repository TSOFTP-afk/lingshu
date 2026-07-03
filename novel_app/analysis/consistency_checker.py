from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ConsistencyChecker:
    def __init__(self, ai_provider: Any | None = None) -> None:
        self._ai_provider = ai_provider

    def check(self, plan: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
        plan_payload = plan.get("plan") if isinstance(plan.get("plan"), dict) else dict(plan)
        probe_type = str(plan.get("probe_type") or plan_payload.get("probe_type") or "")
        fact_by_uid = {str(fact.get("fact_uid") or ""): dict(fact) for fact in facts}
        source_evidence = _resolve_evidence(plan_payload.get("source_fact_uids"), plan_payload.get("source_evidence"), fact_by_uid)
        target_evidence = _resolve_evidence(plan_payload.get("target_fact_uids"), plan_payload.get("target_evidence"), fact_by_uid)

        # 优先使用 LLM 判定
        if self._ai_provider is not None:
            try:
                result = self._llm_check(plan_payload, source_evidence, target_evidence, probe_type)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("LLM consistency check failed, falling back to rules: %s", exc)

        # 规则引擎降级
        if probe_type == "foreshadowing_recovery":
            consistency, confidence, finding = self._check_foreshadowing(source_evidence, target_evidence)
        elif probe_type == "entity_state":
            consistency, confidence, finding = self._check_state(source_evidence, target_evidence)
        elif probe_type == "world_rule":
            consistency, confidence, finding = self._check_world_rule(source_evidence, target_evidence)
        elif probe_type == "relationship_evolution":
            consistency, confidence, finding = self._check_relationship(source_evidence, target_evidence)
        else:
            consistency, confidence, finding = "uncertain", 0.5, "unsupported probe type"

        status = "manual_review" if consistency == "uncertain" else "candidate"
        result = {
            "probe_uid": str(plan_payload.get("probe_uid") or plan.get("probe_uid") or ""),
            "probe_type": probe_type,
            "subject": plan_payload.get("subject") if isinstance(plan_payload.get("subject"), dict) else {},
            "question": str(plan_payload.get("question") or ""),
            "expected": str(plan_payload.get("expected") or ""),
            "consistency": consistency,
            "confidence": confidence,
            "status": status,
            "finding": finding,
            "source_evidence": source_evidence,
            "target_evidence": target_evidence,
            "manual_review_required": consistency == "uncertain",
            "formal_writeback": False,
            "checker": "rules_v1",
        }
        return {
            "probe_uid": result["probe_uid"],
            "consistency": consistency,
            "confidence": confidence,
            "status": status,
            "result": result,
        }

    # ------------------------------------------------------------------
    # LLM 一致性判定
    # ------------------------------------------------------------------

    def _llm_check(
        self,
        plan: dict[str, Any],
        source_evidence: list[dict[str, Any]],
        target_evidence: list[dict[str, Any]],
        probe_type: str,
    ) -> dict[str, Any] | None:
        """使用 LLM 判定一致性。返回 None 表示 LLM 不可用或失败。"""
        if not self._ai_provider or not hasattr(self._ai_provider, 'check_consistency'):
            return None

        probe_uid = str(plan.get("probe_uid") or "")
        question = str(plan.get("question") or "")

        # 构建证据文本
        source_text = self._evidence_to_text(source_evidence)
        target_text = self._evidence_to_text(target_evidence)
        if not source_text:
            return None

        prompt = (
            f"你是一个小说一致性检查器。请判断以下证据是否前后一致。\n\n"
            f"探针类型: {probe_type}\n"
            f"检查问题: {question}\n\n"
            f"前文证据:\n{source_text}\n\n"
            f"后文证据:\n{target_text or '（无后文证据）'}\n\n"
            f"请以 JSON 格式输出:\n"
            f'{{"consistency": "consistent/inconsistent/uncertain", "confidence": 0.0-1.0, "finding": "判定理由"}}'
        )

        response = self._ai_provider.check_consistency(
            prompt=prompt,
            probe_type=probe_type,
            probe_uid=probe_uid,
        )
        if not response:
            return None

        try:
            parsed = json.loads(response)
            consistency = str(parsed.get("consistency") or "uncertain")
            confidence = float(parsed.get("confidence") or 0.5)
            finding = str(parsed.get("finding") or "")
        except (json.JSONDecodeError, ValueError):
            return None

        if consistency not in {"consistent", "inconsistent", "uncertain"}:
            consistency = "uncertain"
        confidence = max(0.0, min(1.0, confidence))
        status = "manual_review" if consistency == "uncertain" else "candidate"

        result = {
            "probe_uid": probe_uid,
            "probe_type": probe_type,
            "subject": plan.get("subject") if isinstance(plan.get("subject"), dict) else {},
            "question": question,
            "expected": str(plan.get("expected") or ""),
            "consistency": consistency,
            "confidence": confidence,
            "status": status,
            "finding": finding,
            "source_evidence": source_evidence,
            "target_evidence": target_evidence,
            "manual_review_required": consistency == "uncertain",
            "formal_writeback": False,
            "checker": "llm_v1",
        }
        return {
            "probe_uid": probe_uid,
            "consistency": consistency,
            "confidence": confidence,
            "status": status,
            "result": result,
        }

    @staticmethod
    def _evidence_to_text(evidence: list[dict[str, Any]]) -> str:
        if not evidence:
            return ""
        parts = []
        for i, item in enumerate(evidence, 1):
            quote = str(item.get("quote_text") or item.get("summary") or "")
            chapter = item.get("chapter_id", "?")
            parts.append(f"  [{i}] 章节{chapter}: {quote[:200]}")
        return "\n".join(parts)

    @staticmethod
    def _check_foreshadowing(
        source_evidence: list[dict[str, Any]],
        target_evidence: list[dict[str, Any]],
    ) -> tuple[str, float, str]:
        if not source_evidence:
            return "uncertain", 0.45, "missing source evidence"
        if any(_has_recovery_text(item) for item in target_evidence):
            return "consistent", 0.78, "later evidence appears to recover or explain the setup"
        if target_evidence:
            return "uncertain", 0.62, "later related evidence exists, but payoff is not explicit"
        return "uncertain", 0.56, "no later target evidence found for this setup"

    @staticmethod
    def _check_state(
        source_evidence: list[dict[str, Any]],
        target_evidence: list[dict[str, Any]],
    ) -> tuple[str, float, str]:
        if _has_conflict(source_evidence, target_evidence):
            return "inconsistent", 0.84, "state evidence contains contradictory polarity"
        if target_evidence:
            return "consistent", 0.7, "state evidence has a traceable follow-up without obvious contradiction"
        return "uncertain", 0.58, "state evidence lacks a later confirmation or transition"

    @staticmethod
    def _check_world_rule(
        source_evidence: list[dict[str, Any]],
        target_evidence: list[dict[str, Any]],
    ) -> tuple[str, float, str]:
        if _has_conflict(source_evidence, target_evidence):
            return "inconsistent", 0.86, "world-rule evidence contains contradictory permission or prohibition"
        if target_evidence:
            return "consistent", 0.72, "world-rule evidence is compatible across source and target"
        return "uncertain", 0.57, "world rule has no later corroborating evidence"

    @staticmethod
    def _check_relationship(
        source_evidence: list[dict[str, Any]],
        target_evidence: list[dict[str, Any]],
    ) -> tuple[str, float, str]:
        if _has_conflict(source_evidence, target_evidence):
            return "uncertain", 0.61, "relationship polarity changes and needs manual review"
        if target_evidence:
            return "consistent", 0.69, "relationship has later evidence that can support an evolution"
        return "uncertain", 0.56, "relationship evidence has no later continuation"


def _resolve_evidence(
    fact_uids: Any,
    fallback_evidence: Any,
    fact_by_uid: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for fact_uid in fact_uids if isinstance(fact_uids, list) else []:
        fact = fact_by_uid.get(str(fact_uid or ""))
        if fact:
            resolved.append(_fact_evidence(fact))
    if resolved:
        return resolved
    return [dict(item) for item in fallback_evidence] if isinstance(fallback_evidence, list) else []


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


def _has_recovery_text(evidence: dict[str, Any]) -> bool:
    text = _evidence_text(evidence)
    return any(token in text for token in ("回收", "揭示", "揭开", "答案", "兑现", "reveal", "resolve", "answer", "payoff"))


def _has_conflict(source_evidence: list[dict[str, Any]], target_evidence: list[dict[str, Any]]) -> bool:
    source_text = " ".join(_evidence_text(item) for item in source_evidence)
    target_text = " ".join(_evidence_text(item) for item in target_evidence)
    if not source_text or not target_text:
        return False
    return (
        (_has_negative(source_text) and _has_positive(target_text))
        or (_has_positive(source_text) and _has_negative(target_text))
        or (_has_dead(source_text) and _has_alive(target_text))
        or (_has_alive(source_text) and _has_dead(target_text))
    )


def _evidence_text(evidence: dict[str, Any]) -> str:
    return " ".join(
        [
            str(evidence.get("fact_type") or ""),
            str(evidence.get("quote_text") or ""),
            str(evidence.get("summary") or ""),
        ]
    ).lower()


def _has_negative(text: str) -> bool:
    return bool(re.search(r"\b(cannot|can't|can not|never|forbidden|prohibited|impossible)\b", text)) or any(
        token in text for token in ("不能", "不可", "禁止", "无法", "不允许")
    )


def _has_positive(text: str) -> bool:
    return bool(re.search(r"\b(can|may|allowed|possible|must|always)\b", text)) or any(
        token in text for token in ("可以", "允许", "必须", "必然", "能够")
    )


def _has_dead(text: str) -> bool:
    return any(token in text for token in ("死亡", "死去", "陨落", "dead", "dies", "died"))


def _has_alive(text: str) -> bool:
    return any(token in text for token in ("活着", "复活", "苏醒", "alive", "revived", "awakens"))
