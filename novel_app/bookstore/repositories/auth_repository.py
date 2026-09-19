"""认证/会话仓储 — 从 store.py 按域搬移（SQL 与行为不变）。

承接：登录、token 签发与校验、登出、在线会话结转。
连接与事务模式照搬原 store.py：``with _connect(self.db_path) as connection`` + 显式 ``connection.commit()``。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..models import _connect
from ..security import (
    _generate_token,
    _seconds_between_sql,
    _token_hash,
    _verify_login_password,
)


def _record_login_session(
    connection: sqlite3.Connection,
    *,
    user_id: int,
    token: str,
    expires_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO user_online_sessions (user_id, token_hash, login_at, expires_at, status)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?, 'active')
        """,
        (int(user_id), _token_hash(token), expires_at),
    )


def _settle_online_session(
    connection: sqlite3.Connection,
    *,
    token_hash: str,
    status: str,
) -> None:
    connection.execute(
        f"""
        UPDATE user_online_sessions
        SET logout_at = COALESCE(logout_at, CURRENT_TIMESTAMP),
            estimated_online_seconds = CASE
                WHEN estimated_online_seconds > 0 THEN estimated_online_seconds
                ELSE {_seconds_between_sql("CURRENT_TIMESTAMP")}
            END,
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE token_hash = ? AND status = 'active'
        """,
        (status, token_hash),
    )


def _settle_expired_sessions(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        UPDATE user_online_sessions
        SET logout_at = COALESCE(logout_at, expires_at),
            estimated_online_seconds = CASE
                WHEN estimated_online_seconds > 0 THEN estimated_online_seconds
                ELSE {_seconds_between_sql("expires_at")}
            END,
            status = 'expired',
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'active' AND expires_at <= CURRENT_TIMESTAMP
        """
    )


class AuthRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def logout_token(self, token: str) -> bool:
        token_hash = _token_hash(token)
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE auth_tokens
                SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (token_hash,),
            )
            _settle_online_session(connection, token_hash=token_hash, status="logged_out")
            connection.commit()
            return cursor.rowcount > 0

    def login_user(self, username: str, password: str) -> str | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT id, password_hash, status FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if not row or not _verify_login_password(password, row["password_hash"]):
                return None
            if str(row["status"] or "active") != "active":
                return None
            token = _generate_token()
            token_hash = _token_hash(token)
            # 安全：只存哈希，明文 token 仅返回给客户端，不落库（防拖库泄露会话）
            connection.execute(
                """
                INSERT INTO auth_tokens (token, token_hash, user_id, created_at, expires_at)
                VALUES (NULL, ?, ?, CURRENT_TIMESTAMP, datetime('now', '+7 days'))
                """,
                (token_hash, row["id"]),
            )
            token_row = connection.execute("SELECT expires_at FROM auth_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
            _record_login_session(
                connection,
                user_id=int(row["id"]),
                token=token,
                expires_at=str(token_row["expires_at"] if token_row else ""),
            )
            connection.commit()
            return token

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        token_hash = _token_hash(token)
        with _connect(self.db_path) as connection:
            _settle_expired_sessions(connection)
            row = connection.execute(
                """
                SELECT u.id, u.username, u.is_author, u.is_admin, u.status,
                       u.disabled_at, u.updated_at, u.bind_reader_id,
                       b.username as bind_reader_name
                FROM auth_tokens t
                JOIN users u ON u.id = t.user_id
                LEFT JOIN users b ON b.id = u.bind_reader_id
                WHERE t.token_hash = ?
                  AND t.revoked_at IS NULL
                  AND t.expires_at > datetime('now')
                  AND u.status = 'active'
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                connection.commit()
                return None
            connection.commit()
            return dict(row)

    def bind_reader(self, author_id: int, reader_id: int) -> None:
        with _connect(self.db_path) as connection:
            connection.execute("UPDATE users SET bind_reader_id = ? WHERE id = ?", (reader_id, author_id))
            connection.commit()
