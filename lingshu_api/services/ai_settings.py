from __future__ import annotations

import copy
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from novel_app.ai.types import DEFAULT_BASE_URL
from novel_app.secure_storage import protect_secret, unprotect_secret

AI_SETTINGS_VERSION = "ai_profiles_v3_book_analysis_pyramid"

AI_PURPOSES: dict[str, dict[str, str]] = {
    "writing": {"label": "写作生成", "description": "章节草稿生成、续写、润色"},
    "outline": {"label": "同步大纲", "description": "根据正文同步章节或书籍大纲"},
    "detector": {"label": "AI概率检测", "description": "检测正文 AI 生成痕迹"},
    "correction": {"label": "AI纠错", "description": "中文错别字检测与修改建议"},
    "import": {"label": "智能导入分类", "description": "判断导入文档类型和章节结构"},
    "skills": {"label": "Skills提炼", "description": "从参考文本提炼写作约束"},
    "book_analysis": {"label": "全书分析", "description": "三级全书分析流程"},
    "review": {"label": "长篇生成/校验", "description": "审查、校验和多智能体长篇流程"},
    "chat": {"label": "AI 对话", "description": "多轮对话式写作辅助"},
    "writing_probe": {
        "label": "写作探针",
        "description": "章节写作时后台静默扫描，生成人物与概要草稿（默认8秒间隔）",
    },
}

PURPOSE_ALIASES: dict[str, str] = {
    "generation": "writing",
    "generate": "writing",
    "writer": "writing",
    "review_ws": "review",
    "analysis": "book_analysis",
    "book-analysis": "book_analysis",
    "conversation": "chat",
}

PROFILE_DEFAULTS: dict[str, Any] = {
    "remote_enabled": False,
    "provider": "custom",
    "api_key": "",
    "base_url": DEFAULT_BASE_URL,
    "model": "",
    "temperature": 0.7,
    "max_tokens": 0,
    "thinking_enabled": False,
    "thinking_budget_tokens": 10000,
    "interval_seconds": 8,
    "auto_write_threshold": 0.55,
    "probe_enabled": False,
}


def settings_path(data_dir: Path) -> Path:
    """旧版全局 ai_settings.json 路径（仅用于向后兼容读取一次迁移）。"""
    return data_dir / "ai_settings.json"


def _bookstore_db_path(data_dir: Path) -> Path:
    """根据 data_dir 推导 bookstore_demo.db 路径（与 Database 同目录约定）。"""
    env_db = os.environ.get("BOOKSTORE_DB_PATH", "").strip()
    if env_db:
        return Path(env_db)
    return data_dir / "bookstore_demo.db"


def default_ai_settings() -> dict[str, Any]:
    return {
        "version": AI_SETTINGS_VERSION,
        "profiles": {key: copy.deepcopy(PROFILE_DEFAULTS) for key in AI_PURPOSES},
        "request_retries": 2,
        "book_analysis_concurrency": 3,
        "book_analysis_fast_extra_body": "",
        "book_analysis_final_extra_body": "",
    }


def normalize_purpose(purpose: str | None) -> str:
    raw = str(purpose or "writing").strip()
    raw = PURPOSE_ALIASES.get(raw, raw)
    return raw if raw in AI_PURPOSES else "writing"


