from __future__ import annotations

from novel_app.db.analysis_parts.common import *


class AnalysisProbesMixin:
    def replace_analysis_probe_plans(
        self,
        book_id: int,
        run_id: int,
        plans: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_probe_plans WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        plan_ids: list[int] = []
        for plan in plans:
            probe_uid = str(plan.get("probe_uid") or "").strip()
            if not probe_uid:
                continue
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_probe_plans (
                    book_id, run_id, probe_uid, probe_type, subject_entity_uid,
                    plan_json, status, priority
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    probe_uid,
                    str(plan.get("probe_type") or ""),
                    str(plan.get("subject_entity_uid") or ""),
                    self._json_payload(plan.get("plan") if isinstance(plan.get("plan"), dict) else {}),
                    str(plan.get("status") or "pending"),
                    self._analysis_int(plan.get("priority"), 0),
                ),
            )
            plan_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return plan_ids

    def list_analysis_probe_plans(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_probe_plans
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if status:
            sql += " AND status = ?"
            params.append(str(status))
        sql += " ORDER BY priority DESC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def replace_analysis_probe_results(
        self,
        book_id: int,
        run_id: int,
        results: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_probe_results WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        result_ids: list[int] = []
        for result in results:
            probe_uid = str(result.get("probe_uid") or "").strip()
            if not probe_uid:
                continue
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_probe_results (
                    book_id, run_id, probe_uid, result_json,
                    consistency, confidence, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    probe_uid,
                    self._json_payload(result.get("result") if isinstance(result.get("result"), dict) else {}),
                    str(result.get("consistency") or "unknown"),
                    float(result.get("confidence") or 0.0),
                    str(result.get("status") or "candidate"),
                ),
            )
            result_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return result_ids

    def list_analysis_probe_results(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        probe_uid: str | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_probe_results
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if probe_uid:
            sql += " AND probe_uid = ?"
            params.append(str(probe_uid))
        if status:
            sql += " AND status = ?"
            params.append(str(status))
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def create_analysis_backtrack_task(
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
        clean_task_uid = str(task_uid or "").strip()
        if not clean_task_uid:
            raise ValueError("backtrack task_uid is required")
        self.connection.execute(
            """
            INSERT INTO analysis_backtrack_tasks (
                book_id, run_id, task_uid, trigger_type, target_uid,
                impact_json, status, priority, error_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
            ON CONFLICT(book_id, run_id, task_uid) DO UPDATE SET
                trigger_type = excluded.trigger_type,
                target_uid = excluded.target_uid,
                impact_json = excluded.impact_json,
                status = excluded.status,
                priority = excluded.priority,
                error_text = '',
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                run_id,
                clean_task_uid,
                str(trigger_type or ""),
                str(target_uid or ""),
                self._json_payload(impact or {}),
                str(status or "pending"),
                self._analysis_int(priority, 50),
            ),
        )
        self.connection.commit()
        row = self.get_analysis_backtrack_task_by_uid(book_id, run_id, clean_task_uid)
        if row is None:
            raise RuntimeError("failed to create backtrack task")
        return row

    def get_analysis_backtrack_task(self, task_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            "SELECT * FROM analysis_backtrack_tasks WHERE id = ?",
            (int(task_id),),
        )
        return cursor.fetchone()

    def get_analysis_backtrack_task_by_uid(self, book_id: int, run_id: int, task_uid: str) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT *
            FROM analysis_backtrack_tasks
            WHERE book_id = ? AND run_id = ? AND task_uid = ?
            """,
            (book_id, run_id, str(task_uid or "")),
        )
        return cursor.fetchone()

    def list_analysis_backtrack_tasks(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_backtrack_tasks
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if status:
            sql += " AND status = ?"
            params.append(str(status))
        sql += " ORDER BY priority DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def update_analysis_backtrack_task_status(
        self,
        task_id: int,
        status: str,
        *,
        impact: dict[str, Any] | None = None,
        error_text: str = "",
    ) -> sqlite3.Row | None:
        if impact is None:
            self.connection.execute(
                """
                UPDATE analysis_backtrack_tasks
                SET status = ?, error_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(status or "pending"), str(error_text or ""), int(task_id)),
            )
        else:
            self.connection.execute(
                """
                UPDATE analysis_backtrack_tasks
                SET status = ?, impact_json = ?, error_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(status or "pending"), self._json_payload(impact), str(error_text or ""), int(task_id)),
            )
        self.connection.commit()
        return self.get_analysis_backtrack_task(int(task_id))

