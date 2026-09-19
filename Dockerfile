# ============================================================
# 灵枢后端镜像 — FastAPI (lingshu_api) + uvicorn
# 替代旧部署方式（deploy_admin_auth.sh sed 原地改服务器 main.py，
# 已移入 _attic/legacy-deploy/）。
#
# 注意：本文件未经过实际 docker build 验证（抢救方案阶段 4.2），
# 首次部署时需试跑，命令清单见仓库 CONTRIBUTING/README 或：
#   docker build -t lingshu-backend .
#   docker compose up -d backend
# ============================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 依赖层单独拷贝，利用 Docker 缓存；requirements.lock 为精确 pin
# （faiss-cpu/lxml/cryptography/hiredis 均有 manylinux wheel，
#  python:3.11-slim 无需额外编译工具链；如某依赖需源码编译，
#  在此处补 apt-get install build-essential 后重试）
COPY requirements.lock ./requirements.lock
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.lock

# 运行时代码：lingshu_api 依赖 novel_app 与 shared（top-level import 仅此三者）
COPY lingshu_api ./lingshu_api
COPY novel_app ./novel_app
COPY shared ./shared

# SQLite 数据库落在 /app/data（lingshu_api/main.py DEFAULT_DB_PATH）
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8787

# 健康端点：GET /api/health（lingshu_api/main.py）
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "lingshu_api.main:app", "--host", "0.0.0.0", "--port", "8787"]
