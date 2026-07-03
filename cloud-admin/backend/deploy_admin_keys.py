#!/usr/bin/env python3
"""
部署管理员密钥验证模块到服务器。

1. 创建 admin_keys 表
2. 修改 admin_auth.py 支持 HMAC 签名验证
3. 生成初始管理员密钥文件
"""
import os
import sys
import json
import secrets
import hashlib
import hmac as hmac_mod
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_LINGSHU_CLOUD_DIR = os.environ.get("LISHU_CLOUD_DIR")
if not _LINGSHU_CLOUD_DIR:
    _LINGSHU_CLOUD_DIR = "/home/CODEX/lingshu-cloud"
    print(f"[WARN] LISHU_CLOUD_DIR 环境变量未设置，使用默认路径: {_LINGSHU_CLOUD_DIR}")
    print("       建议设置 LISHU_CLOUD_DIR 环境变量以指定灵枢云端部署目录")

DB_PATH = os.path.join(_LINGSHU_CLOUD_DIR, "data/bookstore_demo.db")
ADMIN_AUTH_PY = os.path.join(_LINGSHU_CLOUD_DIR, "app/lingshu_api/routers/admin_auth.py")
KEY_OUTPUT_DIR = os.path.join(_LINGSHU_CLOUD_DIR, "tmp")


def _get_encryption_key(db_path) -> bytes:
    """获取或生成 HMAC 密钥的 AES-256 加密密钥。"""
    env_key = os.environ.get("ADMIN_HMAC_ENCRYPTION_KEY")
    if env_key:
        return base64.b64decode(env_key)
    p = Path(db_path) if not isinstance(db_path, Path) else db_path
    key_file = p.parent / ".admin_encryption_key"
    if key_file.exists():
        return base64.b64decode(key_file.read_text().strip())
    key = AESGCM.generate_key(bit_length=256)
    key_file.write_text(base64.b64encode(key).decode())
    try:
        os.chmod(str(key_file), 0o600)
    except OSError:
        pass
    return key


def _encrypt_secret(plaintext: str, db_path) -> str:
    """使用 AES-256-GCM 加密密钥。返回 aes256gcm:<iv>:<ciphertext>:<tag> 格式。"""
    key = _get_encryption_key(db_path)
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
    ciphertext = ciphertext_with_tag[:-16]
    tag = ciphertext_with_tag[-16:]
    return f"aes256gcm:{base64.b64encode(iv).decode()}:{base64.b64encode(ciphertext).decode()}:{base64.b64encode(tag).decode()}"


def _decrypt_secret(encrypted: str, db_path) -> str:
    """解密密钥。如果值不以 aes256gcm: 开头，则视为明文（向后兼容）。"""
    if not encrypted.startswith("aes256gcm:"):
        return encrypted
    parts = encrypted.split(":")
    if len(parts) != 4:
        raise ValueError("Invalid encrypted secret format")
    _, iv_b64, ct_b64, tag_b64 = parts
    key = _get_encryption_key(db_path)
    aesgcm = AESGCM(key)
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ct_b64)
    tag = base64.b64decode(tag_b64)
    plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
    return plaintext.decode()


def create_admin_keys_table():
    """创建 admin_keys 表。"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_keys (
            key_id TEXT PRIMARY KEY,
            admin_user_id INTEGER NOT NULL,
            secret_encrypted TEXT NOT NULL,
            key_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            issued_at TEXT NOT NULL,
            last_used_at TEXT,
            expires_at TEXT,
            FOREIGN KEY (admin_user_id) REFERENCES admin_users(id)
        )
    """)
    conn.commit()
    conn.close()
    print("[OK] admin_keys table created")


