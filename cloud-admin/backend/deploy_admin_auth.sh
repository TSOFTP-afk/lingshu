#!/bin/bash
# 部署管理员独立认证模块到服务器
set -e

APP_DIR="/home/CODEX/lingshu-cloud/app"
AUTH_FILE="$APP_DIR/lingshu_api/routers/admin_auth.py"

# 1. 复制 admin_auth.py
cp /home/CODEX/lingshu-cloud/tmp/admin_auth.py "$AUTH_FILE"
echo "Copied admin_auth.py"

# 2. 在 main.py 中注册路由（如果尚未注册）
if grep -q "admin_auth" "$APP_DIR/lingshu_api/main.py"; then
    echo "admin_auth router already registered"
else
    # 在 admin router 导入之后添加 admin_auth
    sed -i 's/from lingshu_api.routers import auth, bookshelf, bookstore, admin, workspace/from lingshu_api.routers import auth, bookshelf, bookstore, admin, admin_auth, workspace/' "$APP_DIR/lingshu_api/main.py"
    # 在 admin.router 挂载之后添加 admin_auth.router
    sed -i '/app.include_router(admin.router)/a\    app.include_router(admin_auth.router)' "$APP_DIR/lingshu_api/main.py"
    echo "Registered admin_auth router in main.py"
fi

# 3. 修改 admin.py 的 _require_admin 使用 admin_users 表
# 备份原文件
cp "$APP_DIR/lingshu_api/routers/admin.py" "$APP_DIR/lingshu_api/routers/admin.py.bak"

# 用 Python 脚本修改 admin.py
python3 << 'PYEOF'
import re

path = "/home/CODEX/lingshu-cloud/app/lingshu_api/routers/admin.py"
with open(path, "r") as f:
    content = f.read()

# 替换 _require_admin 函数，使用 admin_users 表
old_func = '''def _require_admin(authorization: str, store: BookstoreStore) -> dict[str, Any]:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期")
    if not int(user.get("is_admin") or 0):
        raise HTTPException(status_code=403, detail="管理员权限不足")
    return user'''

new_func = '''def _require_admin(authorization: str, store: BookstoreStore) -> dict[str, Any]:
    """管理员认证 — 使用 admin_users 表，与用户认证完全独立。"""
    from lingshu_api.routers.admin_auth import require_admin_user
    import inspect
    # 直接调用 require_admin_user 的核心逻辑
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    from lingshu_api.routers.admin_auth import _get_admin_by_token, _get_db_path
    admin = _get_admin_by_token(_get_db_path(store), token)
    if not admin:
        raise HTTPException(status_code=401, detail="管理员登录已过期或无效")
    return admin'''

content = content.replace(old_func, new_func)

with open(path, "w") as f:
    f.write(content)

print("Updated admin.py _require_admin")
PYEOF

echo "Deployment complete. Restarting service..."
sudo systemctl restart lingshu-cloud.service
sleep 2
sudo systemctl status lingshu-cloud.service --no-pager | head -10
echo "Done."
