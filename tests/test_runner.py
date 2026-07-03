"""Regression test runner for the Vue/Electron migration baseline.

Run with:
    python tests/test_runner.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--cov=novel_app", "--cov=lingshu_api", "--cov-report=term-missing", "--cov-fail-under=60"],
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(run())
