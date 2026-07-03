"""
灵枢 v2.0 — FastAPI 后端入口（已从 PyQt6 迁移至 Vue3 + Electron）

启动方式:
    python main.py                              # 默认启动 API 服务
    python main.py --electron                   # 在 Electron 壳中启动
    python -m uvicorn lingshu_api.main:app      # 直接启动 API

环境变量:
    LINGSHU_AI_API_KEY       AI API 密钥
    LINGSHU_AI_BASE_URL      AI API 地址（默认 https://api.openai.com/v1）
    LINGSHU_AI_MODEL         AI 模型（默认 gpt-4o-mini）
    BOOKSTORE_DB_PATH        书城数据库路径
    BOOKSTORE_PUBLISH_TOKEN  发布令牌
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 确保项目在路径中
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

APP_ICON = BASE_DIR / "packaging" / "app_icon.ico"


def start_api_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    """启动 FastAPI 后端服务。"""
    import uvicorn
    print(f"[灵枢] 启动 API 服务: http://{host}:{port}")
    print(f"[灵枢] API 文档: http://{host}:{port}/docs")
    uvicorn.run(
        "lingshu_api.main:app",
        host=host,
        port=port,
        log_level="info",
    )


def check_backend_health(host: str = "127.0.0.1", port: int = 8787) -> bool:
    """检查后端是否已在运行。"""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2)
        return True
    except Exception:
        return False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="灵枢 v2.0 — 智能写作工作台")
    parser.add_argument("--host", default="127.0.0.1", help="绑定地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="绑定端口 (默认 8787)")
    parser.add_argument("--dev", action="store_true", help="开发模式（不检查端口占用）")
    args = parser.parse_args()

    if not args.dev and check_backend_health(args.host, args.port):
        print(f"[灵枢] API 服务已在 http://{args.host}:{args.port} 运行")
        print(f"[灵枢] 无需重复启动，按 Ctrl+C 退出")
        return

    start_api_server(args.host, args.port)


if __name__ == "__main__":
    main()
