from __future__ import annotations

import hashlib
import secrets
from typing import Any

import bcrypt

from .models import (
    CLIENT_PASSWORD_ITERATIONS,
    CLIENT_PASSWORD_PEPPER,
    CLIENT_PASSWORD_SALT,
)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def client_password_hash(password: str) -> str:
    peppered = hashlib.sha256(str(password).encode("utf-8") + CLIENT_PASSWORD_PEPPER).digest()
    return hashlib.pbkdf2_hmac(
        "sha256",
        peppered,
        CLIENT_PASSWORD_SALT,
        CLIENT_PASSWORD_ITERATIONS,
        dklen=32,
    ).hex()


def legacy_public_client_password_hash(password: str) -> str:
    """Match the removed /password-params client hash for legacy accounts."""
    pepper_digest = hashlib.sha256(CLIENT_PASSWORD_PEPPER).digest()
    salt_digest = hashlib.sha256(CLIENT_PASSWORD_SALT).digest()
    peppered = hashlib.sha256(str(password).encode("utf-8") + pepper_digest).digest()
    return hashlib.pbkdf2_hmac(
        "sha256",
        peppered,
        salt_digest,
        CLIENT_PASSWORD_ITERATIONS,
        dklen=32,
    ).hex()


def _looks_like_client_hash(value: str) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def _password_candidates(password: str) -> list[str]:
    text = str(password or "")
    candidates = [text]
    if not _looks_like_client_hash(text):
        candidates.append(client_password_hash(text))
        candidates.append(legacy_public_client_password_hash(text))
    return list(dict.fromkeys(candidates))


def _hash_login_password(password: str) -> str:
    text = str(password or "")
    return _hash_password(text if _looks_like_client_hash(text) else client_password_hash(text))


def _verify_login_password(password: str, password_hash: str) -> bool:
    return any(_verify_password(candidate, password_hash) for candidate in _password_candidates(password))


def _generate_token() -> str:
    return secrets.token_hex(32)


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _seconds_between_sql(end_expr: str, start_expr: str = "login_at") -> str:
    return f"MAX(0, CAST(strftime('%s', {end_expr}) - strftime('%s', {start_expr}) AS INTEGER))"


def _online_seconds_expr(now_expr: str = "datetime('now')") -> str:
    active_end = f"CASE WHEN expires_at < {now_expr} THEN expires_at ELSE {now_expr} END"
    return (
        "CASE "
        f"WHEN status = 'active' THEN {_seconds_between_sql(active_end)} "
        "ELSE COALESCE(estimated_online_seconds, 0) "
        "END"
    )


def _masked_token(token: str) -> str:
    text = str(token or "")
    if len(text) <= 12:
        return "***"
    return f"{text[:8]}...{text[-4:]}"


def _fulltext_content_hash(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def estimate_token_count(text: str) -> int:
    return max(0, (len(str(text or "")) + 3) // 4)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _bearer_token(authorization: str) -> str:
    text = str(authorization or "").strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


def _public_user(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "is_author": int(row.get("is_author") or 0),
        "is_admin": int(row.get("is_admin") or 0),
        "status": str(row.get("status") or "active"),
        "bind_reader_id": row.get("bind_reader_id"),
        "bind_reader_name": row.get("bind_reader_name"),
    }
