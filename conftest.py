from __future__ import annotations

from pathlib import Path


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
