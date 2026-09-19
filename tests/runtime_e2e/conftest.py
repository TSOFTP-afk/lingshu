"""runtime_e2e 测试套件 pytest 配置 — fixtures 与 marker 注册。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from .helpers import (
    BACKEND_URL,
    E2E_BOOK_PREFIX,
    FRONTEND_URL,
    ApiClient,
    cleanup_e2e_books,
    is_backend_up,
    is_frontend_up,
    login,
    start_backend_subprocess,
    start_frontend_subprocess,
    wait_for,
)

# ================================================================
# Marker 注册
# ================================================================

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "runtime_e2e: runtime E2E test requiring real servers",
    )


def pytest_collection_modifyitems(config, items):
    # pytestmark 在 conftest 中不生效，改用 hook 给本目录所有 item 加 runtime marker，
    # 使其被 pytest.ini 的 `-m "not performance and not runtime"` 默认排除。
    # conftest hook 一旦加载即作用于整个会话，必须按路径过滤，避免殃及目录外的用例。
    here = Path(__file__).resolve().parent
    for item in items:
        if here in Path(item.path).resolve().parents:
            item.add_marker(pytest.mark.runtime)

# 模块级变量：记录 ensure_servers 启动的前端子进程，供 teardown
_frontend_procs: list = []


# ================================================================
# 基础 URL fixtures
# ================================================================

@pytest.fixture(scope="session")
def backend_url():
    return BACKEND_URL


@pytest.fixture(scope="session")
def frontend_url():
    return FRONTEND_URL


# ================================================================
# 服务器启停
# ================================================================

@pytest.fixture(scope="session")
def ensure_backend(backend_url):
    """session 级 fixture：确保后端服务器就绪（必需）。

    - 检查后端是否运行，未运行则 start_backend_subprocess 并 wait_for
    - 记录哪些子进程是自己启动的
    - teardown 时终止自己启动的子进程
    """
    started_procs: list = []

    # 后端
    if not is_backend_up(backend_url):
        proc = start_backend_subprocess()
        started_procs.append(proc)
        wait_for(
            lambda: is_backend_up(backend_url),
            timeout=60,
            interval=1,
            description="后端启动",
        )

    yield

    # teardown：终止自己启动的子进程
    for proc in started_procs:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            pass


@pytest.fixture(scope="session")
def ensure_frontend(ensure_backend, frontend_url):
    """session 级 fixture：确保前端服务器就绪（仅前端冒烟测试需要）。

    - 检查前端是否运行，未运行则尝试 start_frontend_subprocess 并 wait_for
    - 前端启动失败时打印告警但不抛异常（后端 E2E 测试不依赖前端）
    - 记录哪些子进程是自己启动的
    - teardown 时终止自己启动的子进程
    """
    started_procs: list = []

    # 前端
    if not is_frontend_up(frontend_url):
        try:
            proc = start_frontend_subprocess()
            started_procs.append(proc)
            wait_for(
                lambda: is_frontend_up(frontend_url),
                timeout=90,
                interval=1,
                description="前端启动",
            )
        except Exception as exc:
            print(f"[ensure_frontend] 前端启动失败（不影响后端 E2E 测试）: {exc}")

    yield

    # teardown：终止自己启动的子进程
    for proc in started_procs:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            pass


@pytest.fixture(scope="session")
def ensure_servers(ensure_backend, frontend_url):
    """session 级 fixture：确保前后端服务器就绪（兼容旧引用）。

    后端为必需，前端为 best-effort（失败不阻塞后端 E2E 测试）。
    """
    # 前端 best-effort 启动
    if not is_frontend_up(frontend_url):
        try:
            proc = start_frontend_subprocess()
            wait_for(
                lambda: is_frontend_up(frontend_url),
                timeout=90,
                interval=1,
                description="前端启动",
            )
            _frontend_procs.append(proc)
        except Exception as exc:
            print(f"[ensure_servers] 前端启动失败（不影响后端 E2E 测试）: {exc}")
    yield
    # teardown：终止前端子进程
    for proc in _frontend_procs:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            pass
    _frontend_procs.clear()


# ================================================================
# 登录与 API 客户端
# ================================================================

@pytest.fixture(scope="session")
def auth_token(ensure_backend, backend_url):
    """用 E2E 账号登录（env LINGSHU_E2E_USER/LINGSHU_E2E_PASS，未设置时自动运行种子脚本），返回 access_token。

    登录失败抛异常终止整个 session。
    仅依赖后端服务器（ensure_backend），不依赖前端。
    """
    token, _user = login(backend_url)
    if not token:
        raise RuntimeError("登录失败：access_token 为空，终止 session")
    return token


@pytest.fixture(scope="session")
def api_client(auth_token, backend_url):
    """返回 ApiClient(backend_url, auth_token)。"""
    return ApiClient(backend_url, auth_token)


# ================================================================
# 测试书籍
# ================================================================

@pytest.fixture(scope="session")
def e2e_book_id(api_client):
    """session 级 fixture：创建测试书籍，teardown 时清理。"""
    book = api_client.create_book(f"{E2E_BOOK_PREFIX}{int(time.time())}")
    book_id = int(book.get("id") or 0)
    if book_id <= 0:
        raise RuntimeError(f"测试书籍创建失败：{book}")
    yield book_id
    # teardown：清理所有 E2E 书籍
    try:
        cleanup_e2e_books(api_client)
    except Exception as exc:
        print(f"[e2e_book_id teardown] cleanup_e2e_books 异常: {exc}")


# ================================================================
# V3 分析运行
# ================================================================

@pytest.fixture(scope="session")
def e2e_run_id(api_client, e2e_book_id):
    """session 级 fixture：写入测试章节并触发 V3 分析，轮询直至完成。

    yield run_id（从 list_analysis_v3_runs 取最新一条的 id）。
    """
    # 写入测试章节（复用 tests/fixtures/test_novel.py 的 CHAPTERS）
    from tests.fixtures.test_novel import CHAPTERS

    for chapter in CHAPTERS:
        ch = api_client.create_chapter(e2e_book_id, chapter["title"])
        chapter_id = int(ch.get("id") or 0)
        if chapter_id <= 0:
            raise RuntimeError(f"章节创建失败：{ch}")
        api_client.update_chapter(chapter_id, content=chapter["content"])

    # 触发 V3 分析
    api_client.create_analysis_v3_run(e2e_book_id, use_ai=False, execute_l1=True)

    # 轮询直至完成
    wait_for(
        lambda: api_client.list_analysis_v3_runs(e2e_book_id)[0]["status"]
        in ("completed", "probes_ready"),
        timeout=180,
        interval=3,
        description="V3 分析完成",
    )

    runs = api_client.list_analysis_v3_runs(e2e_book_id)
    if not runs:
        raise RuntimeError("V3 分析完成后 list_analysis_v3_runs 返回空列表")
    run_id = int(runs[0].get("id") or 0)
    if run_id <= 0:
        raise RuntimeError(f"V3 分析运行 id 无效：{runs[0]}")
    yield run_id
