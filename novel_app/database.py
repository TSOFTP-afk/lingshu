from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
import time
from pathlib import Path
from threading import Lock, RLock, local
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
    def __init__(self, connection: sqlite3.Connection, lock: RLock, registry: ThreadLocalConnections | None = None) -> None:
        self._connection = connection
        self._lock = lock
        self._registry = registry
        self._last_sql = ""
        self._txn_origin = ""
        # 事务抑制计数（支持 transaction() 嵌套：内层退出后外层仍处于抑制态）
        self._commit_suppressed: int = 0

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

    def _dump_lock_holders(self) -> str:
        if self._registry is None:
            return ""
        try:
            return "\n" + self._registry.describe_pending_transactions()
        except Exception:  # pragma: no cover - 诊断信息失败不影响原错误
            return ""

    def execute(self, *args: Any, **kwargs: Any) -> ThreadSafeCursor:
        self._last_sql = " ".join(str(args[0]).split())[:120] if args else ""
        if (
            args
            and not self.in_transaction
            and str(args[0]).lstrip()[:6].upper() in ("INSERT", "UPDATE", "DELETE", "REPLAC")
        ):
            # 写语句首次开启事务时记录调用栈，用于定位"写了不提交"的泄漏点
            import traceback as _tb

            self._txn_origin = "".join(_tb.format_stack(limit=-14))
        with self._lock:
            try:
                return ThreadSafeCursor(self._connection.execute(*args, **kwargs), self._lock)
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc):
                    raise sqlite3.OperationalError(
                        f"{exc} — 当前连接 last_sql={self._last_sql!r}{self._dump_lock_holders()}"
                    ) from None
                raise

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


class ThreadLocalConnections:
    """每线程独立 SQLite 连接注册表。

    旧实现是全 Database 共享一根 check_same_thread=False 的连接：事务抑制
    标志跨线程共享，一个线程 transaction() 期间其他线程的写入会被并进同一
    事务，commit/rollback 会波及全部线程。改为每线程一根连接后，事务边界
    天然线程隔离；连接在线程首次访问时惰性创建并复用（FastAPI 的线程池
    线程会长期存活，连接数上界 = 线程池大小）。

    check_same_thread 保持 False：连接按构造只被属主线程使用，但
    close_all() 可能从主线程关闭工作线程创建的连接（测试临时目录清理、
    应用退出路径都依赖这一点）。
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._local = local()
        self._all: list[ThreadSafeConnection] = []
        self._registry_lock = Lock()
        self._closed = False

    def get(self) -> ThreadSafeConnection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_connection()
            self._local.conn = conn
            # 无条件入册：close() 之后才首次访问的线程（如分析管线后台线程
            # 收尾）也能被 close_all 的排空循环追上关闭，避免句柄泄漏导致
            # Windows 下临时目录无法删除
            with self._registry_lock:
                self._all.append(conn)
        return conn

    def describe_pending_transactions(self) -> str:
        """诊断用：列出所有连接的未决事务、起源栈与最后一条 SQL。"""
        with self._registry_lock:
            lines = []
            for conn in self._all:
                try:
                    pending = conn.in_transaction
                except Exception:
                    pending = "?"
                line = f"  in_txn={pending} suppressed={conn._commit_suppressed} last_sql={conn._last_sql!r}"
                if pending and conn._txn_origin:
                    line += "\n    事务起源:\n" + "\n".join(
                        f"      {ln}" for ln in conn._txn_origin.strip().splitlines()
                    )
                lines.append(line)
            return f"数据库连接注册表（共 {len(self._all)} 根）:\n" + "\n".join(lines)

    def _new_connection(self) -> ThreadSafeConnection:
        raw = sqlite3.connect(self._db_path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        # 注册 cjk_unigram 函数，供 FTS5 触发器在 SQL 中调用
        raw.create_function("cjk_unigram", 1, cjk_unigram)
        wrapper = ThreadSafeConnection(raw, RLock(), registry=self)
        # busy_timeout/foreign_keys/synchronous 均为连接级设置，每根连接都要设；
        # journal_mode=WAL 是库级持久属性，重复设置无害。
        # busy_timeout 必须在 migrations 之前设置，避免新连接初始化时
        # 遇到正在运行的分析管线持有写锁而立即失败 (database is locked)
        wrapper.execute("PRAGMA busy_timeout = 10000")
        wrapper.execute("PRAGMA foreign_keys = ON")
        wrapper.execute("PRAGMA journal_mode = WAL")
        wrapper.execute("PRAGMA synchronous = NORMAL")
        return wrapper

    def close_all(self) -> None:
        self._closed = True
        # 排空循环：关闭之后仍可能有后台线程（如 V3 记忆层的 bg 线程）首次
        # 访问 DB 并注册新连接，注册表瞬时为空不代表没有迟到者——必须等到
        # 静默期（连续无新增）才返回，兜底时限防止真正挂死的线程拖住关闭
        deadline = time.monotonic() + 5.0
        last_activity = time.monotonic()
        while time.monotonic() < deadline:
            with self._registry_lock:
                pending = self._all[:]
                self._all.clear()
            for conn in pending:
                with contextlib.suppress(Exception):
                    conn.close()
            with self._registry_lock:
                if self._all:
                    last_activity = time.monotonic()
                elif time.monotonic() - last_activity >= 0.5:
                    return
            time.sleep(0.05)


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
        self._connections = ThreadLocalConnections(self.db_path)

    @property
    def connection(self) -> ThreadSafeConnection:
        """当前线程的 SQLite 连接（惰性创建，线程内复用）。"""
        return self._connections.get()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._connections.close_all()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self):
        """将当前线程的多个写操作包裹在单个事务中，失败时自动回滚。

        在事务期间，各 mixin 方法的 commit() 调用会被抑制（按计数支持嵌套），
        退出上下文时统一 commit 或 rollback。连接是线程本地的，事务边界
        不会波及其他线程的写入。
        """
        conn = self.connection
        if conn.in_transaction:
            # 防御：线程连接被上一个请求遗留的未决事务污染时先回滚，
            # 避免本事务的失败回滚牵连无关写入
            conn.rollback()
        conn._commit_suppressed += 1
        try:
            yield
        except Exception:
            conn.rollback()
            conn._commit_suppressed -= 1
            raise
        conn._commit_suppressed -= 1
        conn.commit()


__all__ = ["ALL_VOLUMES", "UNASSIGNED_VOLUMES", "Database"]
