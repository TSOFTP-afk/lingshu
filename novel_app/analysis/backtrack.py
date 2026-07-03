from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.card_coordinator import CardCoordinator, CardCoordinatorResult
from novel_app.analysis.entity_store import EntityStore
from novel_app.analysis.fact_extractor import FactExtractor
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.memory_classifier import MemoryClassifier
from novel_app.analysis.memory_compressor import MemoryCompressor
from novel_app.analysis.schemas_v3 import stable_hash
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database


@dataclass(frozen=True)
class BacktrackTaskResult:
    task: dict[str, Any]
    fact_count: int
    card_result: CardCoordinatorResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "fact_count": self.fact_count,
            "card_result": self.card_result.as_dict(),
        }


class BacktrackPlanner:
    def __init__(
        self,
        database: Database,
        *,
        store: AnalysisStore | None = None,
        entity_store: EntityStore | None = None,
        fact_store: FactStore | None = None,
        card_coordinator: CardCoordinator | None = None,
        memory_classifier: MemoryClassifier | None = None,
        memory_compressor: MemoryCompressor | None = None,
    ) -> None:
        self.database = database
        self.store = store or AnalysisStore(database)
        self.entity_store = entity_store or EntityStore(database)
        self.fact_store = fact_store or FactStore(database)
        self.memory_classifier = memory_classifier or MemoryClassifier()
        self.memory_compressor = memory_compressor or MemoryCompressor()
        self.card_coordinator = card_coordinator or CardCoordinator(
            database,
            store=self.store,
            entity_store=self.entity_store,
            fact_store=self.fact_store,
        )

    def plan_task(
        self,
        *,
        book_id: int,
        run_id: int,
        trigger_type: str,
        target_uid: str,
        reason: str = "",
        priority: int = 50,
    ) -> dict[str, Any]:
        impact = self.calculate_impact(
            book_id=int(book_id),
            run_id=int(run_id),
            trigger_type=trigger_type,
            target_uid=target_uid,
        )
        if reason:
            impact["reason"] = str(reason)
        task_uid = _task_uid(int(book_id), int(run_id), trigger_type, target_uid)
        row = self.store.create_backtrack_task(
            int(book_id),
            int(run_id),
            task_uid=task_uid,
            trigger_type=str(trigger_type or "manual"),
            target_uid=str(target_uid or ""),
            impact=impact,
            status="pending",
            priority=priority,
        )
        task = _backtrack_task_row(row)
        self.store.create_audit_log(
            int(book_id),
            run_id=int(run_id),
            action="analysis_v3_backtrack_task_created",
            target_type="analysis_backtrack_task",
            target_uid=task_uid,
            new_value=task,
            reason="analysis v3 m6 backtrack impact task created",
        )
        return task

    def calculate_impact(
        self,
        *,
        book_id: int,
        run_id: int,
        trigger_type: str,
        target_uid: str,
    ) -> dict[str, Any]:
        clean_target = str(target_uid or "").strip()
        clean_trigger = str(trigger_type or "manual").strip() or "manual"
        mentions = self.entity_store.list_mentions(int(book_id), run_id=int(run_id), limit=None)
        facts = self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)
        cards = [dict(row) for row in self.store.list_cards(int(run_id)) if str(row["card_type"] or "").startswith("v3_")]
        dependencies = [
            dict(row)
            for row in self.store.list_card_dependencies(int(book_id), run_id=int(run_id), limit=None)
        ]

        entity_uids: set[str] = set()
        mention_uids: set[str] = set()
        fact_uids: set[str] = set()
        block_uids: set[str] = set()
        card_uids: set[str] = set()
        chapter_ids: set[int] = set()

        if clean_target:
            if "card" in clean_trigger:
                card_uids.add(clean_target)
            elif "fact" in clean_trigger:
                fact_uids.add(clean_target)
            elif "mention" in clean_trigger:
                mention_uids.add(clean_target)
            elif "block" in clean_trigger:
                block_uids.add(clean_target)
            else:
                entity_uids.add(clean_target)

        for card in cards:
            if str(card.get("card_uid") or "") == clean_target:
                card_uids.add(clean_target)
                entity_uid = str(card.get("entity_uid") or "")
                if entity_uid:
                    entity_uids.add(entity_uid)

        for dependency in dependencies:
            if str(dependency.get("card_uid") or "") in card_uids:
                _collect_dependency(dependency, entity_uids, fact_uids, block_uids)

        changed = True
        while changed:
            before = (len(entity_uids), len(mention_uids), len(fact_uids), len(block_uids), len(card_uids), len(chapter_ids))
            for mention in mentions:
                mention_uid = str(mention.get("mention_uid") or "")
                mention_entity_uid = str(mention.get("entity_uid") or "")
                mention_block_uid = str(mention.get("block_uid") or "")
                if mention_uid in mention_uids or mention_entity_uid in entity_uids or mention_block_uid in block_uids:
                    if mention_uid:
                        mention_uids.add(mention_uid)
                    if mention_entity_uid:
                        entity_uids.add(mention_entity_uid)
                    if mention_block_uid:
                        block_uids.add(mention_block_uid)
                    chapter_id = _int_or_none(mention.get("chapter_id"))
                    if chapter_id is not None:
                        chapter_ids.add(chapter_id)

            for fact in facts:
                fact_uid = str(fact.get("fact_uid") or "")
                fact_entity_uid = str(fact.get("subject_entity_uid") or "")
                fact_block_uid = str(fact.get("block_uid") or "")
                if fact_uid in fact_uids or fact_entity_uid in entity_uids or fact_block_uid in block_uids:
                    if fact_uid:
                        fact_uids.add(fact_uid)
                    if fact_entity_uid:
                        entity_uids.add(fact_entity_uid)
                    if fact_block_uid:
                        block_uids.add(fact_block_uid)
                    chapter_id = _int_or_none(fact.get("chapter_id"))
                    if chapter_id is not None:
                        chapter_ids.add(chapter_id)

            dependency_targets = entity_uids | fact_uids | block_uids
            for dependency in dependencies:
                dependency_uid = str(dependency.get("dependency_uid") or "")
                if dependency_uid in dependency_targets:
                    card_uid = str(dependency.get("card_uid") or "")
                    if card_uid:
                        card_uids.add(card_uid)
            changed = before != (len(entity_uids), len(mention_uids), len(fact_uids), len(block_uids), len(card_uids), len(chapter_ids))

        return {
            "trigger_type": clean_trigger,
            "target_uid": clean_target,
            "entity_uids": sorted(entity_uids),
            "mention_uids": sorted(mention_uids),
            "fact_uids": sorted(fact_uids),
            "block_uids": sorted(block_uids),
            "card_uids": sorted(card_uids),
            "chapter_ids": sorted(chapter_ids),
            "counts": {
                "entities": len(entity_uids),
                "mentions": len(mention_uids),
                "facts": len(fact_uids),
                "blocks": len(block_uids),
                "cards": len(card_uids),
                "chapters": len(chapter_ids),
            },
        }

    def execute_task(self, *, book_id: int, run_id: int, task_id: int) -> BacktrackTaskResult:
        task_row = self.store.get_backtrack_task(int(task_id))
        if task_row is None or int(task_row["book_id"]) != int(book_id) or int(task_row["run_id"]) != int(run_id):
            raise ValueError("backtrack task not found")
        running = self.store.update_backtrack_task_status(int(task_id), "running")
        task = _backtrack_task_row(running or task_row)
        impact = dict(task.get("impact") or {})
        block_uids = [str(item) for item in impact.get("block_uids") or [] if str(item)]
        entity_uids = [str(item) for item in impact.get("entity_uids") or [] if str(item)]

        try:
            source_blocks = [
                dict(row)
                for row in self.store.list_blocks(int(book_id), run_id=int(run_id), limit=None)
                if str(row["block_uid"] or "") in set(block_uids)
            ]
            mentions = self.entity_store.list_mentions(int(book_id), run_id=int(run_id), limit=None)
            entities = self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None)
            facts = FactExtractor().extract_from_context(
                book_id=int(book_id),
                run_id=int(run_id),
                blocks=source_blocks,
                mentions=mentions,
                entities=entities,
            )
            fact_ids = self.fact_store.replace_facts_for_scope(
                int(book_id),
                int(run_id),
                facts,
                block_uids=block_uids,
                entity_uids=entity_uids,
            )
            all_facts = self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)
            classified = self.memory_classifier.classify_facts(
                [fact for fact in all_facts if str(fact.get("fact_type") or "") != "memory_summary"]
            )
            compressed = self.memory_compressor.compress(classified)
            self.fact_store.replace_facts(int(book_id), int(run_id), compressed)
            target_entities = sorted({*entity_uids, *(str(fact.subject_entity_uid) for fact in facts if str(fact.subject_entity_uid))})
            card_result = self.card_coordinator.run(
                book_id=int(book_id),
                run_id=int(run_id),
                target_entity_uids=target_entities,
            )
            completed_impact = {
                **impact,
                "result": {
                    "recomputed_fact_count": len(fact_ids),
                    "memory_fact_count": len(classified),
                    "memory_summary_fact_count": sum(1 for fact in compressed if str(fact.get("fact_type") or "") == "memory_summary"),
                    "active_card_count": card_result.active_card_count,
                    "event_count": card_result.event_count,
                    "formal_writeback": False,
                },
            }
            completed = self.store.update_backtrack_task_status(
                int(task_id),
                "completed",
                impact=completed_impact,
            )
            self._mark_run_backtracked(
                int(book_id),
                int(run_id),
                task_uid=str(task.get("task_uid") or ""),
                task_count=len(self.store.list_backtrack_tasks(int(book_id), run_id=int(run_id), limit=None)),
                fact_count=len(self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)),
                card_result=card_result,
            )
            task = _backtrack_task_row(completed or task_row)
            self.store.create_audit_log(
                int(book_id),
                run_id=int(run_id),
                action="analysis_v3_backtrack_task_completed",
                target_type="analysis_backtrack_task",
                target_uid=str(task.get("task_uid") or ""),
                new_value=task,
                reason="analysis v3 m6 backtrack task executed without formal writeback",
            )
            return BacktrackTaskResult(task=task, fact_count=len(fact_ids), card_result=card_result)
        except Exception as exc:
            self.store.update_backtrack_task_status(int(task_id), "failed", error_text=str(exc))
            raise

    def _mark_run_backtracked(
        self,
        book_id: int,
        run_id: int,
        *,
        task_uid: str,
        task_count: int,
        fact_count: int,
        card_result: CardCoordinatorResult,
    ) -> None:
        run = self.store.get_run(int(run_id))
        meta = _existing_run_meta(run)
        meta.update(
            {
                "pipeline_family": "analysis_v3",
                "current_phase": "M6",
                "current_step": "backtrack",
                "next_step": "memory_layer",
                "backtrack_task_count": int(task_count),
                "last_backtrack_task_uid": task_uid,
                "fact_count": int(fact_count),
                "event_count": int(card_result.event_count),
                "card_count": int(card_result.active_card_count),
                "ai_invoked": False,
            }
        )
        self.store.update_run_status(
            int(run_id),
            "backtrack_ready",
            summary=f"Backtrack task {task_uid} completed; affected facts/cards were regenerated as V3 drafts.",
            meta=meta,
        )


