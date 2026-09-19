"""设备信任仓储 — 从 store.py 按域搬移（SQL 与行为不变）。

承接：trusted_devices 表的查询/写入/列举。
连接与事务模式照搬原 store.py：``with _connect(self.db_path) as connection`` + 显式 ``connection.commit()``。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import _connect


class DeviceRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def check_device_trusted(self, user_id: int, fingerprint: str, ip_address: str) -> dict[str, Any]:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT id, trusted_until, ip_address
                FROM trusted_devices
                WHERE user_id = ? AND fingerprint = ? AND trusted_until > datetime('now')
                """,
                (user_id, fingerprint),
            ).fetchone()
        if row:
            return {
                "trusted": True,
                "requires_verification": False,
                "trusted_until": str(row["trusted_until"]),
                "last_ip": str(row["ip_address"] or ""),
            }
        return {
            "trusted": False,
            "requires_verification": True,
            "reason": "new_or_expired_device",
            "current_ip": ip_address,
        }

    def trust_device(self, user_id: int, fingerprint: str, device_info: str, ip_address: str) -> None:
        with _connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO trusted_devices (
                    user_id, fingerprint, device_info, ip_address, trusted_until
                )
                VALUES (?, ?, ?, ?, datetime('now', '+30 days'))
                ON CONFLICT(user_id, fingerprint) DO UPDATE SET
                    device_info = excluded.device_info,
                    ip_address = excluded.ip_address,
                    trusted_until = excluded.trusted_until,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, fingerprint, device_info, ip_address),
            )
            connection.commit()

    def get_trusted_devices(self, user_id: int) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT fingerprint, device_info, ip_address, trusted_until, updated_at
                FROM trusted_devices
                WHERE user_id = ? AND trusted_until > datetime('now')
                ORDER BY updated_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]
