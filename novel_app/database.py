from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
from pathlib import Path
from threading import RLock
from typing import Any

from novel_app.db.analysis import AnalysisMixin
from novel_app.db.chapter_generation_snapshots import ChapterGenerationSnapshotMixin
from novel_app.db.character_state_machine import CharacterStateMachineMixin
from novel_app.db.characters import CharactersMixin
from novel_app.db.common import ALL_VOLUMES, UNASSIGNED_VOLUMES
from novel_app.db.legacy import LegacyMixin
from novel_app.db.library import LibraryMixin
from novel_app.db.media import MediaMixin
from novel_app.db.resources import ResourcesMixin
from novel_app.db.review import ReviewMixin
from novel_app.db.schema import SchemaMixin
from novel_app.db.structured import StructuredMixin
from novel_app.db.sync_changelog import SyncChangelogMixin


def cjk_unigram(s: str | None) -> str:
    """把 CJK 字符前后加空格，让 unicode61 tokenizer 能按字符切分。

    SQLite FTS5 的 unicode61 tokenizer 默认把连续的 CJK 字符序列当作
    一个 token，导致中文子串搜索（如 "白狐" 在 "白狐回头" 中）失败。
    本函数把每个 CJK 字符前后加空格，使 unicode61 按空格切分为单字 token；
    英文/数字/标点保持原样（英文单词完整性不破坏）。

    调用方：
    - schema.py 的 FTS5 触发器：cjk_unigram(new.title), cjk_unigram(new.content)
    - db_bridge.py 的 _search_book_fts5：查询串也需经此函数处理

    注册到 SQLite 连接后可在 SQL 中直接调用：cjk_unigram(column)
    """
    if not s:
        return ""
    result: list[str] = []
    for ch in str(s):
        code = ord(ch)
        # CJK 统一表意文字 + 扩展A + 兼容表意
        if (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF) or (0xF900 <= code <= 0xFAFF):
            result.append(" " + ch + " ")
        else:
            result.append(ch)
    return "".join(result)


class ThreadSafeCursor:
    def __init__(self, cursor: sqlite3.Cursor, lock: RLock) -> None:
        self._cursor = cursor
        self._lock = lock

    def __iter__(self):
        with self._lock:
            return iter(self._cursor.fetchall())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def fetchone(self) -> sqlite3.Row | None:
        with self._lock:
            return self._cursor.fetchone()

    def fetchall(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._cursor.fetchall()

    def fetchmany(self, size: int | None = None) -> list[sqlite3.Row]:
        with self._lock:
            return self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size)


class ThreadSafeConnection:
    def __init__(self, connection: sqlite3.Connection, lock: RLock) -> None:
        self._connection = connection
        self._lock = lock
        self._commit_suppressed: bool = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def __enter__(self) -> ThreadSafeConnection:
        self._lock.acquire()
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        try:
            return self._connection.__exit__(exc_type, exc, tb)
        finally:
            self._lock.release()

    def execute(self, *args: Any, **kwargs: Any) -> ThreadSafeCursor:
        with self._lock:
            return ThreadSafeCursor(self._connection.execute(*args, **kwargs), self._lock)

    def executemany(self, *args: Any, **kwargs: Any) -> ThreadSafeCursor:
        with self._lock:
            return ThreadSafeCursor(self._connection.executemany(*args, **kwargs), self._lock)

    def executescript(self, *args: Any, **kwargs: Any) -> ThreadSafeCursor:
        with self._lock:
            return ThreadSafeCursor(self._connection.executescript(*args, **kwargs), self._lock)

    def commit(self) -> None:
        with self._lock:
            if self._commit_suppressed:
                return
            self._connection.commit()

    def rollback(self) -> None:
        with self._lock:
            self._connection.rollback()

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class Database(
    LegacyMixin,
    SchemaMixin,
    StructuredMixin,
    MediaMixin,
    LibraryMixin,
    ReviewMixin,
    AnalysisMixin,
    ResourcesMixin,
    CharactersMixin,
    CharacterStateMachineMixin,
    ChapterGenerationSnapshotMixin,
    SyncChangelogMixin,
):
    def __init__(self, db_path: Path | None = None) -> None:
        configured_data_dir = os.environ.get("SIMPLE_AI_NOVEL_DATA_DIR", "").strip()
        legacy_data_dirs = self._legacy_data_dirs_from_env()
        if db_path is None:
            legacy_data_dirs.extend(self._known_legacy_data_dirs())
        if configured_data_dir:
            self.data_dir = Path(configured_data_dir).expanduser()
        else:
            if getattr(sys, "frozen", False):
                base_dir = Path(sys.executable).resolve().parent
                appdata = Path(os.environ.get("APPDATA", os.path.expanduser("~")))
                legacy_data_dirs.append(appdata / "SimpleAINovelApp" / "data")
            else:
                base_dir = Path(__file__).resolve().parent.parent
            self.data_dir = base_dir / "data"
        self.legacy_data_dirs = self._dedupe_legacy_data_dirs(legacy_data_dirs)
        self.imported_legacy_data_dirs: list[Path] = []
        self.legacy_import_errors: list[tuple[Path, str]] = []
        self.legacy_data_dirs = [path for path in self.legacy_data_dirs if path.exists()]
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.references_dir = self.data_dir / "references" / "imported_books"
        self.references_dir.mkdir(parents=True, exist_ok=True)
        self.project_references_dir = self.data_dir / "references" / "github_projects"
        self.project_references_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir = self.data_dir / "media"
        self.book_covers_dir = self.media_dir / "book_covers"
        self.character_images_dir = self.media_dir / "character_images"
        self.book_covers_dir.mkdir(parents=True, exist_ok=True)
        self.character_images_dir.mkdir(parents=True, exist_ok=True)

        self.exports_dir = self.data_dir / "exports"
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path or self.data_dir / "novels.db"
        raw_connection = sqlite3.connect(self.db_path, check_same_thread=False)
        raw_connection.row_factory = sqlite3.Row
        # 注册 cjk_unigram 函数，供 FTS5 触发器在 SQL 中调用
        # 必须在 migrations 之前注册，否则触发器执行时会找不到函数
        raw_connection.create_function("cjk_unigram", 1, cjk_unigram)
        self._connection_lock = RLock()
        self.connection = ThreadSafeConnection(raw_connection, self._connection_lock)
        # busy_timeout 必须在 migrations 之前设置，避免新连接初始化时
        # 遇到正在运行的分析管线持有写锁而立即失败 (database is locked)
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.connection.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self):
        """将多个写操作包裹在单个事务中，失败时自动回滚。

        在事务期间，各 mixin 方法的 commit() 调用会被抑制，
        退出上下文时统一 commit 或 rollback。
        """
        conn = self.connection
        conn._commit_suppressed = True
        try:
            yield
            conn._connection.commit()
        except Exception:
            conn._connection.rollback()
            raise
        finally:
            conn._commit_suppressed = False


__all__ = ["ALL_VOLUMES", "UNASSIGNED_VOLUMES", "Database"]
