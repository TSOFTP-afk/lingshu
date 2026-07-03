#!/usr/bin/env python3
"""
部署管理员行为审计增强 + 云端密钥生成器。

1. 增强 admin_audit_logs 表（添加 admin_username, ip_address, key_id 字段）
2. 在 admin_auth.py 中添加登录/登出审计记录
3. 创建密钥生成器 API（/api/admin/keys/generate, /api/admin/keys/list, /api/admin/keys/revoke）
4. 生成第一个密钥文件
"""
import json
import os
import sys
import sqlite3

DB_PATH = "/home/CODEX/lingshu-cloud/data/bookstore_demo.db"
ADMIN_AUTH_PY = "/home/CODEX/lingshu-cloud/app/lingshu_api/routers/admin_auth.py"
ADMIN_PY = "/home/CODEX/lingshu-cloud/app/lingshu_api/routers/admin.py"
KEY_OUTPUT_DIR = "/home/CODEX/lingshu-cloud/tmp"


def enhance_audit_table():
    """增强审计表，添加新字段。"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 检查并添加新字段
    new_columns = [
        ("admin_username", "TEXT NOT NULL DEFAULT ''"),
        ("ip_address", "TEXT NOT NULL DEFAULT ''"),
        ("key_id", "TEXT NOT NULL DEFAULT ''"),
        ("user_agent", "TEXT NOT NULL DEFAULT ''"),
    ]

    for col_name, col_type in new_columns:
        try:
            cur.execute(f"ALTER TABLE admin_audit_logs ADD COLUMN {col_name} {col_type}")
            print(f"[OK] Added column {col_name} to admin_audit_logs")
        except sqlite3.OperationalError:
            print(f"[SKIP] Column {col_name} already exists")

    conn.commit()
    conn.close()


def patch_admin_auth_audit():
    """在 admin_auth.py 中添加登录/登出审计记录。"""
    with open(ADMIN_AUTH_PY, "r") as f:
        content = f.read()

    if "admin_audit_logs" in content and "_record_admin_login_audit" in content:
        print("[SKIP] admin_auth.py already has audit logging")
        return

    # 添加审计记录函数
    audit_func = (
        "\n\n"
        "def _record_admin_audit(db_path: Path, admin_user_id: int, admin_username: str, action: str, object_type: str = '', object_id: str = '', detail: dict = None, ip_address: str = '', key_id: str = '') -> None:\n"
        '    """记录管理员行为到审计日志。"""\n'
        "    import json as _json\n"
        "    with sqlite3.connect(db_path) as conn:\n"
        "        conn.execute(\n"
        '            "INSERT INTO admin_audit_logs (admin_user_id, admin_username, action, object_type, object_id, detail, ip_address, key_id) "\n'
        '            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",\n'
        "            (admin_user_id, admin_username, action, object_type, str(object_id), _json.dumps(detail or {}, ensure_ascii=False), ip_address, key_id),\n"
        "        )\n"
        "        conn.commit()\n"
        "\n"
    )

    if "_record_admin_audit" not in content:
        content = content.replace(
            "\n@router.post(\"/login\")",
            audit_func + "\n@router.post(\"/login\")",
        )

    # 在登录成功后添加审计记录
    old_login_success = (
        "    # 登录成功，清除失败记录\n"
        "    _clear_login_failures(db_path, username)"
    )

    new_login_success = (
        "    # 登录成功，清除失败记录\n"
        "    _clear_login_failures(db_path, username)\n"
        "\n"
        "    # 记录登录审计\n"
        "    client_ip = request.client.host if request.client else ''\n"
        "    _record_admin_audit(db_path, row['id'], username, 'login', 'admin_session', '', {'key_id': key_id}, client_ip, key_id)"
    )

    content = content.replace(old_login_success, new_login_success)

    # 在登出时添加审计记录
    old_logout = (
        "    token = _bearer_token(authorization)\n"
        "    if token:\n"
        "        db_path = _get_db_path(store)\n"
        "        with sqlite3.connect(db_path) as conn:\n"
        "            conn.execute(f\"DELETE FROM {_ADMIN_TOKENS_TABLE} WHERE token = ?\", (token,))\n"
        "            conn.commit()"
    )

    new_logout = (
        "    token = _bearer_token(authorization)\n"
        "    if token:\n"
        "        db_path = _get_db_path(store)\n"
        "        # 记录登出审计\n"
        "        admin = _get_admin_by_token(db_path, token)\n"
        "        if admin:\n"
        "            _record_admin_audit(db_path, admin['id'], admin.get('username', ''), 'logout', 'admin_session')\n"
        "        with sqlite3.connect(db_path) as conn:\n"
        "            conn.execute(f\"DELETE FROM {_ADMIN_TOKENS_TABLE} WHERE token = ?\", (token,))\n"
        "            conn.commit()"
    )

    content = content.replace(old_logout, new_logout)

    with open(ADMIN_AUTH_PY, "w") as f:
        f.write(content)
    print("[OK] admin_auth.py patched: login/logout audit logging added")


def create_key_generator_api():
    """在 admin_auth.py 中添加密钥生成器 API。"""
    with open(ADMIN_AUTH_PY, "r") as f:
        content = f.read()

    if "key_generator" in content and "/keys/generate" in content:
        print("[SKIP] Key generator API already exists")
        return

    key_api_code = (
        "\n\n"
        "# ============================================================\n"
        "#  密钥生成器 API\n"
        "# ============================================================\n"
        "\n"
        "import base64\n"
        "import hashlib\n"
        "\n"
        "\n"
        "@router.post(\"/keys/generate\")\n"
        "async def generate_key(payload: dict, admin: dict[str, Any] = Depends(require_admin_user), store: BookstoreStore = Depends(get_store)):\n"
        '    """生成管理员密钥文件。"""\n'
        "    target_username = (payload.get('username') or '').strip()\n"
        "    if not target_username:\n"
        "        raise HTTPException(status_code=400, detail='请指定目标管理员用户名')\n"
        "\n"
        "    db_path = _get_db_path(store)\n"
        "    _ensure_admin_tables(db_path)\n"
        "\n"
        "    with sqlite3.connect(db_path) as conn:\n"
        "        conn.row_factory = sqlite3.Row\n"
        "        admin_row = conn.execute('SELECT id, username FROM admin_users WHERE username = ? AND status = ?', (target_username, 'active')).fetchone()\n"
        "        if not admin_row:\n"
        "            raise HTTPException(status_code=404, detail='管理员账号不存在或已停用')\n"
        "\n"
        "        # 生成密钥\n"
        "        key_id = f'ak_{secrets.token_hex(8)}'\n"
        "        secret = base64.b64encode(secrets.token_bytes(32)).decode()\n"
        "        fingerprint = hashlib.sha256(secret.encode()).hexdigest()[:16]\n"
        "        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')\n"
        "\n"
        "        # 存储到 admin_keys 表\n"
        "        conn.execute(\n"
        "            'INSERT INTO admin_keys (key_id, admin_user_id, secret_encrypted, key_fingerprint, status, issued_at) VALUES (?, ?, ?, ?, ?, ?)',\n"
        "            (key_id, admin_row['id'], secret, fingerprint, 'active', now),\n"
        "        )\n"
        "        conn.commit()\n"
        "\n"
        "    # 记录审计\n"
        "    _record_admin_audit(db_path, admin['id'], admin.get('username', ''), 'generate_key', 'admin_key', key_id, {'target_user': target_username, 'fingerprint': fingerprint})\n"
        "\n"
        "    # 返回密钥文件内容\n"
        "    key_data = {\n"
        "        'key_id': key_id,\n"
        "        'secret': secret,\n"
        "        'issued_to': target_username,\n"
        "        'issued_at': now,\n"
        "        'server_host': os.environ.get('LINGSHU_SERVER_HOST', 'www.ling-shu.top'),\n"
        "    }\n"
        "\n"
        "    return {'ok': True, 'key_data': key_data, 'fingerprint': fingerprint}\n"
        "\n"
        "\n"
        "@router.get(\"/keys/list\")\n"
        "async def list_keys(admin: dict[str, Any] = Depends(require_admin_user), store: BookstoreStore = Depends(get_store)):\n"
        '    """列出所有密钥。"""\n'
        "    db_path = _get_db_path(store)\n"
        "    _ensure_admin_tables(db_path)\n"
        "\n"
        "    with sqlite3.connect(db_path) as conn:\n"
        "        conn.row_factory = sqlite3.Row\n"
        "        rows = conn.execute(\n"
        "            'SELECT k.key_id, k.key_fingerprint, k.status, k.issued_at, k.last_used_at, k.expires_at, a.username as issued_to '\n"
        "            'FROM admin_keys k JOIN admin_users a ON a.id = k.admin_user_id '\n"
        "            'ORDER BY k.issued_at DESC'\n"
        "        ).fetchall()\n"
        "\n"
        "    return {'items': [dict(r) for r in rows]}\n"
        "\n"
        "\n"
        "@router.post(\"/keys/{key_id}/revoke\")\n"
        "async def revoke_key(key_id: str, admin: dict[str, Any] = Depends(require_admin_user), store: BookstoreStore = Depends(get_store)):\n"
        '    """吊销密钥。"""\n'
        "    db_path = _get_db_path(store)\n"
        "    _ensure_admin_tables(db_path)\n"
        "\n"
        "    with sqlite3.connect(db_path) as conn:\n"
        "        row = conn.execute('SELECT key_id FROM admin_keys WHERE key_id = ?', (key_id,)).fetchone()\n"
        "        if not row:\n"
        "            raise HTTPException(status_code=404, detail='密钥不存在')\n"
        "        conn.execute('UPDATE admin_keys SET status = ? WHERE key_id = ?', ('revoked', key_id))\n"
        "        conn.commit()\n"
        "\n"
        "    _record_admin_audit(db_path, admin['id'], admin.get('username', ''), 'revoke_key', 'admin_key', key_id)\n"
        "    return {'ok': True}\n"
    )

    content += key_api_code

    with open(ADMIN_AUTH_PY, "w") as f:
        f.write(content)
    print("[OK] Key generator API added to admin_auth.py")


def generate_first_key():
    """生成第一个管理员密钥。"""
    import secrets as _secrets
    import base64 as _base64
    import hashlib as _hashlib
    from datetime import datetime as _dt, timezone as _tz

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 检查是否已有活跃密钥
    cur.execute("SELECT key_id FROM admin_keys WHERE status = 'active' AND admin_user_id = (SELECT id FROM admin_users WHERE username = 'test')")
    existing = cur.fetchone()
    if existing:
        print(f"[SKIP] Active key already exists for test: {existing['key_id']}")
        conn.close()
        return

    cur.execute("SELECT id, username FROM admin_users WHERE username = 'test'")
    admin = cur.fetchone()
    if not admin:
        print("[ERROR] Admin user 'test' not found")
        conn.close()
        return

    key_id = f"ak_{_secrets.token_hex(8)}"
    secret = _base64.b64encode(_secrets.token_bytes(32)).decode()
    fingerprint = _hashlib.sha256(secret.encode()).hexdigest()[:16]
    now = _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        "INSERT INTO admin_keys (key_id, admin_user_id, secret_encrypted, key_fingerprint, status, issued_at) VALUES (?, ?, ?, ?, ?, ?)",
        (key_id, admin["id"], secret, fingerprint, "active", now),
    )

    # 记录审计
    cur.execute(
        "INSERT INTO admin_audit_logs (admin_user_id, admin_username, action, object_type, object_id, detail, ip_address, key_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (admin["id"], "test", "generate_key", "admin_key", key_id, json.dumps({"method": "initial_setup"}, ensure_ascii=False), "localhost", key_id),
    )

    conn.commit()
    conn.close()

    # 生成密钥文件
    key_data = {
        "key_id": key_id,
        "secret": secret,
        "issued_to": "test",
        "issued_at": now,
        "server_host": os.environ.get("LINGSHU_SERVER_HOST", "www.ling-shu.top"),
    }

    os.makedirs(KEY_OUTPUT_DIR, exist_ok=True)
    key_file_path = os.path.join(KEY_OUTPUT_DIR, f"test_{key_id}.lingshu-key")
    with open(key_file_path, "w") as f:
        json.dump(key_data, f, indent=2, ensure_ascii=False)

    print(f"[OK] First key generated: {key_file_path}")
    print(f"     key_id: {key_id}")
    print(f"     fingerprint: {fingerprint}")
    return key_file_path


if __name__ == "__main__":
    print("=== Step 1: Enhance audit table ===")
    enhance_audit_table()

    print("\n=== Step 2: Add login/logout audit ===")
    patch_admin_auth_audit()

    print("\n=== Step 3: Create key generator API ===")
    create_key_generator_api()

    print("\n=== Step 4: Generate first key ===")
    key_path = generate_first_key()

    if key_path:
        print(f"\n{'='*50}")
        print(f"密钥文件已生成: {key_path}")
        print("请将此文件安全地传送给管理员，用于灵镜管理台登录。")
        print("此文件包含敏感信息，请勿泄露！")
