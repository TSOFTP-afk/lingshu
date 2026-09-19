from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.card_generators_v3 import (
    V3_CARD_MIN_FACT_CONFIDENCE,
    build_v3_book_card,
    build_v3_entity_card,
)
from novel_app.analysis.entity_store import EntityStore
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.schemas_v3 import stable_hash
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database

logger = logging.getLogger(__name__)

# M5 卡片生成 AI 调用并发上限
# build_v3_*_card 是纯函数（不修改共享状态），可安全并发
CARD_AI_MAX_WORKERS = int(os.environ.get("LINGSHU_CARD_AI_MAX_WORKERS", "6") or 6)


@dataclass(frozen=True)
class CardCoordinatorResult:
    event_count: int
    card_count: int
    active_card_count: int
    dependency_count: int
    engine: str = "rule"

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "card_count": self.card_count,
            "active_card_count": self.active_card_count,
            "dependency_count": self.dependency_count,
            "engine": self.engine,
        }


class CardCoordinator:
    def __init__(
        self,
        database: Database,
        *,
        store: AnalysisStore | None = None,
        entity_store: EntityStore | None = None,
        fact_store: FactStore | None = None,
        min_fact_confidence: float = V3_CARD_MIN_FACT_CONFIDENCE,
    ) -> None:
        self.database = database
        self.store = store or AnalysisStore(database)
        self.entity_store = entity_store or EntityStore(database)
        self.fact_store = fact_store or FactStore(database)
        self.min_fact_confidence = max(0.0, min(1.0, float(min_fact_confidence)))
        self._lock = threading.Lock()

    def run(
        self,
        *,
        book_id: int,
        run_id: int,
        target_entity_uids: set[str] | list[str] | tuple[str, ...] | None = None,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> CardCoordinatorResult:
        with self._lock:
            return self._run_internal(
                book_id=book_id,
                run_id=run_id,
                target_entity_uids=target_entity_uids,
                use_ai=use_ai,
                ai_provider=ai_provider,
            )

    def _run_internal(
        self,
        *,
        book_id: int,
        run_id: int,
        target_entity_uids: set[str] | list[str] | tuple[str, ...] | None = None,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> CardCoordinatorResult:
        target_entities = {str(uid or "").strip() for uid in (target_entity_uids or []) if str(uid or "").strip()}
        facts = [
            fact
            for fact in self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)
            if _eligible_fact(fact, self.min_fact_confidence)
        ]
        entities = {
            str(entity.get("entity_uid") or ""): entity
            for entity in self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None)
        }
        events = self._build_events(
            book_id=int(book_id),
            run_id=int(run_id),
            facts=facts,
            entities=entities,
            target_entity_uids=target_entities or None,
        )
        drafts_by_uid = {}
        dependency_count = 0
        processed_events: list[dict[str, Any]] = []
        ai_count = 0
        fallback_count = 0

        # ── 第一步：准备所有 event 参数，过滤无效 event ──
        # 收集 (event, payload, event_facts, entity_or_None) 元组
        event_tasks: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]] = []
        for event in events:
            payload = dict(event["payload"])
            event_facts = [fact for fact in facts if str(fact.get("fact_uid") or "") in set(payload.get("fact_uids") or [])]
            if not event_facts:
                continue
            if payload["card_type"] == "v3_book_summary":
                event_tasks.append((event, payload, event_facts, None))
            else:
                entity = entities.get(str(payload.get("entity_uid") or ""))
                if not entity:
                    continue
                event_tasks.append((event, payload, event_facts, entity))

        # ── 第二步：并发生成卡片 drafts（build_v3_*_card 是纯函数，不修改共享状态） ──
        # 结果按 event_tasks 原始索引存储，保持顺序
        draft_results: list[tuple[int, Any]] = [None] * len(event_tasks)  # type: ignore[list-item]

        def _build_one(idx: int, task: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]) -> tuple[int, Any]:
            _event, payload, event_facts, entity = task
            try:
                if payload["card_type"] == "v3_book_summary":
                    draft = build_v3_book_card(
                        book_id=int(book_id),
                        run_id=int(run_id),
                        facts=event_facts,
                        dependency_hash=str(payload["dependency_hash"]),
                        use_ai=use_ai,
                        ai_provider=ai_provider,
                    )
                else:
                    draft = build_v3_entity_card(
                        book_id=int(book_id),
                        run_id=int(run_id),
                        entity=entity,
                        facts=event_facts,
                        card_type=str(payload["card_type"]),
                        dependency_hash=str(payload["dependency_hash"]),
                        use_ai=use_ai,
                        ai_provider=ai_provider,
                    )
                return idx, draft
            except Exception as exc:
                logger.warning("M5 card build failed for event idx=%d: %s", idx, exc)
                return idx, None

        if event_tasks:
            worker_count = max(1, min(len(event_tasks), CARD_AI_MAX_WORKERS))
            if use_ai and ai_provider is not None:
                logger.info("M5 卡片生成: %d events, %d 并发 worker", len(event_tasks), worker_count)
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="card-ai") as executor:
                futures = [executor.submit(_build_one, i, task) for i, task in enumerate(event_tasks)]
                for future in as_completed(futures):
                    idx, draft = future.result()
                    draft_results[idx] = (idx, draft)

        # ── 第三步：串行执行 DB 写入（有依赖关系：supersede → create → dependencies） ──
        for _i, (idx, draft) in enumerate(draft_results):
            if draft is None:
                continue
            event, payload, event_facts, _entity = event_tasks[idx]
            if use_ai:
                source_rule = str(draft.payload.get("source_rule") or "")
                if source_rule == "ai_llm_card":
                    ai_count += 1
                else:
                    fallback_count += 1
            self.store.mark_cards_superseded(
                int(book_id),
                int(run_id),
                card_type=draft.card_type,
                entity_uid=draft.entity_uid,
                keep_card_uid=draft.card_uid,
            )
            self.store.create_card_if_absent(int(book_id), int(run_id), draft)
            dependencies = _dependencies_for_card(draft.card_uid, event_facts, str(payload.get("entity_uid") or draft.entity_uid))
            dependency_count += len(self.store.replace_card_dependencies(int(book_id), int(run_id), draft.card_uid, dependencies))
            drafts_by_uid[draft.card_uid] = draft
            processed_payload = {**payload, "card_uid": draft.card_uid}
            processed_events.append({**event, "payload": processed_payload, "status": "processed", "attempts": 1})

        if target_entities:
            event_ids = self.store.upsert_events(int(book_id), int(run_id), processed_events)
        else:
            event_ids = self.store.replace_events(int(book_id), int(run_id), processed_events)
        cards = [dict(row) for row in self.store.list_cards(int(run_id))]
        active_cards = [card for card in cards if str(card.get("status") or "") != "superseded"]
        if use_ai:
            if ai_count > 0 and fallback_count == 0:  # noqa: SIM108 — 外层还依赖 use_ai 分支，ruff 建议的三元会丢分支
                engine = "ai"
            else:
                engine = "rule_fallback"
        else:
            engine = "rule"
        self._last_card_engine = engine
        return CardCoordinatorResult(
            event_count=len(event_ids),
            card_count=len(cards),
            active_card_count=len(active_cards),
            dependency_count=dependency_count,
            engine=engine,
        )

    def _build_events(
        self,
        *,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
        entities: dict[str, dict[str, Any]],
        target_entity_uids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        facts_by_entity: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            entity_uid = str(fact.get("subject_entity_uid") or "")
            if target_entity_uids is not None and entity_uid not in target_entity_uids:
                continue
            if entity_uid and entity_uid in entities:
                facts_by_entity.setdefault(entity_uid, []).append(fact)

        for entity_uid, entity_facts in sorted(facts_by_entity.items()):
            entity = entities[entity_uid]
            card_type = "v3_character" if str(entity.get("entity_type") or "") == "character" else "v3_world"
            events.append(_event_for_card(book_id, run_id, card_type, entity_uid, entity_facts))

        if facts:
            events.append(_event_for_card(book_id, run_id, "v3_book_summary", f"BOOK-{int(book_id)}::V3-BOOK-SUMMARY", facts))
        return events


def _event_for_card(
    book_id: int,
    run_id: int,
    card_type: str,
    entity_uid: str,
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    fact_uids = sorted({str(fact.get("fact_uid") or "") for fact in facts if str(fact.get("fact_uid") or "")})
    dependency_hash = stable_hash("|".join([card_type, entity_uid, *fact_uids]))
    event_uid = f"EVT-V3-CARD-{stable_hash('|'.join([str(book_id), str(run_id), card_type, entity_uid, dependency_hash]))[:16]}"
    return {
        "event_uid": event_uid,
        "event_type": "v3_card_requested",
        "payload": {
            "card_type": card_type,
            "entity_uid": entity_uid,
            "fact_uids": fact_uids,
            "dependency_hash": dependency_hash,
        },
        "status": "pending",
        "priority": 10 if card_type == "v3_book_summary" else 20,
        "attempts": 0,
    }


def _dependencies_for_card(card_uid: str, facts: list[dict[str, Any]], entity_uid: str) -> list[dict[str, Any]]:
    dependencies = [
        {
            "card_uid": card_uid,
            "dependency_type": "entity",
            "dependency_uid": entity_uid,
            "dependency_hash": stable_hash(entity_uid),
        }
    ]
    seen_blocks: set[str] = set()
    for fact in facts:
        fact_uid = str(fact.get("fact_uid") or "")
        if fact_uid:
            dependencies.append(
                {
                    "card_uid": card_uid,
                    "dependency_type": "fact",
                    "dependency_uid": fact_uid,
                    "dependency_hash": stable_hash("|".join([fact_uid, str(fact.get("quote_text") or ""), str(fact.get("confidence") or "")])),
                }
            )
        block_uid = str(fact.get("block_uid") or "")
        if block_uid and block_uid not in seen_blocks:
            seen_blocks.add(block_uid)
            dependencies.append(
                {
                    "card_uid": card_uid,
                    "dependency_type": "block",
                    "dependency_uid": block_uid,
                    "dependency_hash": stable_hash(block_uid),
                }
            )
    return dependencies


def _eligible_fact(fact: dict[str, Any], min_confidence: float) -> bool:
    if str(fact.get("status") or "candidate") != "candidate":
        return False
    if float(fact.get("confidence") or 0.0) < min_confidence:
        return False
    return bool(str(fact.get("subject_entity_uid") or "") and str(fact.get("quote_text") or ""))
