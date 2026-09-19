"""统计/用量仓储 — 从 store.py 按域搬移（SQL 与行为不变）。

承接：AI 用量与分析运行记录写入（user_analysis_runs / user_ai_usage_events）、
用量汇总（_usage_summary_for_*）、管理端统计报表（admin_overview / admin_user_stats）。
连接与事务模式照搬原 store.py：``with _connect(self.db_path) as connection`` + 显式 ``connection.commit()``。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from ..models import _connect
from ..security import _online_seconds_expr, _safe_int
from .auth_repository import _settle_expired_sessions
from .common import _validate_table

logger = logging.getLogger(__name__)


def _usage_summary_for_users(connection: sqlite3.Connection, user_ids: list[int]) -> dict[int, dict[str, Any]]:
    result = {
        int(user_id): {
            "online_seconds": 0,
            "analysis_count": 0,
            "analysis_input_chars": 0,
            "ai_prompt_tokens": 0,
            "ai_completion_tokens": 0,
            "ai_total_tokens": 0,
            "ai_input_chars": 0,
            "ai_output_chars": 0,
            "total_input_chars": 0,
            "fulltext_book_count": 0,
            "fulltext_char_count": 0,
        }
        for user_id in user_ids
    }
    if not user_ids:
        return result
    placeholders = ",".join("?" for _ in user_ids)
    for row in connection.execute(
        f"""
        SELECT user_id, COALESCE(SUM({_online_seconds_expr()}), 0) AS online_seconds
        FROM user_online_sessions
        WHERE user_id IN ({placeholders})
        GROUP BY user_id
        """,
        user_ids,
    ).fetchall():
        result[int(row["user_id"])]["online_seconds"] = int(row["online_seconds"] or 0)
    for row in connection.execute(
        f"""
        SELECT user_id, COUNT(*) AS analysis_count, COALESCE(SUM(input_chars), 0) AS input_chars
        FROM user_analysis_runs
        WHERE user_id IN ({placeholders})
        GROUP BY user_id
        """,
        user_ids,
    ).fetchall():
        summary = result[int(row["user_id"])]
        summary["analysis_count"] = int(row["analysis_count"] or 0)
        summary["analysis_input_chars"] = int(row["input_chars"] or 0)
    for row in connection.execute(
        f"""
        SELECT
            user_id,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(input_chars), 0) AS input_chars,
            COALESCE(SUM(output_chars), 0) AS output_chars
        FROM user_ai_usage_events
        WHERE user_id IN ({placeholders})
        GROUP BY user_id
        """,
        user_ids,
    ).fetchall():
        summary = result[int(row["user_id"])]
        summary["ai_prompt_tokens"] = int(row["prompt_tokens"] or 0)
        summary["ai_completion_tokens"] = int(row["completion_tokens"] or 0)
        summary["ai_total_tokens"] = int(row["total_tokens"] or 0)
        summary["ai_input_chars"] = int(row["input_chars"] or 0)
        summary["ai_output_chars"] = int(row["output_chars"] or 0)
    for row in connection.execute(
        f"""
        SELECT user_id, COUNT(*) AS book_count, COALESCE(SUM(char_count), 0) AS char_count
        FROM book_fulltexts
        WHERE user_id IN ({placeholders})
        GROUP BY user_id
        """,
        user_ids,
    ).fetchall():
        summary = result[int(row["user_id"])]
        summary["fulltext_book_count"] = int(row["book_count"] or 0)
        summary["fulltext_char_count"] = int(row["char_count"] or 0)
    for summary in result.values():
        summary["total_input_chars"] = int(summary["analysis_input_chars"] or 0) + int(summary["ai_input_chars"] or 0)
    return result


def _usage_summary_for_user(connection: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    return _usage_summary_for_users(connection, [int(user_id)]).get(int(user_id), {})


class StatsRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def record_user_analysis_run(
        self,
        *,
        user_id: int,
        book_id: int | None = None,
        analysis_mode: str = "",
        input_chars: int = 0,
        status: str = "completed",
        source: str = "",
        run_ref: str = "",
        metadata: dict[str, Any] | None = None,
        error_text: str = "",
    ) -> int:
        # book_id 是 novels.db 的本地 book_id，而 user_analysis_runs 表的 book_id
        # 外键引用 bookstore_demo.db 的 books(id)。跨库引用会导致 FOREIGN KEY constraint failed。
        # 此处先尝试带 book_id 插入，外键失败则置 NULL 重试，保证统计记录不丢失。
        effective_book_id = int(book_id) if book_id is not None else None
        params = (
            int(user_id),
            effective_book_id,
            str(run_ref or ""),
            str(analysis_mode or ""),
            max(0, _safe_int(input_chars)),
            str(status or "completed"),
            str(source or ""),
            str(error_text or "")[:2000],
            json.dumps(metadata or {}, ensure_ascii=False, default=str),
        )
        insert_sql = """
            INSERT INTO user_analysis_runs (
                user_id, book_id, run_ref, analysis_mode, input_chars, status,
                source, error_text, metadata, completed_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
        with _connect(self.db_path) as connection:
            try:
                cursor = connection.execute(insert_sql, params)
            except sqlite3.IntegrityError as exc:
                if "FOREIGN KEY" in str(exc).upper() and effective_book_id is not None:
                    logger.warning(
                        "record_user_analysis_run FOREIGN KEY failed for book_id=%s, retrying with NULL",
                        effective_book_id,
                    )
                    params = (params[0], None) + params[2:]
                    cursor = connection.execute(insert_sql, params)
                else:
                    raise
            connection.commit()
            return int(cursor.lastrowid)

    def record_user_ai_usage(
        self,
        *,
        user_id: int,
        feature: str,
        book_id: int | None = None,
        analysis_run_id: int | None = None,
        model: str = "",
        provider: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        token_source: str = "unknown",
        input_chars: int = 0,
        output_chars: int = 0,
        trace_id: str = "",
        prompt_version: str = "",
        schema_version: str = "",
        latency_ms: int = 0,
        status: str = "completed",
        error_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        resolved_prompt = max(0, _safe_int(prompt_tokens))
        resolved_completion = max(0, _safe_int(completion_tokens))
        resolved_total = max(0, _safe_int(total_tokens))
        if not resolved_total and (resolved_prompt or resolved_completion):
            resolved_total = resolved_prompt + resolved_completion
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO user_ai_usage_events (
                    user_id, book_id, analysis_run_id, feature, model, provider,
                    prompt_tokens, completion_tokens, total_tokens, token_source,
                    input_chars, output_chars, trace_id, prompt_version, schema_version,
                    latency_ms, status, error_text, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_id),
                    int(book_id) if book_id is not None else None,
                    int(analysis_run_id) if analysis_run_id is not None else None,
                    str(feature or ""),
                    str(model or ""),
                    str(provider or ""),
                    resolved_prompt,
                    resolved_completion,
                    resolved_total,
                    str(token_source or "unknown"),
                    max(0, _safe_int(input_chars)),
                    max(0, _safe_int(output_chars)),
                    str(trace_id or ""),
                    str(prompt_version or ""),
                    str(schema_version or ""),
                    max(0, _safe_int(latency_ms)),
                    str(status or "completed"),
                    str(error_text or "")[:2000],
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def admin_overview(self) -> dict[str, Any]:
        with _connect(self.db_path) as connection:
            _settle_expired_sessions(connection)
            counts = {
                "users": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "active_users": connection.execute("SELECT COUNT(*) FROM users WHERE status = 'active'").fetchone()[0],
                "books": connection.execute("SELECT COUNT(*) FROM books").fetchone()[0],
                "active_books": connection.execute("SELECT COUNT(*) FROM books WHERE deleted_at IS NULL").fetchone()[0],
                "chapters": connection.execute("SELECT COUNT(*) FROM chapters").fetchone()[0],
                "active_chapters": connection.execute("SELECT COUNT(*) FROM chapters WHERE deleted_at IS NULL").fetchone()[0],
                "bookshelf_items": connection.execute("SELECT COUNT(*) FROM bookshelf_items").fetchone()[0],
                "active_tokens": connection.execute("SELECT COUNT(*) FROM auth_tokens WHERE revoked_at IS NULL AND expires_at > datetime('now')").fetchone()[0],
                "trusted_devices": connection.execute("SELECT COUNT(*) FROM trusted_devices WHERE trusted_until > datetime('now')").fetchone()[0],
                "book_fulltexts": connection.execute("SELECT COUNT(*) FROM book_fulltexts").fetchone()[0],
                "book_fulltext_chars": connection.execute("SELECT COALESCE(SUM(char_count), 0) FROM book_fulltexts").fetchone()[0],
                "online_seconds": connection.execute(f"SELECT COALESCE(SUM({_online_seconds_expr()}), 0) FROM {_validate_table('user_online_sessions')}").fetchone()[0],
                "analysis_runs": connection.execute("SELECT COUNT(*) FROM user_analysis_runs").fetchone()[0],
                "analysis_input_chars": connection.execute("SELECT COALESCE(SUM(input_chars), 0) FROM user_analysis_runs").fetchone()[0],
                "ai_prompt_tokens": connection.execute("SELECT COALESCE(SUM(prompt_tokens), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_completion_tokens": connection.execute("SELECT COALESCE(SUM(completion_tokens), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_total_tokens": connection.execute("SELECT COALESCE(SUM(total_tokens), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_input_chars": connection.execute("SELECT COALESCE(SUM(input_chars), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_output_chars": connection.execute("SELECT COALESCE(SUM(output_chars), 0) FROM user_ai_usage_events").fetchone()[0],
            }
            counts["total_input_chars"] = int(counts["analysis_input_chars"] or 0) + int(counts["ai_input_chars"] or 0)
            chapter_statuses = [
                dict(row)
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM chapters GROUP BY status ORDER BY count DESC"
                ).fetchall()
            ]
            recent_audits = [
                dict(row)
                for row in connection.execute(
                    """
                SELECT l.*, COALESCE(au.username, u.username, '') AS admin_username
                FROM admin_audit_logs AS l
                LEFT JOIN admin_users AS au ON au.id = l.admin_user_id
                LEFT JOIN users AS u ON u.id = l.admin_user_id
                ORDER BY l.created_at DESC, l.id DESC
                LIMIT 10
                """
                ).fetchall()
            ]
            connection.commit()
        return {"counts": counts, "chapter_statuses": chapter_statuses, "recent_audits": recent_audits}

    def admin_user_stats(self, granularity: str = "monthly", year: int | None = None, month: str | None = None) -> dict[str, Any]:
        """用户统计：数据起始2026-06-01，支持 monthly/yearly/daily + 年份/月份筛选"""
        data_start = "2026-06-01 00:00:00"
        with _connect(self.db_path) as connection:
            now = connection.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
            month_start = now[:8] + "01 00:00:00"
            three_months_ago = connection.execute(
                "SELECT datetime('now', 'localtime', '-3 months', 'start of month')"
            ).fetchone()[0]

            # 所有计数从2026-06-01起算
            total_users = connection.execute(
                "SELECT COUNT(*) FROM users WHERE created_at >= ?", (data_start,)
            ).fetchone()[0]
            new_this_month = connection.execute(
                "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at >= ?", (data_start, month_start)
            ).fetchone()[0]
            dormant_users = connection.execute(
                "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at >= ?",
                (three_months_ago, data_start)
            ).fetchone()[0]
            active_this_month = connection.execute(
                "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND created_at >= ?",
                (month_start, data_start)
            ).fetchone()[0]

            trends: dict[str, list[dict[str, Any]]] = {"new_users": [], "dormant_users": [], "active_users": []}

            if granularity == "monthly" and month is not None:
                # 指定月份的按天明细 (1-30/31)
                year_part, mon_part = month.split("-")
                y, m = int(year_part), int(mon_part)
                import calendar
                days_in_month = calendar.monthrange(y, m)[1]
                for d in range(1, days_in_month + 1):
                    day_label = f"{m:02d}-{d:02d}"
                    day_begin = f"{y}-{m:02d}-{d:02d} 00:00:00"
                    day_end = f"{y}-{m:02d}-{d + 1:02d} 00:00:00" if d < days_in_month else f"{y}-{m + 1:02d}-01 00:00:00" if m < 12 else f"{y + 1}-01-01 00:00:00"
                    dormant_before = connection.execute(
                        "SELECT datetime(?, '-3 months')", (day_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (day_begin, day_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before, day_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (day_begin, day_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": day_label, "count": new_count})
                    trends["dormant_users"].append({"month": day_label, "count": dormant_count})
                    trends["active_users"].append({"month": day_label, "count": active_count})
            elif granularity == "yearly" and year is not None:
                # 指定年份的1-12月月度明细
                for m_ in range(1, 13):
                    month_label = f"{year}-{m_:02d}"
                    month_begin = f"{year}-{m_:02d}-01 00:00:00"
                    month_end = f"{year}-{m_ + 1:02d}-01 00:00:00" if m_ < 12 else f"{year + 1}-01-01 00:00:00"
                    dormant_before_val = connection.execute(
                        "SELECT datetime(?, '-3 months')", (month_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before_val, month_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": month_label, "count": new_count})
                    trends["dormant_users"].append({"month": month_label, "count": dormant_count})
                    trends["active_users"].append({"month": month_label, "count": active_count})
            elif granularity == "yearly":
                # 近5年（从2026起）
                current_year = int(now[:4])
                for y_ in range(2026, current_year + 1):
                    year_label = str(y_)
                    year_begin = f"{year_label}-01-01 00:00:00"
                    year_end = f"{y_ + 1}-01-01 00:00:00"
                    dormant_before_val = connection.execute(
                        "SELECT datetime(?, '-3 months')", (year_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (year_begin, year_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before_val, year_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (year_begin, year_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": year_label, "count": new_count})
                    trends["dormant_users"].append({"month": year_label, "count": dormant_count})
                    trends["active_users"].append({"month": year_label, "count": active_count})
            else:
                # monthly: 从2026-06起的所有月份
                current_year = int(now[:4])
                current_mon = int(now[5:7])
                start_y, start_m = 2026, 6
                months_list: list[tuple[int, int]] = []
                for y_ in range(start_y, current_year + 1):
                    m_start = start_m if y_ == start_y else 1
                    m_end = current_mon if y_ == current_year else 12
                    for m_ in range(m_start, m_end + 1):
                        months_list.append((y_, m_))
                for (y_, m_) in months_list:
                    month_label = f"{y_}-{m_:02d}"
                    month_begin = f"{y_}-{m_:02d}-01 00:00:00"
                    month_end = f"{y_}-{m_ + 1:02d}-01 00:00:00" if m_ < 12 else f"{y_ + 1}-01-01 00:00:00"
                    dormant_before_val = connection.execute(
                        "SELECT datetime(?, '-3 months')", (month_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before_val, month_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": month_label, "count": new_count})
                    trends["dormant_users"].append({"month": month_label, "count": dormant_count})
                    trends["active_users"].append({"month": month_label, "count": active_count})

        result: dict[str, Any] = {
            "total_users": total_users,
            "new_this_month": new_this_month,
            "dormant_users": dormant_users,
            "active_this_month": active_this_month,
            "trends": trends,
            "granularity": granularity,
        }
        if year is not None:
            result["year"] = year
        if month is not None:
            result["month"] = month
        return result
