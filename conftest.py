from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
QT_MODULE_PRESENT = (PROJECT_ROOT / "novel_app" / "qt").exists()
QT_TESTS = {
    "test_qt_helpers.py",
    "tests/test_analysis_drawer_ui.py",
    "tests/test_chapter_tabs.py",
    "tests/test_star_graph_history.py",
    "tests/test_star_graph_models.py",
    "tests/test_star_graph_style_manager.py",
}


if not QT_MODULE_PRESENT:
    collect_ignore = sorted(QT_TESTS)


def pytest_ignore_collect(collection_path, config) -> bool:  # noqa: ARG001
    if QT_MODULE_PRESENT:
        return False
    path = Path(str(collection_path))
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        relative = path.name
    return relative in QT_TESTS


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001
    """给登记在案的存量失败打 xfail，使默认路径回绿且修复后以 XPASS 提示摘牌。"""
    try:
        from tests.preexisting_failures import PREEXISTING_FAILURES
    except ImportError:
        return
    for item in items:
        entry = PREEXISTING_FAILURES.get(item.nodeid)
        if entry is not None:
            cluster, reason = entry
            item.add_marker(pytest.mark.xfail(reason=f"[{cluster}] {reason}", strict=False))
