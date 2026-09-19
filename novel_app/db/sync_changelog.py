"""离线变更追踪 Mixin —— hybrid-database-architecture spec Task 6 实现。

设计要点：
- 所有 log_change 调用都通过 _safe_log_change 包裹，失败时静默不影响主业务写入
- 在 Database 各 mixin 的关键写操作中注入 log_change（参见 library.py / characters.py / analysis.py）
- 表结构在 schema.py 的 _apply_sync_changelog_migration 中创建，幂等
- sync_changelog 自身的写入不记录到 changelog（避免无限递归）
- 通过 _is_sync_changelog_ready 检测表是否已就绪，避免在迁移过程中触发写入
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any


class SyncChangelogMixin:
    """提供 sync_changelog 表的读写 API。

    Mixin 假定宿主类具有：
    - self.connection: ThreadSafeConnection
    - self._connection_lock: RLock
    """

    # 在迁移过程中 / 表未就绪时跳过 log_change
    _sync_changelog_disabled: bool = False
    _sync_changelog_ready_cache: bool | None = None
    _sync_changelog_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _is_sync_changelog_ready(self) -> bool:
        """检测 sync_changelog 表是否已创建。

        结果缓存到实例属性，避免每次写入都查询 sqlite_master。
        失败时返回 False，调用方据此决定是否调用 log_change。
        """
        if self._sync_changelog_disabled:
            return False
        if self._sync_changelog_ready_cache is not None:
            return self._sync_changelog_ready_cache
        try:
            row = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_changelog' LIMIT 1"
            ).fetchone()
            ready = row is not None
        except sqlite3.Error:
            ready = False
        self._sync_changelog_ready_cache = ready
        return ready

    def _safe_log_change(
        self,
        table_name: str,
        row_id: Any,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """安全记录变更。失败时静默，不影响主业务写入。

        - table_name: 业务表名（如 'books', 'chapters', 'characters'）
        - row_id: 行主键（int/str）；多列主键传 JSON 字符串
        - operation: 'insert' | 'update' | 'delete'
        - payload: 行快照（可选，用于 delete 后云端删除 / insert 后云端重建）
        """
        if not self._is_sync_changelog_ready():
            return
        if operation not in ("insert", "update", "delete"):
            return
        try:
            import json as _json
            self.connection.execute(
                """
                INSERT INTO sync_changelog (table_name, row_id, operation, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(table_name),
                    str(row_id) if row_id is not None else "",
                    operation,
                    _json.dumps(payload, ensure_ascii=False) if payload else "",
                ),
            )
            # 若处于显式 transaction() 内则不 commit，随外层业务写入一起提交/回滚，
            # 保持一致性；事务外（绝大多数调用方都是先 commit 业务数据再调
            # log_change）必须自行提交，否则 changelog 写入会留下未决事务——
            # 线程本地连接下会占住写锁阻塞其他线程；旧共享连接架构下则会被
            # 任意线程的下次 commit "顺手"提交，造成跨线程事务污染。
            if not self.connection._commit_suppressed:
                self.connection.commit()
        except sqlite3.Error:
            # 静默失败：changelog 故障不应影响业务流程
            return

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def log_change(
        self,
        table_name: str,
        row_id: Any,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """记录一条变更到 sync_changelog。供各 mixin 的写操作调用。"""
        self._safe_log_change(table_name, row_id, operation, payload)

    def get_unsynced_changes(self, limit: int = 100) -> list[sqlite3.Row]:
        """获取未同步的变更记录，按时间升序返回。"""
        if not self._is_sync_changelog_ready():
            return []
        cursor = self.connection.execute(
            """
            SELECT id, table_name, row_id, operation, timestamp, payload_json
            FROM sync_changelog
            WHERE synced = 0
            ORDER BY id ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        return list(cursor.fetchall())

    def mark_changes_synced(self, change_ids: list[int]) -> int:
        """标记指定 ID 的变更为已同步。返回更新的行数。"""
        if not change_ids or not self._is_sync_changelog_ready():
            return 0
        # 用 IN 子句批量更新
        placeholders = ",".join("?" * len(change_ids))
        cursor = self.connection.execute(
            f"""
            UPDATE sync_changelog
            SET synced = 1
            WHERE id IN ({placeholders})
            """,
            [int(cid) for cid in change_ids],
        )
        self.connection.commit()
        return cursor.rowcount or 0

    def count_unsynced_changes(self) -> int:
        """统计当前未同步的变更数量。"""
        if not self._is_sync_changelog_ready():
            return 0
        row = self.connection.execute(
            "SELECT COUNT(*) AS cnt FROM sync_changelog WHERE synced = 0"
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def clear_synced_changes(self, keep_recent: int = 1000) -> int:
        """清理已同步的旧变更记录，避免表无限增长。

        - keep_recent: 保留最近 N 条已同步记录（用于审计/回溯）
        返回删除的行数。
        """
        if not self._is_sync_changelog_ready():
            return 0
        cursor = self.connection.execute(
            """
            DELETE FROM sync_changelog
            WHERE synced = 1
              AND id NOT IN (
                  SELECT id FROM sync_changelog
                  WHERE synced = 1
                  ORDER BY id DESC
                  LIMIT ?
              )
            """,
            (max(0, int(keep_recent)),),
        )
        self.connection.commit()
        return cursor.rowcount or 0

    def get_last_sync_timestamp(self) -> str | None:
        """获取最后一条已同步记录的时间戳。无记录时返回 None。"""
        if not self._is_sync_changelog_ready():
            return None
        row = self.connection.execute(
            """
            SELECT timestamp FROM sync_changelog
            WHERE synced = 1
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return str(row["timestamp"]) if row else None

    def reset_sync_state(self) -> int:
        """将所有已同步记录重置为未同步（用于重试同步）。

        返回重置的行数。慎用——这会导致已同步的变更被重新推送。
        """
        if not self._is_sync_changelog_ready():
            return 0
        cursor = self.connection.execute(
            "UPDATE sync_changelog SET synced = 0 WHERE synced = 1"
        )
        self.connection.commit()
        return cursor.rowcount or 0