def _normalize_profile(profile: dict[str, Any], key: str, *, reveal_secrets: bool) -> dict[str, Any]:
    """规整单个 profile 字段，返回规整后的 dict（原地修改 + 返回）。"""
    profile["purpose"] = key
    profile["label"] = AI_PURPOSES[key]["label"]
    profile["description"] = AI_PURPOSES[key]["description"]
    profile["remote_enabled"] = bool(profile.get("remote_enabled"))
    profile["provider"] = str(profile.get("provider") or "custom").strip() or "custom"
    profile["base_url"] = str(profile.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    profile["model"] = str(profile.get("model") or "").strip()
    profile["temperature"] = _float(profile.get("temperature"), 0.7)
    profile["max_tokens"] = _int(profile.get("max_tokens"), 0)
    profile["thinking_enabled"] = bool(profile.get("thinking_enabled"))
    profile["thinking_budget_tokens"] = _int(profile.get("thinking_budget_tokens"), 10000)
    profile["interval_seconds"] = max(5, min(60, _int(profile.get("interval_seconds"), 8)))
    profile["auto_write_threshold"] = max(0.0, min(1.0, _float(profile.get("auto_write_threshold"), 0.55)))
    profile["probe_enabled"] = bool(profile.get("probe_enabled"))
    stored_api_key = str(profile.get("api_key") or "")
    decoded_api_key = _decode_secret(stored_api_key) if stored_api_key else ""
    profile["api_key"] = decoded_api_key if reveal_secrets else ""
    profile["api_key_configured"] = bool(decoded_api_key or stored_api_key)
    return profile


def _load_user_profiles_from_db(db_path: Path, user_id: int) -> dict[str, dict[str, Any]]:
    """从 user_ai_settings 表读取该用户的所有 profile（已解密 api_key）。"""
    profiles: dict[str, dict[str, Any]] = {}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT purpose, profile_json FROM user_ai_settings WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
        for row in rows:
            try:
                data = json.loads(row["profile_json"] or "{}")
                if isinstance(data, dict):
                    profiles[str(row["purpose"])] = data
            except (json.JSONDecodeError, TypeError):
                continue
    except sqlite3.Error:
        pass
    return profiles


def _save_user_profile_to_db(db_path: Path, user_id: int, purpose: str, profile: dict[str, Any]) -> None:
    """upsert 单个 profile 到 user_ai_settings 表（api_key 加密存储）。"""
    serializable = copy.deepcopy(profile)
    serializable.pop("purpose", None)
    serializable.pop("label", None)
    serializable.pop("description", None)
    serializable.pop("api_key_configured", None)
    serializable["api_key"] = protect_secret(
        str(serializable.get("api_key") or ""), allow_plaintext_fallback=True
    )
    payload_json = json.dumps(serializable, ensure_ascii=False)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO user_ai_settings (user_id, purpose, profile_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, purpose) DO UPDATE SET
                profile_json = excluded.profile_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(user_id), purpose, payload_json),
        )
        conn.commit()


def load_ai_settings(data_dir: Path, *, reveal_secrets: bool = False, user_id: int | None = None) -> dict[str, Any]:
    """加载 AI 设置。若提供 user_id 则按账号隔离读取（user_ai_settings 表），
    否则回退到旧的 ai_settings.json（向后兼容，不推荐）。
    """
    settings = default_ai_settings()

    if user_id is not None:
        # 按账号隔离：从数据库读取
        db_path = _bookstore_db_path(data_dir)
        stored_profiles = _load_user_profiles_from_db(db_path, int(user_id))
        for key in AI_PURPOSES:
            stored = stored_profiles.get(key)
            if isinstance(stored, dict):
                settings["profiles"][key].update(stored)
    else:
        # 向后兼容：读全局 JSON（仅旧路径，不应再被新代码使用）
        path = settings_path(data_dir)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
            if isinstance(raw, dict):
                settings.update({k: v for k, v in raw.items() if k != "profiles"})
                profiles = raw.get("profiles")
                if isinstance(profiles, dict):
                    for key in AI_PURPOSES:
                        stored = profiles.get(key)
                        if isinstance(stored, dict):
                            settings["profiles"][key].update(stored)

    for key, profile in settings["profiles"].items():
        _normalize_profile(profile, key, reveal_secrets=reveal_secrets)
    return settings


def save_ai_settings(data_dir: Path, payload: dict[str, Any], *, user_id: int | None = None) -> dict[str, Any]:
    """保存 AI 设置。若提供 user_id 则按账号隔离写入（user_ai_settings 表），
    否则回退到旧的 ai_settings.json（向后兼容，不推荐）。
    """
    if user_id is None:
        # 向后兼容：写全局 JSON
        return _save_ai_settings_legacy(data_dir, payload)

    current = load_ai_settings(data_dir, reveal_secrets=True, user_id=user_id)
    incoming_profiles = payload.get("profiles") if isinstance(payload, dict) else {}
    if not isinstance(incoming_profiles, dict):
        incoming_profiles = {}

    db_path = _bookstore_db_path(data_dir)
    for key in AI_PURPOSES:
        incoming = incoming_profiles.get(key)
        if not isinstance(incoming, dict):
            continue
        profile = copy.deepcopy(current["profiles"][key])
        for field in (
            "remote_enabled",
            "provider",
            "base_url",
            "model",
            "temperature",
            "max_tokens",
            "thinking_enabled",
            "thinking_budget_tokens",
            "interval_seconds",
            "auto_write_threshold",
            "probe_enabled",
        ):
            if field in incoming:
                profile[field] = incoming[field]
        if "api_key" in incoming:
            profile["api_key"] = str(incoming.get("api_key") or "")
        _save_user_profile_to_db(db_path, int(user_id), key, profile)

    return load_ai_settings(data_dir, reveal_secrets=True, user_id=user_id)


