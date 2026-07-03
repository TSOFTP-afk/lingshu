from __future__ import annotations

from novel_app.db.common import *


class ReviewMixin:
    def create_review_run(
        self,
        *,
        book_id: int,
        chapter_id: int | None,
        scope_type: str,
        status: str,
        truth_snapshot: str = "",
        summary: str = "",
        overall_score: int = 0,
        snapshot_id: int | None = None,
        revised_content: str = "",
        revised_outline: str = "",
        final_verdict: str = "",
        template_comparison: str = "",
        risk_notes: str = "",
        cross_summary: str = "",
        applied: bool = False,
    ) -> int:
        score = max(0, min(100, int(overall_score or 0)))
        cursor = self.connection.execute(
            """
            INSERT INTO review_runs (
                book_id,
                chapter_id,
                scope_type,
                status,
                truth_snapshot,
                summary,
                overall_score,
                snapshot_id,
                revised_content,
                revised_outline,
                final_verdict,
                template_comparison,
                risk_notes,
                cross_summary,
                applied_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (
                book_id,
                chapter_id,
                scope_type or "chapter",
                status or "completed",
                truth_snapshot,
                summary,
                score,
                snapshot_id,
                revised_content,
                revised_outline,
                final_verdict,
                template_comparison,
                risk_notes,
                cross_summary,
                1 if applied else 0,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def replace_review_findings(self, run_id: int, findings: list[dict[str, Any]]) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM review_findings WHERE run_id = ?", (run_id,))
            for item in findings:
                if not isinstance(item, dict):
                    continue
                issue = str(item.get("issue") or item.get("issue_text") or "").strip()
                suggestion = str(item.get("suggestion") or item.get("suggestion_text") or "").strip()
                if not issue and not suggestion:
                    continue
                severity = str(item.get("severity", "low")).strip().lower()
                if severity not in {"high", "medium", "low"}:
                    severity = "low"
                self.connection.execute(
                    """
                    INSERT INTO review_findings (
                        run_id,
                        agent,
                        severity,
                        category,
                        location_hint,
                        quote_text,
                        issue_text,
                        suggestion_text,
                        dimension,
                        conflict_with,
                        is_cross_chapter
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(item.get("agent", "")).strip(),
                        severity,
                        str(item.get("category", "")).strip(),
                        str(item.get("location_hint", "")).strip(),
                        str(item.get("quote") or item.get("quote_text") or "").strip(),
                        issue,
                        suggestion,
                        str(item.get("dimension", "")).strip(),
                        str(item.get("conflict_with", "")).strip(),
                        1 if item.get("is_cross_chapter") else 0,
                    ),
                )

    def list_review_runs(
        self,
        book_id: int,
        chapter_id: int | None = None,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT
                id,
                book_id,
                chapter_id,
                scope_type,
                status,
                summary,
                overall_score,
                snapshot_id,
                final_verdict,
                template_comparison,
                risk_notes,
                cross_summary,
                created_at,
                updated_at,
                applied_at
            FROM review_runs
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if chapter_id is not None:
            sql += " AND chapter_id = ?"
            params.append(chapter_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def get_review_run(self, run_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT
                id,
                book_id,
                chapter_id,
                scope_type,
                status,
                truth_snapshot,
                summary,
                overall_score,
                snapshot_id,
                revised_content,
                revised_outline,
                final_verdict,
                template_comparison,
                risk_notes,
                cross_summary,
                created_at,
                updated_at,
                applied_at
            FROM review_runs
            WHERE id = ?
            """,
            (run_id,),
        )
        return cursor.fetchone()

    def list_review_findings(self, run_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                id,
                run_id,
                agent,
                severity,
                category,
                location_hint,
                quote_text,
                issue_text,
                suggestion_text,
                created_at,
                IFNULL(dimension, '') as dimension,
                IFNULL(conflict_with, '') as conflict_with,
                IFNULL(is_cross_chapter, 0) as is_cross_chapter
            FROM review_findings
            WHERE run_id = ?
            ORDER BY
                CASE severity
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                id ASC
            """,
            (run_id,),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _json_payload(value: Any) -> str:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _json_object(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
