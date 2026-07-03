"""
管理员独立认证路由。

云端管理后台使用 admin_users / admin_auth_tokens，与普通用户登录完全分离。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from lingshu_api.dependencies import get_store
from lingshu_api.schemas.admin_auth import AdminLoginPayload
from novel_app.bookstore import BookstoreStore, _bearer_token


router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


def _admin_rate_limit_key(request: Request) -> str:
    return f"{get_remote_address(request)}:{id(request.app)}"


limiter = Limiter(key_func=_admin_rate_limit_key)

_ADMIN_TOKENS_TABLE = "admin_auth_tokens"
_ADMIN_KEYS_TABLE = "admin_keys"
_ADMIN_HMAC_WINDOW_MS = 5 * 60 * 1000

# Token 有效期（小时），可通过环境变量覆盖
_ADMIN_TOKEN_TTL_HOURS = int(os.environ.get("ADMIN_TOKEN_TTL_HOURS", "24"))


def _cleanup_expired_tokens(db_path: Path) -> int:
    """清理过期的管理员 Token，返回删除数量。"""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            f"DELETE FROM {_ADMIN_TOKENS_TABLE} WHERE expires_at <= datetime('now')"
        )
        conn.commit()
        return cursor.rowcount


def cleanup_on_startup(db_path: Path) -> None:
    """应用启动时清理过期 Token。"""
    try:
        count = _cleanup_expired_tokens(db_path)
        if count > 0:
            logging.getLogger("lingshu.admin_auth").info("清理了 %d 个过期管理员 Token", count)
    except Exception:
        pass  # 启动时不应因清理失败而中断


def _admin_token_hash(token: str) -> str:
    """Hash an admin token for secure storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_db_path(store: BookstoreStore) -> Path:
    return store.db_path


def _get_encryption_key(db_path: Path) -> bytes:
    """获取或生成 HMAC 密钥的 AES-256 加密密钥。
    优先从环境变量 ADMIN_HMAC_ENCRYPTION_KEY 读取（base64 编码的 32 字节密钥），
    否则从数据库同目录的 .admin_encryption_key 文件读取，若不存在则自动生成。"""
    env_key = os.environ.get("ADMIN_HMAC_ENCRYPTION_KEY")
    if env_key:
        return base64.b64decode(env_key)
    p = Path(db_path) if not isinstance(db_path, Path) else db_path
    key_file = p.parent / ".admin_encryption_key"
    if key_file.exists():
        return base64.b64decode(key_file.read_text().strip())
    key = AESGCM.generate_key(bit_length=256)
    key_file.write_text(base64.b64encode(key).decode())
    try:
        os.chmod(str(key_file), 0o600)
    except OSError:
        pass
    return key


def _encrypt_secret(plaintext: str, db_path: Path) -> str:
    """使用 AES-256-GCM 加密密钥。返回 aes256gcm:<iv>:<ciphertext>:<tag> 格式。"""
    key = _get_encryption_key(db_path)
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
    ciphertext = ciphertext_with_tag[:-16]
    tag = ciphertext_with_tag[-16:]
    return f"aes256gcm:{base64.b64encode(iv).decode()}:{base64.b64encode(ciphertext).decode()}:{base64.b64encode(tag).decode()}"


def _decrypt_secret(encrypted: str, db_path: Path) -> str:
    """解密密钥。如果值不以 aes256gcm: 开头，则视为明文（向后兼容）。"""
    if not encrypted.startswith("aes256gcm:"):
        return encrypted
    parts = encrypted.split(":")
    if len(parts) != 4:
        raise ValueError("Invalid encrypted secret format")
    _, iv_b64, ct_b64, tag_b64 = parts
    key = _get_encryption_key(db_path)
    aesgcm = AESGCM(key)
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ct_b64)
    tag = base64.b64decode(tag_b64)
    plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
    return plaintext.decode()


_ALLOWED_ADMIN_TABLES = frozenset({"admin_users", "admin_auth_tokens", "admin_keys", "admin_audit_logs"})


def _sql_identifier(value: str) -> str:
    text = str(value or "")
    if not text or text[0].isdigit() or not all(char.isalnum() or char == "_" for char in text):
        raise ValueError(f"Unsafe SQL identifier: {text!r}")
    return '"' + text.replace('"', '""') + '"'


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """Get column names for a whitelisted admin table."""
    if table_name not in _ALLOWED_ADMIN_TABLES:
        raise ValueError(f"Table '{table_name}' is not allowed for PRAGMA inspection")
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({_sql_identifier(table_name)})").fetchall()}


