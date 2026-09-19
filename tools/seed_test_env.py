"""E2E 种子脚本 — 在独立数据目录创建测试账号与示例书（幂等，可直接重复运行）。

用途：
- 供 `tests/runtime_e2e`（HTTP 直连）与 Playwright E2E（tests/e2e）使用；
- 替代过去依赖的硬编码账号 `001/12345678a`。

数据隔离（绝不碰生产 novels.db / bookstore_demo.db）：
- `LINGSHU_E2E_DB`        种子数据目录，默认 `<项目根>/data/e2e_seed`；
  其中会创建独立的 `bookstore_demo.db`（bookstore 用户库）与
  `novels.db`（workspace 书籍库），与双库结构一一对应。
- 若环境已设置 `SIMPLE_AI_NOVEL_DATA_DIR` / `BOOKSTORE_DB_PATH`
  （例如 Playwright webServer 注入），种子脚本沿用同一目录，保证
  与后续启动的后端使用同一套库与密码盐。

账号：
- `LINGSHU_E2E_USER`（默认 e2e_writer）、`LINGSHU_E2E_PASS`（默认 e2e_pass_123）。

注册走 auth 路由同款服务层调用：`BookstoreStore.create_user()`（users 表），
再用 `WorkspaceDB`（novels.db）创建示例书与章节，与
`lingshu_api/routers/auth.py::register` 的写库路径保持一致。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------
# 1. 环境变量解析（必须在导入 novel_app/lingshu_api 之前完成：
#    password pepper/salt 等模块级常量在 import 时读取环境变量）
# ---------------------------------------------------------------

DEFAULT_USER = "e2e_writer"
DEFAULT_PASS = "e2e_pass_123"
DEFAULT_DB_DIR = PROJECT_ROOT / "data" / "e2e_seed"

SEED_BOOK_TITLE = "E2E 种子示例书"
SEED_CHAPTER_TITLE = "第一章 种子"
SEED_CHAPTER_CONTENT = (
    "这是 E2E 种子脚本创建的示例章节。\n\n"
    "用于验证工作台的登录、建书、写章与保存链路。\n"
    "内容可以随意修改，种子脚本不会覆盖已有数据。"
)


def _resolve_seed_dir() -> Path:
    """确定种子数据目录：LINGSHU_E2E_DB > 后端 env 推导 > 默认独立目录。"""
    explicit = os.environ.get("LINGSHU_E2E_DB", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    data_dir = os.environ.get("SIMPLE_AI_NOVEL_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser().resolve()

    bookstore_db = os.environ.get("BOOKSTORE_DB_PATH", "").strip()
    if bookstore_db:
        return Path(bookstore_db).expanduser().resolve().parent

    return DEFAULT_DB_DIR


def _resolve_credentials() -> tuple[str, str]:
    username = os.environ.get("LINGSHU_E2E_USER", "").strip() or DEFAULT_USER
    password = os.environ.get("LINGSHU_E2E_PASS", "").strip() or DEFAULT_PASS
    return username, password


def main() -> int:
    seed_dir = _resolve_seed_dir()
    username, password = _resolve_credentials()

    seed_dir.mkdir(parents=True, exist_ok=True)
    bookstore_db = seed_dir / "bookstore_demo.db"
    novels_db = seed_dir / "novels.db"

    # 与后端进程保持同一套库路径（导入前设置，供 pepper/salt 派生与 DB 定位）
    os.environ["SIMPLE_AI_NOVEL_DATA_DIR"] = str(seed_dir)
    os.environ["BOOKSTORE_DB_PATH"] = str(bookstore_db)

    # 延迟导入：等环境变量就绪后再加载服务层
    import sys as _sys

    if str(PROJECT_ROOT) not in _sys.path:
        _sys.path.insert(0, str(PROJECT_ROOT))

    from lingshu_api.services.db_bridge import WorkspaceDB
    from novel_app.bookstore import BookstoreStore
    from novel_app.bookstore.models import _connect

    # ---- bookstore 用户库：注册同款 create_user ----
    store = BookstoreStore(bookstore_db)
    try:
        user = store.create_user(username, password, is_author=1)
        action = "created"
    except HTTPException as exc:
        if exc.status_code != 409:
            print(f"[seed][ERROR] 用户 {username} 创建失败: {exc.detail}")
            return 1
        # 幂等：账号已存在则直接复用（防用户名枚举逻辑不影响服务层直调）
        with _connect(bookstore_db) as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            print(f"[seed][ERROR] 用户 {username} 创建失败且未找到: {exc.detail}")
            return 1
        user = {"id": int(row["id"]), "username": username}
        action = "exists"
    user_id = int(user["id"])

    # ---- workspace 书籍库（novels.db）：示例书 + 章节（幂等） ----
    workspace = WorkspaceDB(novels_db)
    book_action = "exists"
    book_id: int | None = None
    for book in workspace.list_books(user_id=user_id):
        if str(book.get("title") or "") == SEED_BOOK_TITLE:
            book_id = int(book["id"])
            break
    if book_id is None:
        book = workspace.create_book(SEED_BOOK_TITLE, user_id=user_id)
        book_id = int(book["id"])
        chapter = workspace.create_chapter(book_id, SEED_CHAPTER_TITLE)
        workspace.update_chapter(int(chapter["id"]), content=SEED_CHAPTER_CONTENT)
        book_action = "created"

    # ---- 校验登录凭据可用 ----
    token = store.login_user(username, password)
    if not token:
        print(f"[seed][ERROR] 账号 {username} 登录校验失败（密码不一致且账号已存在）")
        print("[seed][HINT] 如需重置密码，删除种子目录后重跑本脚本。")
        return 1

    print("[seed] done")
    print(f"[seed] user        : {username} (id={user_id}, {action})")
    print(f"[seed] sample_book : 《{SEED_BOOK_TITLE}》 id={book_id} ({book_action})")
    print(f"[seed] bookstore_db: {bookstore_db}")
    print(f"[seed] novels_db   : {novels_db}")
    print("[seed] login_check : ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
