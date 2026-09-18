from __future__ import annotations

import json
import sqlite3
from typing import Any

from novel_app.analysis.evidence import resolve_evidence_refs
from novel_app.analysis.models import AnalysisCardDraft
from novel_app.database import Database


class AnalysisStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_run(
        self,
        book_id: int,
        *,
        scope_type: str = "book",
        status: str = "created",
        pipeline_version: str = "draft_mvp_v1",
        meta: dict[str, Any] | None = None,
        summary: str = "",
        input_hash: str = "",
    ) -> int:
        return self.database.create_analysis_run(
            book_id,
            scope_type=scope_type,
            status=status,
            pipeline_version=pipeline_version,
            meta=meta,
            summary=summary,
            input_hash=input_hash,
        )

    def update_run_status(
        self,
        run_id: int,
        status: str,
        *,
        summary: str = "",
        error_text: str = "",
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.database.update_analysis_run_status(
            run_id,
            status,
            summary=summary,
            error_text=error_text,
            meta=meta,
        )

    def get_run(self, run_id: int) -> sqlite3.Row | None:
        return self.database.get_analysis_run(run_id)

    def list_runs(self, book_id: int, limit: int = 20) -> list[sqlite3.Row]:
        return self.database.list_analysis_runs(book_id, limit=limit)

    def create_card(self, book_id: int, run_id: int, draft: AnalysisCardDraft) -> int:
        return self.database.create_analysis_card(
            book_id,
            run_id,
            draft.card_uid,
            draft.card_type,
            draft.payload,
            draft.diff,
            draft.status,
            entity_uid=draft.entity_uid,
            ars_score=draft.ars_score,
        )

    def create_card_if_absent(self, book_id: int, run_id: int, draft: AnalysisCardDraft) -> int:
        return self.database.create_analysis_card_if_absent(
            book_id,
            run_id,
            draft.card_uid,
            draft.card_type,
            draft.payload,
            draft.diff,
            draft.status,
            entity_uid=draft.entity_uid,
            ars_score=draft.ars_score,
        )

    def mark_cards_superseded(
        self,
        book_id: int,
        run_id: int,
        *,
        card_type: str,
        entity_uid: str,
        keep_card_uid: str,
    ) -> None:
        self.database.mark_analysis_cards_superseded(
            book_id,
            run_id,
            card_type=card_type,
            entity_uid=entity_uid,
            keep_card_uid=keep_card_uid,
        )

    def supersede_card_by_uid(self, run_id: int, card_uid: str) -> None:
        """标记单张卡片为 superseded（后处理用）。"""
        self.database.connection.execute(
            "UPDATE analysis_cards SET status='superseded', updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND card_uid=?",
            (run_id, card_uid),
        )

    def update_card_type(self, run_id: int, card_uid: str, new_type: str) -> None:
        """更新卡片类型（后处理用）。"""
        self.database.connection.execute(
            "UPDATE analysis_cards SET card_type=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND card_uid=?",
            (new_type, run_id, card_uid),
        )

    def fix_card_entity_type(self, run_id: int, card_uid: str, new_entity_type: str) -> None:
        """修正卡片实体类型并同步更新 payload_json 中的 entity_type 和 writeback_target。

        后处理用：当 LLM 判定某卡片的 entity_type 标注错误时，
        同时更新 card_type 列和 payload_json 内的关联字段。
        """
        import json

        from novel_app.analysis.card_generators_v3 import _writeback_target_for_entity

        # 读取当前 payload_json
        row = self.database.connection.execute(
            "SELECT payload_json FROM analysis_cards WHERE run_id=? AND card_uid=?",
            (run_id, card_uid),
        ).fetchone()
        if not row:
            return

        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except (json.JSONDecodeError, TypeError):
            return

        # 更新 entity_type 和 writeback_target
        payload["entity_type"] = new_entity_type
        payload["writeback_target"] = _writeback_target_for_entity(new_entity_type)
        # 如果是 world_entry，确保有 category 字段
        if payload["writeback_target"] == "world_entry":
            wb_fields = payload.get("writeback_fields") or {}
            if isinstance(wb_fields, dict) and not wb_fields.get("category"):
                wb_fields["category"] = new_entity_type
                payload["writeback_fields"] = wb_fields

        new_card_type = "v3_character" if new_entity_type == "character" else "v3_world"

        self.database.connection.execute(
            """UPDATE analysis_cards
               SET card_type=?, payload_json=?, updated_at=CURRENT_TIMESTAMP
               WHERE run_id=? AND card_uid=?""",
            (new_card_type, json.dumps(payload, ensure_ascii=False), run_id, card_uid),
        )

    def save_cards(self, book_id: int, run_id: int, drafts: list[AnalysisCardDraft]) -> list[int]:
        return [self.create_card(book_id, run_id, draft) for draft in drafts]

    def save_cards_if_absent(self, book_id: int, run_id: int, drafts: list[AnalysisCardDraft]) -> list[int]:
        return [self.create_card_if_absent(book_id, run_id, draft) for draft in drafts]

    def upsert_card_by_uid(self, book_id: int, run_id: int, draft: AnalysisCardDraft) -> int:
        return self.database.upsert_analysis_card_by_uid(
            book_id,
            run_id,
            draft.card_uid,
            draft.card_type,
            draft.payload,
            draft.diff,
            draft.status,
            entity_uid=draft.entity_uid,
            ars_score=draft.ars_score,
        )

    def list_cards_by_chapter(
        self,
        book_id: int,
        chapter_id: int,
        *,
        card_type: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        return self.database.list_analysis_cards_by_chapter(
            book_id, chapter_id, card_type=card_type, limit=limit
        )

    def save_blocks(self, book_id: int, run_id: int, blocks: list[dict[str, Any]]) -> list[int]:
        return self.database.create_analysis_blocks(book_id, run_id, blocks)

    def find_reusable_run_for_input_hash(
        self,
        book_id: int,
        input_hash: str,
        *,
        exclude_run_id: int | None = None,
    ) -> sqlite3.Row | None:
        """查找具有相同 book_id + input_hash 且已产生 block 的历史 run。"""
        return self.database.find_reusable_run_for_input_hash(
            book_id, input_hash, exclude_run_id=exclude_run_id,
        )

    def clone_blocks(self, book_id: int, source_run_id: int, target_run_id: int) -> int:
        """从 source_run_id 克隆 analysis_blocks 到 target_run_id，返回克隆行数。"""
        return self.database.clone_analysis_blocks(book_id, source_run_id, target_run_id)

    def list_blocks(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        chapter_id: int | None = None,
        limit: int | None = 500,
    ) -> list[sqlite3.Row]:
        return self.database.list_analysis_blocks(book_id, run_id=run_id, chapter_id=chapter_id, limit=limit)

    def get_block(self, book_id: int, block_uid: str, *, run_id: int | None = None) -> sqlite3.Row | None:
        return self.database.get_analysis_block(book_id, block_uid, run_id=run_id)

    def mark_blocks_indexed(self, book_id: int, run_id: int, block_uids: list[str]) -> None:
        self.database.mark_analysis_blocks_indexed(book_id, run_id, block_uids)

    def resolve_payload_evidence(self, book_id: int, payload: dict[str, Any], *, run_id: int | None = None) -> dict[str, Any]:
        def lookup(block_uid: str) -> sqlite3.Row | None:
            return self.database.get_analysis_block(book_id, block_uid, run_id=run_id)

        return resolve_evidence_refs(payload, lookup).as_dict()

    def list_cards(self, run_id: int) -> list[sqlite3.Row]:
        return self.database.list_analysis_cards(run_id)

    def replace_events(self, book_id: int, run_id: int, events: list[dict[str, Any]]) -> list[int]:
        return self.database.replace_analysis_events(book_id, run_id, events)

    def upsert_events(self, book_id: int, run_id: int, events: list[dict[str, Any]]) -> list[int]:
        return self.database.upsert_analysis_events(book_id, run_id, events)

    def list_events(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        return self.database.list_analysis_events(book_id, run_id=run_id, status=status, limit=limit)

    def replace_card_dependencies(
        self,
        book_id: int,
        run_id: int,
        card_uid: str,
        dependencies: list[dict[str, Any]],
    ) -> list[int]:
        return self.database.replace_analysis_card_dependencies(book_id, run_id, card_uid, dependencies)

    def list_card_dependencies(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        card_uid: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        return self.database.list_analysis_card_dependencies(book_id, run_id=run_id, card_uid=card_uid, limit=limit)

    def apply_card(
        self,
        book_id: int,
        run_id: int,
        card_uid: str,
        *,
        actor: str = "user",
        writeback_generator: Any | None = None,
        require_writeback_generator: bool = False,
    ) -> sqlite3.Row | None:
        """将候选卡片写回到业务表并标记为已写回（applied）。"""
        import logging

        from novel_app.analysis.v3_writeback import writeback_v3_card

        _logger = logging.getLogger(__name__)

        # 查找卡片
        card = self.database.connection.execute(
            "SELECT * FROM analysis_cards WHERE book_id = ? AND run_id = ? AND card_uid = ?",
            (book_id, run_id, card_uid),
        ).fetchone()
        if not card:
            return None

        # 执行写回
        result = writeback_v3_card(
            self.database,
            book_id,
            dict(card),
            writeback_generator=writeback_generator,
            require_generator=require_writeback_generator,
        )

        if not result.success:
            _logger.warning("V3 card writeback failed: %s", result.detail)
            self.create_audit_log(
                book_id,
                run_id=run_id,
                card_id=int(card["id"]),
                action="analysis_v3_card_writeback_failed",
                target_type=str(card["card_type"] or "analysis_card"),
                target_uid=card_uid,
                old_value={"snapshot_id": result.snapshot_id},
                new_value={
                    "detail": result.detail,
                    "writeback_generation_used": result.generation_used,
                    "writeback_generation": result.generation_metadata,
                },
                reason=result.detail,
                actor=actor,
            )
            # 写回失败，不标记 applied，返回原状态
            return card

        if result.writeback_fields is not None or result.generation_metadata is not None:
            payload = _analysis_card_payload(card)
            if result.writeback_fields is not None:
                payload["writeback_fields"] = result.writeback_fields
            if result.generation_metadata is not None:
                payload["writeback_generation"] = result.generation_metadata
            self.database.connection.execute(
                "UPDATE analysis_cards SET payload_json = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE book_id = ? AND run_id = ? AND card_uid = ?",
                (json.dumps(payload, ensure_ascii=False), book_id, run_id, card_uid),
            )

        # 写回成功，标记 applied 并填充 applied_table/applied_id
        self.database.connection.execute(
            "UPDATE analysis_cards SET status = 'applied', applied_at = CURRENT_TIMESTAMP, "
            "applied_table = ?, applied_id = ? WHERE book_id = ? AND run_id = ? AND card_uid = ?",
            (result.applied_table, result.applied_id, book_id, run_id, card_uid),
        )
        self.database.connection.commit()
        self.create_audit_log(
            book_id,
            run_id=run_id,
            card_id=int(card["id"]),
            action="analysis_v3_card_writeback_applied",
            target_type=str(card["card_type"] or "analysis_card"),
            target_uid=card_uid,
            old_value={"snapshot_id": result.snapshot_id},
            new_value={
                "applied_table": result.applied_table,
                "applied_id": result.applied_id,
                "detail": result.detail,
                "writeback_generation_used": result.generation_used,
                "writeback_generation": result.generation_metadata,
            },
            reason=result.detail,
            actor=actor,
        )
        return self.database.connection.execute(
            "SELECT * FROM analysis_cards WHERE book_id = ? AND run_id = ? AND card_uid = ?",
            (book_id, run_id, card_uid),
        ).fetchone()

    def replace_probe_plans(self, book_id: int, run_id: int, plans: list[dict[str, Any]]) -> list[int]:
        return self.database.replace_analysis_probe_plans(book_id, run_id, plans)

    def list_probe_plans(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[dict[str, Any]]:
        rows = self.database.list_analysis_probe_plans(book_id, run_id=run_id, status=status, limit=limit)
        return [_probe_plan_row(row) for row in rows]

    def replace_probe_results(self, book_id: int, run_id: int, results: list[dict[str, Any]]) -> list[int]:
        return self.database.replace_analysis_probe_results(book_id, run_id, results)

    def list_probe_results(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        probe_uid: str | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[dict[str, Any]]:
        rows = self.database.list_analysis_probe_results(
            book_id,
            run_id=run_id,
            probe_uid=probe_uid,
            status=status,
            limit=limit,
        )
        return [_probe_result_row(row) for row in rows]

    def get_card(self, card_id: int) -> sqlite3.Row | None:
        return self.database.get_analysis_card(card_id)

    def create_backtrack_task(
        self,
        book_id: int,
        run_id: int,
        *,
        task_uid: str,
        trigger_type: str,
        target_uid: str,
        impact: dict[str, Any],
        status: str = "pending",
        priority: int = 50,
    ) -> sqlite3.Row:
        return self.database.create_analysis_backtrack_task(
            book_id,
            run_id,
            task_uid=task_uid,
            trigger_type=trigger_type,
            target_uid=target_uid,
            impact=impact,
            status=status,
            priority=priority,
        )

    def get_backtrack_task(self, task_id: int) -> sqlite3.Row | None:
        return self.database.get_analysis_backtrack_task(task_id)

    def list_backtrack_tasks(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        return self.database.list_analysis_backtrack_tasks(book_id, run_id=run_id, status=status, limit=limit)

    def update_backtrack_task_status(
        self,
        task_id: int,
        status: str,
        *,
        impact: dict[str, Any] | None = None,
        error_text: str = "",
    ) -> sqlite3.Row | None:
        return self.database.update_analysis_backtrack_task_status(task_id, status, impact=impact, error_text=error_text)

    def get_full_payload_card(self, run_id: int) -> sqlite3.Row | None:
        return self.database.get_analysis_full_payload_card(run_id)

    def mark_card_applied(
        self,
        card_id: int,
        *,
        applied_table: str = "",
        applied_id: int | None = None,
    ) -> None:
        self.database.mark_analysis_card_applied(card_id, applied_table=applied_table, applied_id=applied_id)

    def reject_card(self, card_id: int) -> None:
        self.database.mark_analysis_card_rejected(card_id)

    def update_card_diff(self, card_id: int, diff: dict[str, Any], *, status: str | None = None) -> None:
        self.database.update_analysis_card_diff(card_id, diff, status=status)

    def create_snapshot(
        self,
        book_id: int,
        run_id: int | None,
        label: str,
        snapshot: dict[str, Any],
    ) -> int:
        return self.database.create_analysis_apply_snapshot(book_id, run_id, label, snapshot)

    def create_audit_log(
        self,
        book_id: int,
        *,
        action: str,
        target_type: str,
        run_id: int | None = None,
        card_id: int | None = None,
        target_uid: str = "",
        old_value: Any = None,
        new_value: Any = None,
        reason: str = "",
        confidence: float = 0.0,
        actor: str = "system",
    ) -> int:
        return self.database.create_analysis_audit_log(
            book_id,
            action=action,
            target_type=target_type,
            run_id=run_id,
            card_id=card_id,
            target_uid=target_uid,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            confidence=confidence,
            actor=actor,
        )


def _probe_plan_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "probe_uid": str(row["probe_uid"] or ""),
        "probe_type": str(row["probe_type"] or ""),
        "subject_entity_uid": str(row["subject_entity_uid"] or ""),
        "plan": _json_object(str(row["plan_json"] or "{}")),
        "status": str(row["status"] or "pending"),
        "priority": int(row["priority"] or 0),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def _probe_result_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "probe_uid": str(row["probe_uid"] or ""),
        "result": _json_object(str(row["result_json"] or "{}")),
        "consistency": str(row["consistency"] or "unknown"),
        "confidence": float(row["confidence"] or 0.0),
        "status": str(row["status"] or "candidate"),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def _analysis_card_payload(row: Any) -> dict[str, Any]:
    try:
        raw = row["payload_json"]
    except (KeyError, IndexError, TypeError):
        raw = None
    if isinstance(raw, str) and raw:
        return _json_object(raw)
    if isinstance(row, dict):
        payload = row.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