def _admin_audit_needs_rebuild(connection: sqlite3.Connection) -> bool:
    columns = _table_columns(connection, "admin_audit_logs")
    if not columns:
        return False
    expected = {"id", "admin_user_id", "action", "object_type", "object_id", "detail", "created_at"}
    if not expected.issubset(columns):
        return True
    foreign_keys = connection.execute(f"PRAGMA foreign_key_list({_sql_identifier('admin_audit_logs')})").fetchall()
    return any(str(row[2]) == "users" for row in foreign_keys)


def _column_expr(columns: set[str], *names: str, default: str = "''") -> str:
    for name in names:
        if name in columns:
            return name
    return default


def _ensure_admin_audit_table(connection: sqlite3.Connection) -> None:
    """Normalize admin audit storage so independent admins can write audit rows."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    if _admin_audit_needs_rebuild(connection):
        columns = _table_columns(connection, "admin_audit_logs")
        id_expr = _column_expr(columns, "id", default="NULL")
        admin_expr = _column_expr(columns, "admin_user_id", default="0")
        action_expr = _column_expr(columns, "action")
        object_type_expr = _column_expr(columns, "object_type", "target_type")
        object_id_expr = _column_expr(columns, "object_id", "target_id")
        detail_expr = _column_expr(columns, "detail", "detail_json", default="'{}'")
        created_expr = _column_expr(columns, "created_at", default="CURRENT_TIMESTAMP")
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ALTER TABLE admin_audit_logs RENAME TO admin_audit_logs_old")
        connection.execute(
            """
            CREATE TABLE admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            f"""
            INSERT INTO admin_audit_logs (id, admin_user_id, action, object_type, object_id, detail, created_at)
            SELECT {id_expr}, {admin_expr}, {action_expr}, {object_type_expr}, {object_id_expr}, {detail_expr}, {created_expr}
            FROM admin_audit_logs_old
            """
        )
        connection.execute("DROP TABLE admin_audit_logs_old")
        connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created
        ON admin_audit_logs(created_at DESC, id DESC)
        """
    )


def _ensure_admin_tables(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'operator',
                status TEXT NOT NULL DEFAULT 'active',
                last_login_at TEXT,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_ADMIN_TOKENS_TABLE} (
                token TEXT PRIMARY KEY,
                admin_user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_ADMIN_KEYS_TABLE} (
                key_id TEXT PRIMARY KEY,
                admin_user_id INTEGER NOT NULL,
                secret_encrypted TEXT NOT NULL,
                key_fingerprint TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                issued_at TEXT NOT NULL DEFAULT '',
                last_used_at TEXT,
                expires_at TEXT,
                FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            )
            """
        )
        _ensure_admin_audit_table(connection)
        connection.commit()
    # 惰性清理过期 Token
    try:
        _cleanup_expired_tokens(db_path)
    except Exception:
        pass


