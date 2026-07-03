from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WORKSPACE_SETTINGS_VERSION = "workspace_settings_v1"
ANALYSIS_PIPELINE_MODES = {"legacy", "v3"}


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / "workspace_settings.json"


def default_workspace_settings() -> dict[str, Any]:
    return {
        "version": WORKSPACE_SETTINGS_VERSION,
        "analysis_pipeline_mode": "legacy",
    }


def load_workspace_settings(data_dir: Path) -> dict[str, Any]:
    settings = default_workspace_settings()
    path = settings_path(data_dir)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            settings.update(raw)
    settings["version"] = str(settings.get("version") or WORKSPACE_SETTINGS_VERSION)
    settings["analysis_pipeline_mode"] = normalize_analysis_pipeline_mode(
        settings.get("analysis_pipeline_mode")
    )
    return settings


def save_workspace_settings(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_workspace_settings(data_dir)
    if "analysis_pipeline_mode" in payload:
        current["analysis_pipeline_mode"] = normalize_analysis_pipeline_mode(
            payload.get("analysis_pipeline_mode")
        )
    current["version"] = WORKSPACE_SETTINGS_VERSION
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    settings_path(data_dir).write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return load_workspace_settings(data_dir)


def normalize_analysis_pipeline_mode(value: Any) -> str:
    mode = str(value or "legacy").strip().lower()
    return mode if mode in ANALYSIS_PIPELINE_MODES else "legacy"