def patch_admin_auth_hmac():
    """修改 admin_auth.py 支持 HMAC 签名验证。"""
    with open(ADMIN_AUTH_PY, "r") as f:
        content = f.read()

    if "hmac_signature" in content:
        print("[SKIP] admin_auth.py already has HMAC verification")
        return

    # 添加 import
    if "import hmac" not in content:
        content = content.replace(
            "import secrets",
            "import secrets\nimport hmac as hmac_mod\nimport hashlib",
        )

    # 添加加密相关 import
    if "from cryptography.hazmat.primitives.ciphers.aead import AESGCM" not in content:
        content = content.replace(
            "import os",
            "import os\nimport base64\nfrom cryptography.hazmat.primitives.ciphers.aead import AESGCM",
        )

    # 添加加密/解密函数（如果 admin_auth.py 中尚未包含）
    if "_decrypt_secret" not in content:
        encrypt_functions = (
            "\n\n"
            "def _get_encryption_key(db_path: Path) -> bytes:\n"
            '    """获取或生成 HMAC 密钥的 AES-256 加密密钥。"""\n'
            "    env_key = os.environ.get('ADMIN_HMAC_ENCRYPTION_KEY')\n"
            "    if env_key:\n"
            "        return base64.b64decode(env_key)\n"
            "    p = Path(db_path) if not isinstance(db_path, Path) else db_path\n"
            "    key_file = p.parent / '.admin_encryption_key'\n"
            "    if key_file.exists():\n"
            "        return base64.b64decode(key_file.read_text().strip())\n"
            "    key = AESGCM.generate_key(bit_length=256)\n"
            "    key_file.write_text(base64.b64encode(key).decode())\n"
            "    try:\n"
            "        os.chmod(str(key_file), 0o600)\n"
            "    except OSError:\n"
            "        pass\n"
            "    return key\n"
            "\n\n"
            "def _encrypt_secret(plaintext: str, db_path: Path) -> str:\n"
            '    """使用 AES-256-GCM 加密密钥。"""\n'
            "    key = _get_encryption_key(db_path)\n"
            "    aesgcm = AESGCM(key)\n"
            "    iv = os.urandom(12)\n"
            "    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)\n"
            "    ciphertext = ciphertext_with_tag[:-16]\n"
            "    tag = ciphertext_with_tag[-16:]\n"
            "    return f'aes256gcm:{base64.b64encode(iv).decode()}:{base64.b64encode(ciphertext).decode()}:{base64.b64encode(tag).decode()}'\n"
            "\n\n"
            "def _decrypt_secret(encrypted: str, db_path: Path) -> str:\n"
            '    """解密密钥。如果值不以 aes256gcm: 开头，则视为明文。"""\n'
            "    if not encrypted.startswith('aes256gcm:'):\n"
            "        return encrypted\n"
            "    parts = encrypted.split(':')\n"
            "    if len(parts) != 4:\n"
            "        raise ValueError('Invalid encrypted secret format')\n"
            "    _, iv_b64, ct_b64, tag_b64 = parts\n"
            "    key = _get_encryption_key(db_path)\n"
            "    aesgcm = AESGCM(key)\n"
            "    iv = base64.b64decode(iv_b64)\n"
            "    ciphertext = base64.b64decode(ct_b64)\n"
            "    tag = base64.b64decode(tag_b64)\n"
            "    plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)\n"
            "    return plaintext.decode()\n"
        )
        content = content.replace(
            "\ndef _get_admin_by_token",
            encrypt_functions + "\ndef _get_admin_by_token",
        )

    # 在 _ensure_admin_tables 中添加 admin_keys 表
    if "admin_keys" not in content:
        old_commit = "        conn.commit()\n\n\ndef _check_login_lockout"
        new_commit = (
            "        conn.execute(\n"
            "            'CREATE TABLE IF NOT EXISTS admin_keys ('\n"
            "            '    key_id TEXT PRIMARY KEY,'\n"
            "            '    admin_user_id INTEGER NOT NULL,'\n"
            "            '    secret_encrypted TEXT NOT NULL,'\n"
            "            '    key_fingerprint TEXT NOT NULL,'\n"
            "            '    status TEXT NOT NULL DEFAULT \'active\','\n"
            "            '    issued_at TEXT NOT NULL,'\n"
            "            '    last_used_at TEXT,'\n"
            "            '    expires_at TEXT,'\n"
            "            '    FOREIGN KEY (admin_user_id) REFERENCES admin_users(id)'\n"
            "            ')'\n"
            "        )\n"
            "        conn.commit()\n\n\n"
            "def _check_login_lockout"
        )
        content = content.replace(old_commit, new_commit)

    # 添加 HMAC 验证函数
    hmac_functions = (
        "\n\n"
        "def _verify_hmac_signature(db_path: Path, key_id: str, timestamp: str, signature: str) -> dict[str, Any] | None:\n"
        '    """验证客户端HMAC签名。返回关联的管理员信息或None。"""\n'
        "    with sqlite3.connect(db_path) as conn:\n"
        "        conn.row_factory = sqlite3.Row\n"
        "        row = conn.execute(\n"
        '            "SELECT k.secret_encrypted, k.status, k.admin_user_id, a.username, a.role, a.status as admin_status "\n'
        '            "FROM admin_keys k JOIN admin_users a ON a.id = k.admin_user_id "\n'
        '            "WHERE k.key_id = ?",\n'
        "            (key_id,),\n"
        "        ).fetchone()\n"
        "        if not row:\n"
        "            return None\n"
        "        if str(row['status']) != 'active':\n"
        "            return None\n"
        "        if str(row['admin_status']) != 'active':\n"
        "            return None\n"
        "        # 验证时间戳（5分钟内有效）\n"
        "        import time\n"
        "        try:\n"
        "            ts = int(timestamp)\n"
        "        except (ValueError, TypeError):\n"
        "            return None\n"
        "        if abs(time.time() * 1000 - ts) > 5 * 60 * 1000:\n"
        "            return None\n"
        "        # 验证 HMAC\n"
        "        secret = _decrypt_secret(row['secret_encrypted'], db_path)\n"
        "        expected = hmac_mod.new(secret.encode(), timestamp.encode(), hashlib.sha256).hexdigest()\n"
        "        if not hmac_mod.compare_digest(expected, signature):\n"
        "            return None\n"
        "        # 更新 last_used_at\n"
        "        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')\n"
        "        conn.execute('UPDATE admin_keys SET last_used_at = ? WHERE key_id = ?', (now, key_id))\n"
        "        conn.commit()\n"
        "        return {'admin_user_id': row['admin_user_id'], 'username': row['username'], 'role': row['role']}\n"
        "\n"
    )

    if "_verify_hmac_signature" not in content:
        content = content.replace(
            "\n@router.post(\"/login\")",
            hmac_functions + "\n@router.post(\"/login\")",
        )

    # 修改登录函数，添加 HMAC 验证
    old_login_start = (
        "    username = (payload.get(\"username\") or \"\").strip()\n"
        "    password = payload.get(\"password\") or \"\"\n"
        "    if not username or not password:\n"
        "        raise HTTPException(status_code=400, detail=\"请输入用户名和密码\")"
    )

    new_login_start = (
        "    username = (payload.get(\"username\") or \"\").strip()\n"
        "    password = payload.get(\"password\") or \"\"\n"
        "    key_id = payload.get(\"key_id\") or \"\"\n"
        "    timestamp = payload.get(\"timestamp\") or \"\"\n"
        "    hmac_signature = payload.get(\"hmac_signature\") or \"\"\n"
        "    if not username or not password:\n"
        "        raise HTTPException(status_code=400, detail=\"请输入用户名和密码\")\n"
        "    if not key_id or not timestamp or not hmac_signature:\n"
        "        raise HTTPException(status_code=400, detail=\"缺少密钥验证信息\")"
    )

    content = content.replace(old_login_start, new_login_start)

    # 在锁定检查之后、密码验证之前添加HMAC验证
    old_lockout_check = (
        "    if _check_login_lockout(db_path, username):\n"
        '        raise HTTPException(status_code=429, detail="登录失败次数过多，账号已锁定15分钟，请稍后再试")\n'
        "\n"
        "    with sqlite3.connect(db_path) as conn:"
    )

    new_lockout_check = (
        "    if _check_login_lockout(db_path, username):\n"
        '        raise HTTPException(status_code=429, detail="登录失败次数过多，账号已锁定15分钟，请稍后再试")\n'
        "\n"
        "    # 验证 HMAC 签名\n"
        "    key_info = _verify_hmac_signature(db_path, key_id, timestamp, hmac_signature)\n"
        "    if not key_info:\n"
        '        raise HTTPException(status_code=403, detail="密钥验证失败，请检查密钥文件是否有效")\n'
        "    if key_info['username'] != username:\n"
        '        raise HTTPException(status_code=403, detail="密钥与账号不匹配")\n'
        "\n"
        "    with sqlite3.connect(db_path) as conn:"
    )

    content = content.replace(old_lockout_check, new_lockout_check)

    with open(ADMIN_AUTH_PY, "w") as f:
        f.write(content)
    print("[OK] admin_auth.py patched: HMAC verification added")