def _task_uid(book_id: int, run_id: int, trigger_type: str, target_uid: str) -> str:
    seed = "|".join([str(book_id), str(run_id), str(trigger_type or "manual"), str(target_uid or "")])
    return f"BT-{stable_hash(seed)[:16]}"


def _collect_dependency(
    dependency: dict[str, Any],
    entity_uids: set[str],
    fact_uids: set[str],
    block_uids: set[str],
) -> None:
    dependency_type = str(dependency.get("dependency_type") or "")
    dependency_uid = str(dependency.get("dependency_uid") or "")
    if not dependency_uid:
        return
    if dependency_type == "entity":
        entity_uids.add(dependency_uid)
    elif dependency_type == "fact":
        fact_uids.add(dependency_uid)
    elif dependency_type == "block":
        block_uids.add(dependency_uid)


def _backtrack_task_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "task_uid": str(row["task_uid"] or ""),
        "trigger_type": str(row["trigger_type"] or ""),
        "target_uid": str(row["target_uid"] or ""),
        "impact": _json_object(str(row["impact_json"] or "{}")),
        "status": str(row["status"] or ""),
        "priority": int(row["priority"] or 0),
        "error_text": str(row["error_text"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def _existing_run_meta(run: Any) -> dict[str, Any]:
    if not run:
        return {}
    return _json_object(str(run["meta_json"] or "{}"))


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
