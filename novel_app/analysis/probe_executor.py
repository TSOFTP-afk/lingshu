from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_app.analysis.backtrack import BacktrackPlanner
from novel_app.analysis.consistency_checker import ConsistencyChecker
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database


@dataclass(frozen=True)
class ProbeExecutionResult:
    plan_count: int
    result_count: int
    inconsistent_count: int
    manual_review_count: int
    backtrack_task_count: int
    results: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "probe_plan_count": self.plan_count,
            "probe_result_count": self.result_count,
            "probe_inconsistent_count": self.inconsistent_count,
            "probe_manual_review_count": self.manual_review_count,
            "backtrack_task_count": self.backtrack_task_count,
            "results": list(self.results),
        }


class ProbeExecutor:
    def __init__(
        self,
        database: Database,
        *,
        store: AnalysisStore | None = None,
        fact_store: FactStore | None = None,
        checker: ConsistencyChecker | None = None,
        backtrack_planner: BacktrackPlanner | None = None,
    ) -> None:
        self.database = database
        self.store = store or AnalysisStore(database)
        self.fact_store = fact_store or FactStore(database)
        self.checker = checker or ConsistencyChecker()
        self.backtrack_planner = backtrack_planner or BacktrackPlanner(database, store=self.store, fact_store=self.fact_store)

    def execute(
        self,
        *,
        book_id: int,
        run_id: int,
        plans: list[dict[str, Any]] | None = None,
        facts: list[dict[str, Any]] | None = None,
    ) -> ProbeExecutionResult:
        source_plans = plans if plans is not None else self.store.list_probe_plans(int(book_id), run_id=int(run_id), limit=None)
        source_facts = facts if facts is not None else self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)
        results: list[dict[str, Any]] = []
        backtrack_tasks: list[dict[str, Any]] = []

        for plan in source_plans:
            checked = self.checker.check(plan, source_facts)
            checked["probe_mode"] = plan.get("probe_mode", "passive")
            if checked["consistency"] == "inconsistent":
                task = self._plan_backtrack_for_inconsistency(int(book_id), int(run_id), plan, checked)
                if task:
                    backtrack_tasks.append(task)
                    result_payload = dict(checked["result"])
                    result_payload["backtrack_task"] = {
                        "task_uid": task.get("task_uid"),
                        "target_uid": task.get("target_uid"),
                        "status": task.get("status"),
                    }
                    checked = {**checked, "result": result_payload}
            results.append(checked)

        result_ids = self.store.replace_probe_results(int(book_id), int(run_id), results)
        inconsistent_count = sum(1 for item in results if item.get("consistency") == "inconsistent")
        manual_review_count = sum(1 for item in results if item.get("status") == "manual_review")
        return ProbeExecutionResult(
            plan_count=len(source_plans),
            result_count=len(result_ids),
            inconsistent_count=inconsistent_count,
            manual_review_count=manual_review_count,
            backtrack_task_count=len({str(task.get("task_uid") or "") for task in backtrack_tasks if str(task.get("task_uid") or "")}),
            results=results,
        )

    def _plan_backtrack_for_inconsistency(
        self,
        book_id: int,
        run_id: int,
        plan: dict[str, Any],
        checked: dict[str, Any],
    ) -> dict[str, Any] | None:
        subject_uid = str(plan.get("subject_entity_uid") or checked.get("result", {}).get("subject", {}).get("entity_uid") or "").strip()
        if not subject_uid:
            return None
        probe_uid = str(checked.get("probe_uid") or plan.get("probe_uid") or "")
        finding = str(checked.get("result", {}).get("finding") or "probe inconsistency")
        return self.backtrack_planner.plan_task(
            book_id=book_id,
            run_id=run_id,
            trigger_type="probe_inconsistent",
            target_uid=subject_uid,
            reason=f"{probe_uid}: {finding}",
            priority=80,
        )