def generate_admin_key(admin_username: str = "test") -> str:
    """为管理员生成密钥文件。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 查找管理员
    cur.execute("SELECT id, username FROM admin_users WHERE username = ?", (admin_username,))
    admin = cur.fetchone()
    if not admin:
        print(f"[ERROR] Admin user '{admin_username}' not found")
        conn.close()
        return ""

    # 生成密钥
    key_id = f"ak_{secrets.token_hex(8)}"
    secret = base64.b64encode(secrets.token_bytes(32)).decode()
    fingerprint = hashlib.sha256(secret.encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 存储到数据库（使用 AES-256-GCM 加密存储）
    encrypted_secret = _encrypt_secret(secret, DB_PATH)
    cur.execute(
        "INSERT INTO admin_keys (key_id, admin_user_id, secret_encrypted, key_fingerprint, status, issued_at) VALUES (?, ?, ?, ?, ?, ?)",
        (key_id, admin["id"], encrypted_secret, fingerprint, "active", now),
    )
    conn.commit()
    conn.close()

    # 生成密钥文件
    key_data = {
        "key_id": key_id,
        "secret": secret,
        "issued_to": admin_username,
        "issued_at": now,
        "server_host": os.environ.get("LINGSHU_SERVER_HOST", "www.ling-shu.top"),
    }

    os.makedirs(KEY_OUTPUT_DIR, exist_ok=True)
    key_file_path = os.path.join(KEY_OUTPUT_DIR, f"{admin_username}_{key_id}.lingshu-key")
    with open(key_file_path, "w") as f:
        json.dump(key_data, f, indent=2, ensure_ascii=False)

    print(f"[OK] Key file generated: {key_file_path}")
    print(f"     key_id: {key_id}")
    print(f"     fingerprint: {fingerprint}")
    return key_file_path


if __name__ == "__main__":
    create_admin_keys_table()
    patch_admin_auth_hmac()
    admin_username = os.environ.get("ADMIN_USERNAME") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not admin_username:
        admin_username = input("请输入管理员用户名: ").strip()
    if not admin_username:
        print("[ERROR] 未提供管理员用户名，退出")
        sys.exit(1)
    key_path = generate_admin_key(admin_username)
    if key_path:
        print(f"\n密钥文件已生成: {key_path}")
        print("请将此文件安全地传送给管理员，用于灵镜管理台登录。")
