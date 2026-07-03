from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_SRC = PROJECT_ROOT / "lingshu-app" / "src"
FORBIDDEN_API_PATH = re.compile(r"\bapi\.(?:get|post|put|patch|delete)\(\s*([`'\"])/api/")


def test_lingshu_app_api_client_paths_do_not_repeat_api_prefix() -> None:
    offenders: list[str] = []
    for path in APP_SRC.rglob("*"):
        if path.suffix not in {".js", ".vue"}:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FORBIDDEN_API_PATH.search(line):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert offenders == []
