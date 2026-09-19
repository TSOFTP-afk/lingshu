"""增量同步引擎 — hybrid-database-architecture spec Task 7 实现。

基于 sync_changelog + updated_at 的双向增量同步：
- push: 读取本地 sync_changelog 未同步记录，按行推送到云端 API
- pull: 从云端 API 拉取 updated_at > last_sync_ts 的行，合并到本地
- 冲突解决: Last-Write-Wins (updated_at 较大者胜出)
- 自动同步: 每 sync_interval 秒执行 sync_cycle()，仅联网时运行

设计要点：
- SyncEngine 是独立类，持有 Database 引用，不是 Database mixin
- pull 时直接用 SQL 写入本地（绕过 library.py 方法），不触发 log_change，避免同步循环
- push 时从本地表读完整行数据（payload_json 可能不完整）
- 网络错误标记为离线，不中断本地操作
- 云端 API URL 可配置，认证用 Bearer token
- sync_meta 表（key-value）持久化 last_pull_ts 等同步状态
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from novel_app.database import Database

logger = logging.getLogger(__name__)

# 可同步表白名单（防 SQL 注入，复用 book_sync.py 的 _VALID_LOCAL_TABLES 并补充 books）
SYNCABLE_TABLES = frozenset({
    "books",
    "volumes",
    "chapters",
    "characters",
    "character_relationships",
    "world_entries",
    "chapter_events",
    "chapter_tags",
    "review_findings",
    "review_runs",
    "analysis_cards",
    "analysis_runs",
    "chapter_ai_spans",
    "chapter_snapshots",
})

_SAFE_COLUMN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_table(table_name: str) -> str:
    """校验表名是否在可同步白名单中，防止 SQL 注入。"""
    if table_name not in SYNCABLE_TABLES:
        raise ValueError(f"Table not syncable: {table_name}")
    return table_name


def _validate_column(name: str) -> str:
    """校验列名是否安全（仅允许字母/数字/下划线）。"""
    if not _SAFE_COLUMN.match(name):
        raise ValueError(f"Invalid column name: {name}")
    return name


def _parse_timestamp(ts: str | None) -> datetime | None:
    """解析时间戳字符串为 datetime，兼容 ISO 8601 与 SQLite 格式。

    SQLite 的 CURRENT_TIMESTAMP 产出 naive datetime（如 '2026-07-02 14:00:00'），
    云端 ISO 8601 带 Z 或时区偏移。统一转为 UTC aware datetime 避免比较报错。
    """
    if not ts:
        return None
    try:
        ts = ts.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def _serialize_value(v: Any) -> Any:
    """把 sqlite3.Row 的值转为 JSON 可序列化类型。"""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


@dataclass
class SyncResult:
    """单次同步周期的结果。"""
    pushed: int = 0
    pulled: int = 0
    skipped: int = 0  # 冲突跳过（本地胜出）
    conflicts: int = 0  # 冲突且云端胜出
    errors: list[str] = field(default_factory=list)
    online: bool = True

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def merge(self, other: SyncResult) -> None:
        self.pushed += other.pushed
        self.pulled += other.pulled
        self.skipped += other.skipped
        self.conflicts += other.conflicts
        self.errors.extend(other.errors)
        self.online = self.online and other.online


class SyncEngine:
    """增量同步引擎。

    使用方式::

        engine = SyncEngine(database, "https://api.example.com", auth_token="xxx")
        engine.start_auto_sync()  # 启动自动同步（每 5 秒）
        # ...
        engine.stop_auto_sync()

    或手动触发::

        result = engine.sync_cycle()
        print(f"pushed={result.pushed}, pulled={result.pulled}")
    """

    def __init__(
        self,
        database: Database,
        cloud_api_url: str,
        *,
        auth_token: str | None = None,
        sync_interval: float = 5.0,
        http_client: httpx.Client | None = None,
        push_batch_size: int = 100,
    ) -> None:
        self.database = database
        self.cloud_api_url = cloud_api_url.rstrip("/")
        self.auth_token = auth_token
        self.sync_interval = max(1.0, float(sync_interval))
        self.push_batch_size = max(1, int(push_batch_size))
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._timer: threading.Timer | None = None
        self._timer_lock = threading.RLock()  # RLock: start_auto_sync 持锁时调用 _schedule_next_cycle 需可重入
        self._running = False
        self._sync_lock = threading.Lock()
        self._updated_at_cache: dict[str, bool] = {}
        self._ensure_sync_meta_table()

    # ------------------------------------------------------------------
    # sync_meta 表管理（持久化同步状态）
    # ------------------------------------------------------------------

    def _ensure_sync_meta_table(self) -> None:
        """创建 sync_meta 表（key-value），用于持久化 last_pull_ts 等状态。"""
        try:
            self.database.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.database.connection.commit()
        except sqlite3.Error:
            logger.warning("Failed to create sync_meta table")

    def _get_last_pull_ts(self) -> str:
        row = self.database.connection.execute(
            "SELECT value FROM sync_meta WHERE key = 'last_pull_ts'"
        ).fetchone()
        return str(row["value"]) if row else ""

    def _set_last_pull_ts(self, ts: str) -> None:
        self.database.connection.execute(
            """
            INSERT INTO sync_meta (key, value) VALUES ('last_pull_ts', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (ts,),
        )
        self.database.connection.commit()

    # ------------------------------------------------------------------
    # HTTP 客户端
    # ------------------------------------------------------------------

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is None:
            headers = {"Content-Type": "application/json"}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"
            self._http_client = httpx.Client(
                base_url=self.cloud_api_url,
                headers=headers,
                timeout=10.0,
            )
        return self._http_client

    def close(self) -> None:
        """释放资源（HTTP 客户端、定时器）。"""
        self.stop_auto_sync()
        if self._http_client and self._owns_http_client:
            self._http_client.close()
            self._http_client = None

    # ------------------------------------------------------------------
    # push: 本地变更 → 云端  (SubTask 7.2)
    # ------------------------------------------------------------------

    def push_incremental(self) -> SyncResult:
        """读取 sync_changelog 未同步记录，按行推送到云端 API。

        - 分批读取（push_batch_size 条/批）
        - 对每条 insert/update 从本地表读完整行数据
        - 对 delete 用 payload_json（行已不存在）
        - POST /api/sync/push，成功后标记 synced
        - 网络错误时标记 offline 并中断，下次重试
        """
        result = SyncResult()
        client = self._get_http_client()

        while True:
            changes = self.database.get_unsynced_changes(limit=self.push_batch_size)
            if not changes:
                break

            push_payload = {
                "changes": [self._build_push_change(c) for c in changes]
            }

            try:
                resp = client.post("/api/sync/push", json=push_payload)
                resp.raise_for_status()
                resp_data = resp.json()
            except httpx.ConnectError as exc:
                result.online = False
                result.errors.append(f"push: connect error: {exc}")
                break
            except httpx.TimeoutException as exc:
                result.online = False
                result.errors.append(f"push: timeout: {exc}")
                break
            except httpx.HTTPStatusError as exc:
                result.errors.append(
                    f"push: HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                )
                break
            except (ValueError, KeyError) as exc:
                result.errors.append(f"push: parse error: {exc}")
                break

            accepted = int(resp_data.get("accepted", 0))
            result.pushed += accepted

            # 标记已同步（HTTP 2xx 视为全部成功，云端应保证事务性）
            change_ids = [int(c["id"]) for c in changes]
            self.database.mark_changes_synced(change_ids)

            if len(changes) < self.push_batch_size:
                break

        return result

    def _build_push_change(self, changelog_row: sqlite3.Row) -> dict[str, Any]:
        """从 sync_changelog 记录构建 push 请求的单条变更。

        - delete: 用 payload_json（行已不存在）
        - insert/update: 从本地表读完整行；若读不到（已被删除），降级为 delete
        """
        table_name = str(changelog_row["table_name"])
        row_id = str(changelog_row["row_id"])
        operation = str(changelog_row["operation"])
        timestamp = str(changelog_row["timestamp"])

        change: dict[str, Any] = {
            "table_name": table_name,
            "row_id": row_id,
            "operation": operation,
            "timestamp": timestamp,
        }

        if operation == "delete":
            change["data"] = self._parse_payload(changelog_row["payload_json"])
        else:
            full_row = self._read_full_row(table_name, row_id)
            if full_row is not None:
                change["data"] = full_row
            else:
                # 行已不存在（可能被后续删除），降级为 delete
                change["data"] = self._parse_payload(changelog_row["payload_json"])
                change["operation"] = "delete"

        return change

    def _read_full_row(self, table_name: str, row_id: str) -> dict[str, Any] | None:
        """从本地表读取完整行数据。"""
        if table_name not in SYNCABLE_TABLES:
            return None
        try:
            rid: int | str = int(row_id)
        except ValueError:
            rid = row_id
        try:
            row = self.database.connection.execute(
                f"SELECT * FROM {_validate_table(table_name)} WHERE id = ?",
                (rid,),
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        return {k: _serialize_value(row[k]) for k in row.keys()}  # noqa: SIM118 — row 是 sqlite3.Row，`in row`/直接迭代产出的是值而非键，必须用 .keys()

    @staticmethod
    def _parse_payload(payload_json: str | None) -> dict[str, Any]:
        if not payload_json:
            return {}
        try:
            data = json.loads(payload_json)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    # ------------------------------------------------------------------
    # pull: 云端变更 → 本地  (SubTask 7.3 + 7.4)
    # ------------------------------------------------------------------

    def pull_incremental(self) -> SyncResult:
        """从云端 API 拉取 updated_at > last_sync_ts 的行，合并到本地。

        - GET /api/sync/pull?since={last_pull_ts}
        - 对每条变更做冲突检测（Last-Write-Wins）
        - 直接用 SQL 写入本地，绕过 library.py 方法，不触发 log_change
        """
        result = SyncResult()
        client = self._get_http_client()
        since = self._get_last_pull_ts()

        try:
            params = {"since": since} if since else None
            resp = client.get("/api/sync/pull", params=params)
            resp.raise_for_status()
            resp_data = resp.json()
        except httpx.ConnectError as exc:
            result.online = False
            result.errors.append(f"pull: connect error: {exc}")
            return result
        except httpx.TimeoutException as exc:
            result.online = False
            result.errors.append(f"pull: timeout: {exc}")
            return result
        except httpx.HTTPStatusError as exc:
            result.errors.append(
                f"pull: HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            )
            return result
        except (ValueError, KeyError) as exc:
            result.errors.append(f"pull: parse error: {exc}")
            return result

        changes = resp_data.get("changes", [])
        server_time = str(resp_data.get("server_time", ""))

        for change in changes:
            try:
                applied = self._apply_remote_change(change)
                if applied:
                    result.pulled += 1
                else:
                    result.skipped += 1
            except Exception as exc:
                result.errors.append(f"pull: apply error: {exc}")

        # 更新 last_pull_ts（用云端返回的 server_time 避免时钟漂移）
        if server_time:
            self._set_last_pull_ts(server_time)

        return result

    def _apply_remote_change(self, change: dict[str, Any]) -> bool:
        """应用云端变更到本地。

        返回 True=已应用，False=冲突跳过（本地胜出）。
        冲突检测：若本地 updated_at >= 云端 updated_at，本地胜出，跳过。
        """
        table_name = str(change.get("table_name", ""))
        row_id = str(change.get("row_id", ""))
        operation = str(change.get("operation", ""))
        data = change.get("data") or {}
        remote_updated_at = change.get("updated_at")

        _validate_table(table_name)

        if operation == "delete":
            self._delete_local_row(table_name, row_id)
            return True

        # insert/update: 冲突检测（Last-Write-Wins）
        if remote_updated_at and self._table_has_updated_at(table_name):
            local_ts = self._get_local_updated_at(table_name, row_id)
            if local_ts:
                local_dt = _parse_timestamp(local_ts)
                remote_dt = _parse_timestamp(str(remote_updated_at))
                if local_dt and remote_dt and local_dt >= remote_dt:
                    return False  # 本地胜出，跳过

        self._upsert_local_row(table_name, data)
        return True

    def _table_has_updated_at(self, table_name: str) -> bool:
        """检测表是否有 updated_at 列（结果缓存）。"""
        if table_name not in self._updated_at_cache:
            try:
                cols = self.database.connection.execute(
                    f"PRAGMA table_info({_validate_table(table_name)})"
                ).fetchall()
                self._updated_at_cache[table_name] = any(
                    c["name"] == "updated_at" for c in cols
                )
            except sqlite3.Error:
                self._updated_at_cache[table_name] = False
        return self._updated_at_cache[table_name]

    def _get_local_updated_at(self, table_name: str, row_id: str) -> str | None:
        """查询本地行的 updated_at。"""
        try:
            rid: int | str = int(row_id)
        except ValueError:
            rid = row_id
        try:
            row = self.database.connection.execute(
                f"SELECT updated_at FROM {_validate_table(table_name)} WHERE id = ?",
                (rid,),
            ).fetchone()
            return str(row["updated_at"]) if row and row["updated_at"] else None
        except sqlite3.Error:
            return None

    def _upsert_local_row(self, table_name: str, data: dict[str, Any]) -> None:
        """INSERT OR REPLACE 一行数据（绕过 mixin，不触发 log_change）。"""
        table = _validate_table(table_name)
        columns = [c for c in data if _validate_column(c)]
        if not columns:
            return
        values = [data[c] for c in columns]
        col_list = ", ".join(columns)
        placeholders = ", ".join("?" * len(columns))
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
        self.database.connection.execute(sql, values)
        self.database.connection.commit()

    def _delete_local_row(self, table_name: str, row_id: str) -> None:
        """删除本地行（绕过 mixin，不触发 log_change）。"""
        table = _validate_table(table_name)
        try:
            rid: int | str = int(row_id)
        except ValueError:
            rid = row_id
        self.database.connection.execute(
            f"DELETE FROM {table} WHERE id = ?",
            (rid,),
        )
        self.database.connection.commit()

    # ------------------------------------------------------------------
    # sync_cycle + 自动同步  (SubTask 7.5 + 7.6)
    # ------------------------------------------------------------------

    def sync_cycle(self) -> SyncResult:
        """单次 push + pull 循环。

        - 先 push 本地变更到云端
        - 若 push 期间联网正常，再 pull 云端变更到本地
        - 用 _sync_lock 防止并发同步
        """
        if not self._sync_lock.acquire(blocking=False):
            # 已有同步在运行，跳过本次
            return SyncResult(online=False)
        try:
            result = SyncResult()
            push_result = self.push_incremental()
            result.merge(push_result)
            # 只有 push 联网成功时才 pull
            if push_result.online:
                pull_result = self.pull_incremental()
                result.merge(pull_result)
            else:
                result.online = False
            return result
        finally:
            self._sync_lock.release()

    def start_auto_sync(self) -> None:
        """启动自动同步定时器（每 sync_interval 秒调用 sync_cycle）。

        定时器在 daemon 线程中运行，主进程退出时自动结束。
        重复调用安全（已启动时返回）。
        """
        with self._timer_lock:
            if self._running:
                return
            self._running = True
            self._schedule_next_cycle()
            logger.info("Auto sync started (interval=%.1fs)", self.sync_interval)

    def stop_auto_sync(self) -> None:
        """停止自动同步定时器。重复调用安全。"""
        with self._timer_lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            logger.info("Auto sync stopped")

    def _schedule_next_cycle(self) -> None:
        with self._timer_lock:
            if not self._running:
                return
            self._timer = threading.Timer(self.sync_interval, self._auto_sync_tick)
            self._timer.daemon = True
            self._timer.start()

    def _auto_sync_tick(self) -> None:
        try:
            result = self.sync_cycle()
            if result.has_errors:
                logger.warning(
                    "Auto sync: pushed=%d, pulled=%d, errors=%d",
                    result.pushed, result.pulled, len(result.errors),
                )
            elif result.pushed or result.pulled:
                logger.info(
                    "Auto sync: pushed=%d, pulled=%d", result.pushed, result.pulled
                )
        except Exception:
            logger.exception("Auto sync cycle failed")
        finally:
            self._schedule_next_cycle()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """返回当前同步状态快照。"""
        return {
            "running": self._running,
            "online": True,  # 实际在线状态由上次 sync_cycle 结果决定
            "pending_push": self.database.count_unsynced_changes(),
            "last_pull_ts": self._get_last_pull_ts(),
            "cloud_api_url": self.cloud_api_url,
            "sync_interval": self.sync_interval,
        }