def _admin_keys_configured(db_path: Path) -> bool:
    _ensure_admin_tables(db_path)
    with sqlite3.connect(db_path) as connection:
        count = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM {_ADMIN_KEYS_TABLE}
            WHERE status = 'active'
              AND (expires_at IS NULL OR expires_at = '' OR expires_at > datetime('now'))
            """
        ).fetchone()[0]
    return int(count or 0) > 0


def _admin_hmac_message(timestamp: str, method: str, path: str) -> str:
    return f"{timestamp}\n{method.upper()}\n{path}"


def _verify_admin_hmac_signature(
    db_path: Path,
    *,
    key_id: str,
    timestamp: str,
    signature: str,
    method: str,
    path: str,
) -> dict[str, Any] | None:
    _ensure_admin_tables(db_path)
    if not key_id or not timestamp or not signature:
        return None
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return None
    if abs(time.time() * 1000 - ts) > _ADMIN_HMAC_WINDOW_MS:
        return None

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            f"""
            SELECT
                k.key_id,
                k.secret_encrypted,
                k.status AS key_status,
                k.expires_at,
                a.id,
                a.username,
                a.display_name,
                a.role,
                a.status AS admin_status,
                a.last_login_at
            FROM {_ADMIN_KEYS_TABLE} AS k
            JOIN admin_users AS a ON a.id = k.admin_user_id
            WHERE k.key_id = ?
            """,
            (key_id,),
        ).fetchone()
        if not row:
            return None
        if str(row["key_status"]) != "active" or str(row["admin_status"]) != "active":
            return None
        expires_at = str(row["expires_at"] or "")
        if expires_at:
            expires = connection.execute("SELECT ? > datetime('now')", (expires_at,)).fetchone()[0]
            if not int(expires or 0):
                return None
        # 解密密钥后再验证 HMAC 签名
        secret = _decrypt_secret(str(row["secret_encrypted"]), db_path)
        message = _admin_hmac_message(timestamp, method, path)
        expected = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        connection.execute(
            f"UPDATE {_ADMIN_KEYS_TABLE} SET last_used_at = ? WHERE key_id = ?",
            (now, key_id),
        )
        connection.commit()
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "status": row["admin_status"],
            "last_login_at": row["last_login_at"],
            "key_id": row["key_id"],
        }


def verify_admin_hmac_headers(db_path: Path, request: Request) -> None:
    if not _admin_keys_configured(db_path):
        raise HTTPException(status_code=503, detail="管理员密钥未配置，请先配置 HMAC 密钥")
    signed_path = str(request.scope.get("lingshu.original_path") or request.url.path)
    verified = _verify_admin_hmac_signature(
        db_path,
        key_id=request.headers.get("X-Client-KeyId", ""),
        timestamp=request.headers.get("X-Client-Ts", ""),
        signature=request.headers.get("X-Client-Sig", ""),
        method=request.method,
        path=signed_path,
    )
    if not verified:
        raise HTTPException(status_code=403, detail="管理密钥签名无效或已过期")


def _get_admin_by_token(db_path: Path, token: str) -> dict[str, Any] | None:
    _ensure_admin_tables(db_path)
    token_hash = _admin_token_hash(token)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            f"""
            SELECT a.id, a.username, a.display_name, a.role, a.status, a.last_login_at
            FROM {_ADMIN_TOKENS_TABLE} AS t
            JOIN admin_users AS a ON a.id = t.admin_user_id
            WHERE t.token = ?
              AND t.expires_at > datetime('now')
              AND a.status = 'active'
            """,
            (token_hash,),
        ).fetchone()
    return dict(row) if row else None


def require_admin_user(
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
) -> dict[str, Any]:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    db_path = _get_db_path(store)
    # 双因子验证：HMAC 签名 + Bearer Token
    verify_admin_hmac_headers(db_path, request)
    admin = _get_admin_by_token(db_path, token)
    if not admin:
        raise HTTPException(status_code=401, detail="管理员登录已过期或无效")
    return admin


@router.post("/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, payload: AdminLoginPayload, store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
    username = payload.username.strip()
    password = payload.password

    db_path = _get_db_path(store)
    _ensure_admin_tables(db_path)
    if not _admin_keys_configured(db_path):
        raise HTTPException(status_code=503, detail="管理员密钥未配置，请先配置 HMAC 密钥")
    key_info = _verify_admin_hmac_signature(
        db_path,
        key_id=payload.key_id,
        timestamp=payload.timestamp,
        signature=payload.hmac_signature,
        method=request.method,
        path=str(request.scope.get("lingshu.original_path") or request.url.path),
    )
    if not key_info:
        raise HTTPException(status_code=403, detail="密钥验证失败，请检查密钥文件是否有效")
    if str(key_info.get("username") or "") != username:
        raise HTTPException(status_code=403, detail="密钥与管理员账号不匹配")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT id, username, password_hash, display_name, role, status
            FROM admin_users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

    if not row or not bcrypt.checkpw(password.encode("utf-8"), str(row["password_hash"]).encode("utf-8")):
        raise HTTPException(status_code=401, detail="管理员用户名或密码错误")
    if str(row["status"]) != "active":
        raise HTTPException(status_code=403, detail="管理员账号已停用")

    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=_ADMIN_TOKEN_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            f"""
            INSERT INTO {_ADMIN_TOKENS_TABLE} (token, admin_user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (_admin_token_hash(token), int(row["id"]), expires_at, now),
        )
        connection.execute(
            """
            UPDATE admin_users
            SET last_login_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, int(row["id"])),
        )
        connection.commit()

    return {
        "access_token": token,
        "token_type": "bearer",
        "admin": {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "status": row["status"],
        },
    }


@router.get("/me")
async def admin_me(admin: dict[str, Any] = Depends(require_admin_user)) -> dict[str, Any]:
    return admin


@router.post("/logout")
async def admin_logout(
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
) -> dict[str, bool]:
    db_path = _get_db_path(store)
    # 双因子验证：HMAC 签名 + Bearer Token
    verify_admin_hmac_headers(db_path, request)
    token = _bearer_token(authorization)
    if token:
        _ensure_admin_tables(db_path)
        with sqlite3.connect(db_path) as connection:
            connection.execute(f"DELETE FROM {_ADMIN_TOKENS_TABLE} WHERE token = ?", (_admin_token_hash(token),))
            connection.commit()
    return {"ok": True}
