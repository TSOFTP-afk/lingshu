"""轻量 schema 迁移机制测试（阶段 1.4）。

覆盖三块：
1. 共享工具 ensure_column / ensure_schema_version / get_applied_versions 的
   单元行为（临时 sqlite3.Connection 上验证：添加缺失列、幂等、非法标识符拒绝）；
2. Database（novel_app 主库）初始化后登记 baseline 版本；
3. novel_app.bookstore.models 初始化后登记 bookstore baseline 版本。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from novel_app.database import Database
from novel_app.db.migrations import (
    ensure_column,
    ensure_schema_version,
    get_applied_versions,
)


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(tmp_path / "migrations.db")
    connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    yield connection
    connection.close()


def test_ensure_column_adds_missing_column(conn: sqlite3.Connection):
    assert ensure_column(conn, "sample", "title", "TEXT NOT NULL DEFAULT ''") is True
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sample)").fetchall()}
    assert "title" in columns


def test_ensure_column_idempotent(conn: sqlite3.Connection):
    ensure_column(conn, "sample", "title", "TEXT NOT NULL DEFAULT ''")
    # 重复调用不抛异常、不重复添加
    assert ensure_column(conn, "sample", "title", "TEXT NOT NULL DEFAULT ''") is False
    columns = [row[1] for row in conn.execute("PRAGMA table_info(sample)").fetchall()]
    assert columns.count("title") == 1


@pytest.mark.parametrize("table", ["sample; DROP TABLE sample", "sample-1", "", "1abc"])
def test_ensure_column_rejects_unsafe_table_name(conn: sqlite3.Connection, table: str):
    with pytest.raises(ValueError):
        ensure_column(conn, table, "title", "TEXT")


@pytest.mark.parametrize("column", ["title; DROP TABLE sample", "a b", "", "9x"])
def test_ensure_column_rejects_unsafe_column_name(conn: sqlite3.Connection, column: str):
    with pytest.raises(ValueError):
        ensure_column(conn, "sample", column, "TEXT")


def test_ensure_column_works_with_thread_safe_connection(tmp_path: Path):
    """ensure_column 兼容 ThreadSafeConnection 包装。"""
    database = Database(db_path=tmp_path / "wrap.db")
    database.initialize()
    try:
        assert ensure_column(database.connection, "books", "migration_probe_col", "TEXT NOT NULL DEFAULT ''") is True
        columns = {row[1] for row in database.connection.execute("PRAGMA table_info(books)").fetchall()}
        assert "migration_probe_col" in columns
    finally:
        database.close()


def test_schema_version_first_record_then_idempotent(conn: sqlite3.Connection):
    assert ensure_schema_version(conn, "v1", context="测试上下文") is True
    # 重复登记同一版本幂等
    assert ensure_schema_version(conn, "v1", context="测试上下文") is False
    assert get_applied_versions(conn) == ["v1"]
    assert ensure_schema_version(conn, "v2") is True
    assert get_applied_versions(conn) == ["v1", "v2"]


def test_get_applied_versions_empty_before_any_migration(tmp_path: Path):
    connection = sqlite3.connect(tmp_path / "empty.db")
    try:
        assert get_applied_versions(connection) == []
    finally:
        connection.close()


def test_database_initialize_registers_baseline(tmp_path: Path):
    database = Database(db_path=tmp_path / "main.db")
    database.initialize()
    try:
        tables = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "schema_migrations" in tables
        assert get_applied_versions(database.connection) == ["baseline-2026-09"]
    finally:
        database.close()


def test_database_initialize_baseline_idempotent(tmp_path: Path):
    """重复 initialize 不得重复登记，也不得因版本表已存在而失败。"""
    database = Database(db_path=tmp_path / "main.db")
    database.initialize()
    database.initialize()
    try:
        assert get_applied_versions(database.connection) == ["baseline-2026-09"]
    finally:
        database.close()


def test_bookstore_initialize_registers_baseline(tmp_path: Path):
    from novel_app.bookstore import models as bookstore_models

    db_path = tmp_path / "bookstore.db"
    bookstore_models.initialize_database(db_path)
    connection = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert "schema_migrations" in tables
        assert get_applied_versions(connection) == ["bookstore-baseline-2026-09"]
    finally:
        connection.close()
