"""
灵枢统一 FastAPI 应用入口。

启动方式:
    uvicorn lingshu_api.main:app --host 0.0.0.0 --port 8787
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

# 确保项目根目录在 sys.path 中（开发环境）
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


DEFAULT_DB_PATH = _project_root / "data" / "bookstore_demo.db"


def create_app(db_path: Path | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    # 配置日志：让 novel_app 和 lingshu_api 的 INFO 级别日志输出到 stdout
    # 解决 run_aimd_pool 的进度日志被静默丢弃的问题
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
    # 显式设置 novel_app 和 lingshu_api 的 logger 级别为 INFO
    for name in ("novel_app", "lingshu_api"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)

    from lingshu_api.dependencies import set_cloud_store, set_store, set_sync_service
    from lingshu_api.routers import admin, admin_auth, auth, bookshelf, bookstore, workspace
    from lingshu_api.services.book_sync import BookSyncService
    from lingshu_api.services.db_bridge import WorkspaceDBProvider
    from novel_app.bookstore import BookstoreStore, CloudBookStore, _admin_usernames_from_env

    resolved_db_path = db_path or Path(os.environ.get("BOOKSTORE_DB_PATH", "") or DEFAULT_DB_PATH)
    store = BookstoreStore(resolved_db_path)
    store.sync_admin_users(_admin_usernames_from_env())

    cloud_store = CloudBookStore(resolved_db_path)

    class _NonClosingWorkspaceDB:
        def __init__(self, target):
            self._target = target

        def __getattr__(self, name):
            return getattr(self._target, name)

        def close(self):
            return None

    workspace_provider = WorkspaceDBProvider()

    sync_service = BookSyncService(
        cloud_store=cloud_store,
        workspace_db_factory=lambda: _NonClosingWorkspaceDB(workspace_provider.get()),
    )

    # lifespan 替代已废弃的 on_event
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # startup: 启动 WebSocket 心跳 + 清理过期管理员 Token + WAL checkpoint
        from lingshu_api.ws.connection import get_ws_manager
        ping_task = asyncio.create_task(get_ws_manager().ping_loop())
        try:
            from lingshu_api.routers.admin_auth import _get_db_path, cleanup_on_startup
            cleanup_on_startup(_get_db_path(store))
        except Exception:
            pass
        # 启动时执行 WAL checkpoint，清理上次运行遗留的 WAL 数据
        try:
            workspace_provider.get().db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        # 定期 WAL checkpoint，防止 WAL 膨胀拖慢写入操作
        async def _wal_checkpoint_loop():
            while True:
                await asyncio.sleep(300)  # 每 5 分钟执行一次
                try:
                    workspace_provider.get().db.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    pass
        wal_task = asyncio.create_task(_wal_checkpoint_loop())
        yield
        # shutdown: 取消后台任务
        ping_task.cancel()
        wal_task.cancel()
        with suppress(asyncio.CancelledError):
            await ping_task
            await wal_task
        workspace_provider.close()

    _disable_docs = os.environ.get("DISABLE_API_DOCS", "true").lower() in ("true", "1", "yes")
    app = FastAPI(
        title="灵枢 API",
        lifespan=lifespan,
        docs_url=None if _disable_docs else "/docs",
        redoc_url=None if _disable_docs else "/redoc",
        openapi_url=None if _disable_docs else "/openapi.json",
    )

    # 将 store / cloud_store / sync_service 写入 app.state
    set_store(app, store)
    set_cloud_store(app, cloud_store)
    set_sync_service(app, sync_service)
    app.state.workspace_db_provider = workspace_provider

    # 限流
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request, exc):
        return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})

    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request, exc):
        errors = [
            {
                "field": ".".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": "请求参数验证失败", "errors": errors},
        )

    @app.exception_handler(Exception)
    async def _generic_exception_handler(request, exc):
        logger = logging.getLogger("lingshu.api")
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误，请稍后重试"},
        )

    # CORS — 生产环境必须通过 CORS_ORIGINS 环境变量配置允许的源
    _cors_env = os.environ.get("CORS_ORIGINS", "").strip()
    if _cors_env:
        allow_origins = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]
    else:
        # 开发环境默认值 — 仅允许已知端口
        allow_origins = [
            "http://127.0.0.1:5173", "http://localhost:5173",
            "http://127.0.0.1:5174", "http://localhost:5174",
            "http://127.0.0.1:5175", "http://localhost:5175",
            "http://127.0.0.1:5176", "http://localhost:5176",
            "https://www.ling-shu.top", "https://ling-shu.top",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Publish-Token",
            "X-Client-KeyId",
            "X-Client-Ts",
            "X-Client-Sig",
        ],
    )

    # 安全响应头中间件
    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # CSP 仅对页面资源有意义，对 /api/ JSON 响应反而会触发浏览器跨域误判（net::ERR_FAILED）
        path = request.scope.get("path", "")
        if not (path or "").startswith("/api/"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self' ws: wss:;"
        return response

    @app.middleware("http")
    async def _admin_hmac_guard(request, call_next):
        path = request.url.path
        # 同时保护 /api/admin/ 和 /api/v1/admin/ 路径
        is_admin_path = (
            path.startswith("/api/admin/") or path.startswith("/api/v1/admin/")
        )
        is_login = path in ("/api/admin/auth/login", "/api/v1/admin/auth/login")
        if is_admin_path and not is_login:
            from fastapi import HTTPException

            from lingshu_api.routers.admin_auth import _admin_keys_configured, verify_admin_hmac_headers

            if not _admin_keys_configured(resolved_db_path):
                return JSONResponse(
                    status_code=503,
                    content={"detail": "管理后台未配置安全密钥，请联系管理员配置 HMAC 密钥后重试"},
                )

            try:
                verify_admin_hmac_headers(resolved_db_path, request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.middleware("http")
    async def _api_v1_alias(request, call_next):
        path = str(request.scope.get("path") or "")
        if path.startswith("/api/v1/"):
            request.scope["lingshu.original_path"] = path
            aliased = "/api/" + path.removeprefix("/api/v1/")
            request.scope["path"] = aliased
            request.scope["raw_path"] = aliased.encode("ascii")
        return await call_next(request)

    # API 版本说明:
    # 当前所有 /api/ 路由即为 v1 版本
    # 未来 v2 路由将挂载在 /api/v2/ 前缀下
    # 客户端可通过 /api/v1/ 前缀访问（与 /api/ 等价）
    api_version = "v1"

    # 挂载 REST 路由（/api/ 前缀 — 向后兼容）
    app.include_router(auth.router)
    app.include_router(bookshelf.router)
    app.include_router(bookstore.router)
    app.include_router(admin_auth.router)
    app.include_router(admin.router)
    app.include_router(workspace.router)

    # 挂载阶段2新增路由
    from lingshu_api.routers import (
        analysis_v3,
        characters,
        rag,
        references,
        settings,
        skills,
    )
    from lingshu_api.routers import (
        export as export_router,
    )
    from lingshu_api.routers import (
        world as world_router,
    )
    app.include_router(analysis_v3.router)
    app.include_router(characters.router)
    app.include_router(world_router.router)
    app.include_router(skills.router)
    app.include_router(references.router)
    app.include_router(rag.router)
    app.include_router(export_router.router)
    app.include_router(settings.router)

    # 挂载伏笔管理路由
    from lingshu_api.routers import foreshadows
    app.include_router(foreshadows.router)

    # 挂载网文写作技巧集路由
    from lingshu_api.routers import writing_techniques
    app.include_router(writing_techniques.router)

    # 挂载云端同步路由
    from lingshu_api.routers import cloud_books
    app.include_router(cloud_books.router)

    # 挂载社区卡片路由
    from lingshu_api.routers import community
    app.include_router(community.router)

    # 挂载 WebSocket 路由
    from lingshu_api.ws import analysis_v3_ws, chat, generation, review_ws
    app.include_router(generation.router)
    app.include_router(review_ws.router)
    app.include_router(analysis_v3_ws.router)
    app.include_router(chat.router)

    @app.get("/api/health")
    def health():
        from novel_app.db.redis_client import ping_redis
        return {"ok": True, "version": api_version, "redis": ping_redis()}

    @app.get("/api/v1/health")
    def health_v1():
        from novel_app.db.redis_client import ping_redis
        return {"ok": True, "version": api_version, "redis": ping_redis()}

    return app


# 模块级 app 实例（兼容 uvicorn 直接导入）
app = create_app()
