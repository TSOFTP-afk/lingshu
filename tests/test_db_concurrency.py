"""数据库并发正确性回归测试（阶段 1.2）。

背景：旧实现全 Database 共享一根 SQLite 连接，transaction() 的事务抑制
标志跨线程共享——线程 A 的事务期间线程 B 的写入被并进同一事务，A 回滚
会连带丢弃 B 的数据。改为线程本地连接后，本文件的场景都必须成立。

说明：SQLite 同一时刻只允许一个写者，B 的写入在 A 的事务窗口内会经
busy_timeout 短暂阻塞、待 A 回滚释放写锁后继续——这正是隔离生效的表现；
在旧的共享连接架构下 B 的写入不会阻塞而是混入 A 的事务并被回滚吞掉。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from novel_app.database import Database


@pytest.fixture()
def db(tmp_path: Path):
    database = Database(db_path=tmp_path / "concurrency.db")
    database.initialize()
    yield database
    database.close()


def _start_and_join(targets: list) -> None:
    """并发启动全部线程并等待结束；任一线程抛异常则在主线程重抛。"""
    errors: list[Exception] = []

    def wrap(fn):
        def target():
            try:
                fn()
            except Exception as exc:
                errors.append(exc)
        return target

    threads = [threading.Thread(target=wrap(fn)) for fn in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "工作线程 30s 未结束（可能死锁）"
    if errors:
        raise errors[0]


def _titles(db: Database) -> set[str]:
    return {row["title"] for row in db.connection.execute("SELECT title FROM books").fetchall()}


def test_rollback_in_one_thread_does_not_discard_other_thread_commit(db: Database):
    """线程 A 事务回滚，不得丢弃并发线程 B 已独立提交的写入。"""
    entered = threading.Event()

    def thread_a():
        try:
            with db.transaction():
                db.create_book("A-将被回滚")
                entered.set()
                time.sleep(0.5)  # 持事务窗口，给 B 制造交错
                raise RuntimeError("触发回滚")
        except RuntimeError:
            pass

    def thread_b():
        entered.wait(timeout=10)
        db.create_book("B-必须存活")

    _start_and_join([thread_a, thread_b])

    titles = _titles(db)
    assert "B-必须存活" in titles
    assert "A-将被回滚" not in titles


def test_parallel_transactions_commit_independently(db: Database):
    """两个线程同时各自在事务中写不同书籍，经 busy_timeout 排队后都成功。"""
    def worker(title: str):
        with db.transaction():
            db.create_book(title)

    _start_and_join([lambda: worker("并发-甲"), lambda: worker("并发-乙")])

    assert {"并发-甲", "并发-乙"} <= _titles(db)


def test_suppressed_flag_does_not_leak_across_threads(db: Database):
    """线程 A 事务抑制态下，线程 B 的显式 commit() 必须真实持久化。

    旧共享连接架构下 B 的 commit 会被 A 的事务抑制标志吞掉、数据随 A 回滚
    丢失；线程本地连接后 B 的提交不受 A 影响。
    """
    entered = threading.Event()

    def thread_a():
        try:
            with db.transaction():
                db.create_book("A-回滚")
                entered.set()
                time.sleep(0.5)
                raise RuntimeError("回滚")
        except RuntimeError:
            pass

    def thread_b():
        entered.wait(timeout=10)
        db.create_book("B-立即可见")
        db.connection.commit()

    _start_and_join([thread_a, thread_b])

    titles = _titles(db)
    assert "B-立即可见" in titles
    assert "A-回滚" not in titles
