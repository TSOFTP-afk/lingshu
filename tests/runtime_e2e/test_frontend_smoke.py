"""前端冒烟测试 — 使用 Playwright 验证本地模式免登录进入工作台后能看到 V3 分析运行和写回结果。

依赖 session 级 fixtures：ensure_frontend, e2e_book_id, e2e_run_id（来自 conftest.py）。
Playwright 未安装时整体跳过。

personal-client P3：登录 UI（LoginDialog）与 /api/auth/login 已剥离，
前端以本地单用户模式免登录直达工作台。
"""
from __future__ import annotations

import pytest

from .helpers import E2E_BOOK_PREFIX, FRONTEND_URL, is_frontend_up

# ================================================================
# Playwright 可用性检测
# ================================================================
try:
    from playwright.sync_api import BrowserContext, Page, sync_playwright  # noqa: F401

    pytestmark = pytest.mark.runtime_e2e
except ImportError:
    # Playwright 未安装时跳过整个模块
    pytestmark = [
        pytest.mark.runtime_e2e,
        pytest.mark.skip(reason="Playwright 未安装，跳过前端冒烟测试"),
    ]


# ================================================================
# fixture: playwright_page
# ================================================================

@pytest.fixture(scope="session")
def playwright_page(ensure_frontend):
    """session 级 fixture：启动 Playwright chromium 浏览器并导航到前端首页。

    - 依赖 ensure_frontend 确保前端就绪
    - 前端不可达时 pytest.skip
    - headless 模式启动 chromium
    - yield page 供测试用例使用
    - teardown 关闭浏览器
    """
    if not is_frontend_up(FRONTEND_URL):
        pytest.skip("前端服务器不可达")

    pw = None
    browser = None
    page = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=15000)
        yield page
    finally:
        try:
            if page is not None:
                page.close()
        except Exception as exc:
            print(f"[playwright_page teardown] 关闭 page 失败: {exc}")
        try:
            if browser is not None:
                browser.close()
        except Exception as exc:
            print(f"[playwright_page teardown] 关闭 browser 失败: {exc}")
        try:
            if pw is not None:
                pw.stop()
        except Exception as exc:
            print(f"[playwright_page teardown] 停止 playwright 失败: {exc}")


# ================================================================
# 测试用例
# ================================================================

def test_frontend_opens_workspace(playwright_page):
    """本地模式免登录打开工作台。"""
    page = playwright_page
    try:
        # 本地单用户模式下前端 init 经 /api/auth/me 拿到本地用户，直达工作台
        page.wait_for_url("**/workspace**", timeout=10000)
    except Exception as exc:
        raise AssertionError(f"前端未能免登录进入工作台: {exc}") from exc


def test_frontend_find_e2e_book(playwright_page, e2e_book_id):
    """在书籍列表中找到 __E2E_V3__ 测试书籍。"""
    page = playwright_page
    try:
        # 确保在工作台页面
        page.wait_for_url("**/workspace**", timeout=5000)
        # 等待书籍列表加载
        page.wait_for_selector(f"text={E2E_BOOK_PREFIX}", timeout=10000)
    except Exception as exc:
        raise AssertionError(f"在书籍列表中未找到 E2E 测试书籍: {exc}") from exc


def test_frontend_analysis_panel(playwright_page, e2e_book_id):
    """打开分析 Tab，验证能看到 V3 运行记录。"""
    page = playwright_page
    try:
        # 点击测试书籍
        page.click(f"text={E2E_BOOK_PREFIX}")
        # 点击分析 Tab
        page.get_by_role("tab", name="分析").click()
        # 验证能看到分析运行记录
        page.wait_for_selector("text=analysis_v3", timeout=10000)
    except Exception as exc:
        raise AssertionError(f"打开分析 Tab 或验证 V3 运行记录失败: {exc}") from exc
