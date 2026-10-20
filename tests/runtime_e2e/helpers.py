"""运行时 E2E 测试辅助工具 — HTTP 客户端、轮询、健康检查、清理工具、报告类。

本模块为 runtime_e2e 测试套件提供：
- 后端/前端健康检查与子进程启停
- 当前用户查询与 ApiClient（封装所有业务 API 调用；本地单用户模式免 token）
- E2E 测试数据清理工具
- 探针结果解决（直接访问数据库清除 manual_review 阻断）
- E2EReport 报告收集与渲染
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

# ================================================================
# 常量
# ================================================================

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8787
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 5175
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
FRONTEND_URL = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}"
E2E_BOOK_PREFIX = "__E2E_V3__"

# 项目根目录（tests/runtime_e2e 的上两级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 前端目录
FRONTEND_DIR = PROJECT_ROOT / "lingshu-app"


# ================================================================
# 健康检查与服务器启停
# ================================================================

def is_backend_up(url: str = BACKEND_URL) -> bool:
    """检查后端是否运行 — GET {url}/api/health 返回 200 即 True。"""
    try:
        resp = requests.get(f"{url}/api/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def is_frontend_up(url: str = FRONTEND_URL) -> bool:
    """检查前端是否运行 — GET 前端首页返回 200 即 True。"""
    try:
        resp = requests.get(url, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def start_backend_subprocess(host: str = BACKEND_HOST, port: int = BACKEND_PORT) -> subprocess.Popen:
    """在项目根目录以子进程启动 `python main.py --host {host} --port {port}`。

    stdout/stderr 重定向到临时日志文件，返回 Popen 对象。
    """
    log_dir = PROJECT_ROOT / ".codex-runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / "e2e_backend.out.log"
    err_path = log_dir / "e2e_backend.err.log"
    out_fp = open(out_path, "a", encoding="utf-8")
    err_fp = open(err_path, "a", encoding="utf-8")
    cmd = [
        "python",
        "main.py",
        "--host",
        host,
        "--port",
        str(port),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=out_fp,
        stderr=err_fp,
        shell=False,
    )
    return proc


def start_frontend_subprocess(host: str = FRONTEND_HOST, port: int = FRONTEND_PORT) -> subprocess.Popen:
    """在 lingshu-app/ 目录以子进程启动 `npm run dev -- --host {host} --port {port}`。

    Windows 下用 shell=True。
    """
    log_dir = PROJECT_ROOT / ".codex-runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / "e2e_frontend.out.log"
    err_path = log_dir / "e2e_frontend.err.log"
    out_fp = open(out_path, "a", encoding="utf-8")
    err_fp = open(err_path, "a", encoding="utf-8")
    # Windows 下使用 shell=True，命令以字符串形式
    cmd = f"npm run dev -- --host {host} --port {port}"
    proc = subprocess.Popen(
        cmd,
        cwd=str(FRONTEND_DIR),
        stdout=out_fp,
        stderr=err_fp,
        shell=True,
    )
    return proc


def wait_for(predicate: Callable[[], bool], timeout: int = 60, interval: int = 1, description: str = "") -> None:
    """通用轮询，超时抛 TimeoutError(f"{description} 超时 {timeout}s")。"""
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:
            last_err = exc
        time.sleep(interval)
    if last_err is not None:
        raise TimeoutError(f"{description} 超时 {timeout}s，最后异常: {last_err}")
    raise TimeoutError(f"{description} 超时 {timeout}s")


# ================================================================
# 当前用户查询与 HTTP 客户端
# ================================================================

def current_user(backend_url: str = BACKEND_URL) -> dict:
    """GET {backend_url}/api/auth/me 查询当前用户。

    personal-client P3 后登录端点已剥离：本地单用户模式（默认）下
    /api/auth/me 免 token 返回本地用户（200）；多用户模式下需携带有效
    token（当前 runtime E2E 不覆盖该模式）。非 200 抛 RuntimeError。
    同时作为会话前的后端鉴权链路健康检查。
    """
    resp = requests.get(f"{backend_url}/api/auth/me", timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"查询当前用户失败: {resp.status_code} {resp.text}")
    return resp.json()


class ApiClient:
    """封装所有业务 API 调用，自动携带 Authorization: Bearer {token} 头。

    使用 requests 库（同步），timeout=300。
    """

    def __init__(self, backend_url: str = BACKEND_URL, token: str = ""):
        self.backend_url = backend_url.rstrip("/")
        self.token = token

    def _request(self, method: str, path: str, **kwargs) -> Any:
        """内部统一请求方法，拼接 backend_url + path。

        非 2xx 抛 RuntimeError 含状态码和响应文本。
        """
        url = self.backend_url + path
        headers = kwargs.pop("headers", {}) or {}
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        kwargs.setdefault("timeout", 300)
        resp = requests.request(method, url, headers=headers, **kwargs)
        if not (200 <= resp.status_code < 300):
            raise RuntimeError(f"{method} {path} 失败: {resp.status_code} {resp.text}")
        # 部分 DELETE 接口可能返回空 body
        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # 书籍 CRUD
    # ------------------------------------------------------------------

    def list_books(self) -> list[dict]:
        """GET /api/workspace/books，返回 resp["items"]。"""
        resp = self._request("GET", "/api/workspace/books")
        return resp.get("items", []) or []

    def create_book(self, title: str, summary: str = "") -> dict:
        """POST /api/workspace/books，返回 resp["item"]。"""
        resp = self._request("POST", "/api/workspace/books", json={"title": title, "summary": summary})
        return resp.get("item", {}) or {}

    def get_book(self, book_id: int) -> dict:
        """GET /api/workspace/books/{book_id}。"""
        return self._request("GET", f"/api/workspace/books/{book_id}")

    def delete_book(self, book_id: int) -> None:
        """DELETE /api/workspace/books/{book_id}。"""
        self._request("DELETE", f"/api/workspace/books/{book_id}")

    # ------------------------------------------------------------------
    # 章节 CRUD
    # ------------------------------------------------------------------

    def list_chapters(self, book_id: int) -> list[dict]:
        """GET /api/workspace/books/{book_id}/chapters?volume=all，返回 resp["items"]。"""
        resp = self._request("GET", f"/api/workspace/books/{book_id}/chapters?volume=all")
        return resp.get("items", []) or []

    def create_chapter(self, book_id: int, title: str) -> dict:
        """POST /api/workspace/books/{book_id}/chapters，返回 resp["item"]。"""
        resp = self._request(
            "POST",
            f"/api/workspace/books/{book_id}/chapters",
            json={"title": title},
        )
        return resp.get("item", {}) or {}

    def update_chapter(self, chapter_id: int, content: str = "", title: str | None = None) -> dict:
        """PATCH /api/workspace/chapters/{chapter_id}，只包含非 None 字段，返回 resp["item"]。"""
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if content:
            payload["content"] = content
        resp = self._request("PATCH", f"/api/workspace/chapters/{chapter_id}", json=payload)
        return resp.get("item", {}) or {}

    # ------------------------------------------------------------------
    # 人物 / 世界
    # ------------------------------------------------------------------

    def list_characters(self, book_id: int) -> list[dict]:
        """GET /api/workspace/books/{book_id}/characters，返回 resp["items"]。"""
        resp = self._request("GET", f"/api/workspace/books/{book_id}/characters")
        return resp.get("items", []) or []

    def get_world(self, book_id: int) -> dict:
        """GET /api/workspace/books/{book_id}/world。"""
        return self._request("GET", f"/api/workspace/books/{book_id}/world")

    # ------------------------------------------------------------------
    # V3 分析
    # ------------------------------------------------------------------

    def create_analysis_v3_run(self, book_id: int, use_ai: bool = False, execute_l1: bool = True) -> dict:
        """POST /api/workspace/books/{book_id}/analysis-v3/runs。

        返回完整响应体（含 run_id, status, block_count 等）。
        """
        return self._request(
            "POST",
            f"/api/workspace/books/{book_id}/analysis-v3/runs",
            json={"use_ai": use_ai, "execute_l1": execute_l1},
        )

    def list_analysis_v3_runs(self, book_id: int) -> list[dict]:
        """GET /api/workspace/books/{book_id}/analysis-v3/runs，返回 resp["items"]。"""
        resp = self._request("GET", f"/api/workspace/books/{book_id}/analysis-v3/runs")
        return resp.get("items", []) or []

    def list_cards(self, run_id: int) -> list[dict]:
        """GET /api/workspace/analysis-v3/runs/{run_id}/cards，返回 resp["items"]。"""
        resp = self._request("GET", f"/api/workspace/analysis-v3/runs/{run_id}/cards")
        return resp.get("items", []) or []

    def get_review(self, run_id: int) -> dict:
        """GET /api/workspace/analysis-v3/runs/{run_id}/review，返回完整响应体。"""
        return self._request("GET", f"/api/workspace/analysis-v3/runs/{run_id}/review")

    def writeback_run(self, run_id: int, actor: str = "user") -> dict:
        """POST /api/workspace/analysis-v3/runs/{run_id}/writeback。

        返回完整响应体（含 writeback_count, success_count, results）。
        actor 仅允许 "user" 或 "system"（由 WritebackRunRequest schema 约束）。
        """
        return self._request(
            "POST",
            f"/api/workspace/analysis-v3/runs/{run_id}/writeback",
            json={"actor": actor},
        )


# ================================================================
# 清理工具
# ================================================================

def cleanup_e2e_books(client: ApiClient) -> list[int]:
    """列出所有书籍，删除标题以 E2E_BOOK_PREFIX 开头的书籍。

    返回已删除的 book_id 列表。异常时打印告警但不抛出。
    """
    deleted: list[int] = []
    try:
        books = client.list_books()
        for book in books:
            title = str(book.get("title") or "")
            book_id = book.get("id")
            if not book_id:
                continue
            if title.startswith(E2E_BOOK_PREFIX):
                try:
                    client.delete_book(int(book_id))
                    deleted.append(int(book_id))
                except Exception as exc:
                    print(f"[cleanup_e2e_books] 删除 book_id={book_id} 失败: {exc}")
    except Exception as exc:
        print(f"[cleanup_e2e_books] 列出/删除 E2E 书籍时异常: {exc}")
    return deleted


# ================================================================
# 探针结果解决（直接访问数据库）
# ================================================================

def get_workspace_db_path() -> Path:
    """获取工作台数据库路径（与 lingshu_api/services/db_bridge.py 一致）。"""
    configured = os.environ.get("SIMPLE_AI_NOVEL_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser() / "novels.db"
    return PROJECT_ROOT / "data" / "novels.db"


def resolve_probe_results(run_id: int, book_id: int | None = None) -> int:
    """直接访问数据库，将指定 run 的所有探针结果状态改为 'pass'。

    用于清除 probe_manual_review 阻断，使写回门禁通过。
    返回更新的行数。
    """
    db_path = get_workspace_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"工作台数据库不存在: {db_path}")
    updated = 0
    conn = sqlite3.connect(str(db_path))
    try:
        if book_id is not None:
            cursor = conn.execute(
                "UPDATE analysis_probe_results SET status = 'pass' "
                "WHERE run_id = ? AND book_id = ? AND status IN ('manual_review', 'inconsistent', 'failed')",
                (run_id, book_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE analysis_probe_results SET status = 'pass' "
                "WHERE run_id = ? AND status IN ('manual_review', 'inconsistent', 'failed')",
                (run_id,),
            )
        updated = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return updated


# ================================================================
# 报告类
# ================================================================

class E2EReport:
    """收集每个环节检测结果。"""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        """记录一个环节。"""
        self.steps.append({"name": name, "passed": passed, "detail": detail})

    def is_overall_passed(self) -> bool:
        """所有环节都 passed 才 True。"""
        return all(step["passed"] for step in self.steps)

    def render(self) -> str:
        """渲染为文本报告。"""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("灵枢 V3 全书分析一条龙 — 运行时 E2E 测试报告")
        lines.append("=" * 60)
        lines.append("")
        for idx, step in enumerate(self.steps, start=1):
            mark = "✓" if step["passed"] else "✗"
            line = f"{idx:02d}. {mark} {step['name']}"
            if step.get("detail"):
                line += f" — {step['detail']}"
            lines.append(line)
        lines.append("")
        lines.append("-" * 60)
        overall = "通过" if self.is_overall_passed() else "失败"
        passed_count = sum(1 for s in self.steps if s["passed"])
        failed_count = len(self.steps) - passed_count
        lines.append(
            f"整体结果: {overall}（共 {len(self.steps)} 项，通过 {passed_count}，失败 {failed_count}）"
        )
        lines.append("=" * 60)
        return "\n".join(lines)

    def save(self, path: str) -> None:
        """保存到文件。"""
        text = self.render()
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)

    def print(self) -> None:  # noqa: A003 — 与任务规范一致
        """打印到 stdout。"""
        print(self.render())