def _save_ai_settings_legacy(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """旧版全局 JSON 写入（向后兼容，仅 user_id=None 时使用）。"""
    current = load_ai_settings(data_dir, reveal_secrets=True)
    incoming_profiles = payload.get("profiles") if isinstance(payload, dict) else {}
    if not isinstance(incoming_profiles, dict):
        incoming_profiles = {}

    for key in AI_PURPOSES:
        incoming = incoming_profiles.get(key)
        if not isinstance(incoming, dict):
            continue
        profile = current["profiles"][key]
        for field in (
            "remote_enabled",
            "provider",
            "base_url",
            "model",
            "temperature",
            "max_tokens",
            "thinking_enabled",
            "thinking_budget_tokens",
            "interval_seconds",
            "auto_write_threshold",
            "probe_enabled",
        ):
            if field in incoming:
                profile[field] = incoming[field]
        if "api_key" in incoming:
            profile["api_key"] = str(incoming.get("api_key") or "")

    for field in (
        "request_retries",
        "book_analysis_concurrency",
        "book_analysis_fast_extra_body",
        "book_analysis_final_extra_body",
    ):
        if field in payload:
            current[field] = payload[field]

    serializable = copy.deepcopy(current)
    serializable["version"] = str(payload.get("version") or AI_SETTINGS_VERSION)
    for _key, profile in serializable["profiles"].items():
        profile.pop("purpose", None)
        profile.pop("label", None)
        profile.pop("description", None)
        profile.pop("api_key_configured", None)
        profile["remote_enabled"] = bool(profile.get("remote_enabled"))
        profile["provider"] = str(profile.get("provider") or "custom").strip() or "custom"
        profile["base_url"] = str(profile.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        profile["model"] = str(profile.get("model") or "").strip()
        profile["temperature"] = _float(profile.get("temperature"), 0.7)
        profile["max_tokens"] = _int(profile.get("max_tokens"), 0)
        profile["thinking_enabled"] = bool(profile.get("thinking_enabled"))
        profile["thinking_budget_tokens"] = _int(profile.get("thinking_budget_tokens"), 10000)
        profile["interval_seconds"] = max(5, min(60, _int(profile.get("interval_seconds"), 8)))
        profile["auto_write_threshold"] = max(0.0, min(1.0, _float(profile.get("auto_write_threshold"), 0.55)))
        profile["probe_enabled"] = bool(profile.get("probe_enabled"))
        profile["api_key"] = protect_secret(str(profile.get("api_key") or ""), allow_plaintext_fallback=True)

    data_dir.mkdir(parents=True, exist_ok=True)
    settings_path(data_dir).write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return load_ai_settings(data_dir, reveal_secrets=True)


def resolve_ai_profile(data_dir: Path, purpose: str | None, *, user_id: int | None = None) -> dict[str, Any]:
    key = normalize_purpose(purpose)
    settings = load_ai_settings(data_dir, reveal_secrets=True, user_id=user_id)
    profile = copy.deepcopy(settings["profiles"][key])

    env_api_key = (
        os.environ.get("LINGSHU_AI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    env_base_url = (
        os.environ.get("LINGSHU_AI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    ).strip()
    env_model = (
        os.environ.get("LINGSHU_AI_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or ""
    ).strip()

    if not profile.get("api_key") and env_api_key:
        profile["api_key"] = env_api_key
    if (not profile.get("base_url") or profile.get("base_url") == DEFAULT_BASE_URL) and env_base_url:
        profile["base_url"] = env_base_url
    if not profile.get("model") and env_model:
        profile["model"] = env_model

    if env_api_key and env_model and not profile.get("remote_enabled"):
        profile["remote_enabled"] = True

    if not profile.get("remote_enabled"):
        profile["api_key"] = ""
        profile["model"] = ""

    # 构建思考模式 extra_body
    if profile.get("thinking_enabled"):
        budget = profile.get("thinking_budget_tokens", 10000)
        existing_extra = {}
        if profile.get("extra_body"):
            try:
                existing_extra = json.loads(profile["extra_body"]) if isinstance(profile["extra_body"], str) else profile["extra_body"]
            except (json.JSONDecodeError, TypeError):
                existing_extra = {}
        existing_extra["thinking"] = {
            "type": "enabled",
            "budget_tokens": budget,
        }
        profile["extra_body"] = json.dumps(existing_extra, ensure_ascii=False)

    return profile


def validate_profile_ready(profile: dict[str, Any]) -> tuple[bool, str]:
    if not profile.get("remote_enabled"):
        return False, "该用途未启用远程 AI。"
    if not str(profile.get("api_key") or "").strip():
        return False, "缺少 API Key。"
    if not str(profile.get("model") or "").strip():
        return False, "缺少模型名称。"
    if not str(profile.get("base_url") or "").strip():
        return False, "缺少 Base URL。"
    return True, "配置可用。"


def _decode_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return unprotect_secret(value)
    except Exception:
        return ""


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
