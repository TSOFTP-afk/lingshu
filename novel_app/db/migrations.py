"""轻量 schema 迁移工具（阶段 1.4）。

替代散落在 schema.py / bookstore.models.py 中依靠
`except OperationalError + "duplicate column name"` 字符串匹配的 DDL 写法：
- ensure_column: 先用 PRAGMA table_info 检查列是否存在，缺失才 ALTER TABLE；
- ensure_schema_version / get_applied_versions: 以 schema_migrations 表登记
  版本号，使 schema 演进可查、登记幂等可重放。

connection 参数兼容原生 sqlite3.Connection 与项目里的 ThreadSafeConnection
包装（两者都暴露 .execute / .fetchone / .fetchall）。

本模块不依赖任何具体 Database 类，可被 db 与 bookstore 双方共享。
"""
from __future__ import annotations

import sqlite3


def sql_identifier(value: str) -> str:
    """校验并引用 SQL 标识符（表名/列名），防注入。

    只允许字母数字下划线且不以数字开头；校验通过后再用双引号包裹
    （内部双引号转义），与 bookstore.models._sql_identifier 行为一致。
    """
    text = str(value or "")
    if not text or text[0].isdigit() or not all(char.isalnum() or char == "_" for char in text):
        raise ValueError(f"Unsafe SQL identifier: {text!r}")
    return '"' + text.replace('"', '""') + '"'


def _table_columns(connection, table_name: str) -> set[str]:
    """返回表的既有列名集合（小写比较，SQLite 列名不区分大小写）。"""
    cursor = connection.execute(f"PRAGMA table_info({sql_identifier(table_name)})")
    return {str(row[1]).lower() for row in cursor.fetchall()}


def ensure_column(connection, table_name: str, column_name: str, definition: str) -> bool:
    """确保表存在指定列：缺失则 ALTER TABLE ADD COLUMN，已存在则跳过。

    返回是否实际执行了 ALTER（便于调用方断言与测试）。
    用 PRAGMA table_info 判断存在性，不再依赖异常字符串匹配。
    """
    table = sql_identifier(table_name)
    column = sql_identifier(column_name)
    if column_name.lower() in _table_columns(connection, table_name):
        return False
    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def ensure_schema_version(connection, version_id: str, context: str = "") -> bool:
    """登记一个已应用的迁移版本；首次登记返回 True，重复登记幂等返回 False。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version_id TEXT PRIMARY KEY,
            context TEXT,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    row = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version_id = ?",
        (version_id,),
    ).fetchone()
    if row is not None:
        return False
    connection.execute(
        "INSERT INTO schema_migrations (version_id, context) VALUES (?, ?)",
        (version_id, context),
    )
    return True


def get_applied_versions(connection) -> list[str]:
    """返回已登记的迁移版本号（按 version_id 排序）；版本表不存在时返回空列表。"""
    try:
        rows = connection.execute(
            "SELECT version_id FROM schema_migrations ORDER BY version_id"
        ).fetchall()
    except sqlite3.OperationalError:
        # 库尚未初始化 schema_migrations 表
        return []
    return [str(row[0]) for row in rows]
