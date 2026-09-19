from __future__ import annotations

import base64
import ctypes
import getpass
import hashlib
import logging
import os
import uuid
from ctypes import wintypes

logger = logging.getLogger(__name__)

DPAPI_PREFIX = "dpapi:"
KEYRING_PREFIX = "keyring:"
FERNET_PREFIX = "fernet:"
_LEGACY_APP_ENTROPY = b"LingShuNovel-v1.3"
_KEYRING_SERVICE = "LingShuNovel"


def _app_entropy() -> bytes:
    user = getpass.getuser().encode("utf-8", errors="ignore")
    base = b"LingShuNovel-v1.3"
    return hashlib.sha256(base + b":" + user).digest()


def _fernet_from_master_key():
    """根据 env ``LINGSHU_MASTER_KEY`` 构造 Fernet 实例；未配置或依赖缺失时返回 None。"""
    master = os.environ.get("LINGSHU_MASTER_KEY", "").strip()
    if not master:
        return None
    try:
        from cryptography.fernet import Fernet
    except Exception:
        logger.error("cryptography 库不可用，无法使用 LINGSHU_MASTER_KEY 加密")
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(master.encode("utf-8")).digest())
    return Fernet(key)


def _is_windows() -> bool:
    """平台判定单点。

    独立成函数是为了可测试性：测试模拟 Linux 分支时替换本函数即可，
    严禁全局补丁 os.name——pathlib 的路径类按 os.name 派发，全局补丁会让
    窗口内所有 Path() 构造出"假 PosixPath"，在 Windows 上引发
    NotImplementedError 并把 pytest 的失败报告炸成 INTERNALERROR。
    """
    return os.name == "nt"


def protect_secret(secret: str) -> str:
    if not secret:
        return ""
    if _is_windows():
        return f"{DPAPI_PREFIX}{base64.b64encode(_crypt_protect(secret.encode('utf-8'), _app_entropy())).decode('ascii')}"
    # Linux/macOS：master key Fernet 加密优先（docker 部署确定性最高），其次 keyring；
    # 两者都不可用时抛出明确异常，绝不将密钥明文写入数据库。
    fernet = _fernet_from_master_key()
    if fernet is not None:
        return f"{FERNET_PREFIX}{fernet.encrypt(secret.encode('utf-8')).decode('ascii')}"
    keyring_id = _store_keyring_secret(secret)
    if keyring_id:
        return f"{KEYRING_PREFIX}{keyring_id}"
    raise RuntimeError(
        "无可用安全存储后端，拒绝将 API Key 明文写入数据库。"
        "请设置环境变量 LINGSHU_MASTER_KEY（任意强随机字符串，用于加密存储），"
        "或安装并配置可用的 keyring 后端。详见部署文档中 LINGSHU_MASTER_KEY 的说明。"
    )


def unprotect_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith(FERNET_PREFIX):
        fernet = _fernet_from_master_key()
        if fernet is None:
            raise RuntimeError(
                "检测到 Fernet 加密的密钥，但未设置 LINGSHU_MASTER_KEY（或密钥已变更），无法解密"
            )
        return fernet.decrypt(value[len(FERNET_PREFIX) :].encode("ascii")).decode("utf-8")
    if value.startswith(KEYRING_PREFIX):
        return _load_keyring_secret(value[len(KEYRING_PREFIX) :])
    if not value.startswith(DPAPI_PREFIX):
        return value
    if not _is_windows():
        logger.warning("DPAPI is only available on Windows, cannot decrypt secret")
        return ""
    payload = base64.b64decode(value[len(DPAPI_PREFIX) :].encode("ascii"))
    errors: list[Exception] = []
    for entropy in (_app_entropy(), _LEGACY_APP_ENTROPY):
        try:
            return _crypt_unprotect(payload, entropy).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    raise errors[-1]


def _store_keyring_secret(secret: str) -> str:
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception:
        return ""
    keyring_id = f"api-key-{uuid.uuid4().hex}-{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:12]}"
    try:
        keyring.set_password(_KEYRING_SERVICE, keyring_id, secret)
    except Exception:
        logger.exception("Failed to store secret in keyring")
        return ""
    return keyring_id


def _load_keyring_secret(keyring_id: str) -> str:
    if not keyring_id:
        return ""
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception:
        logger.warning("keyring package is unavailable, cannot decrypt keyring secret")
        return ""
    try:
        return keyring.get_password(_KEYRING_SERVICE, keyring_id) or ""
    except Exception:
        logger.exception("Failed to load secret from keyring")
        return ""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(wintypes.BYTE)),
    ]


def _make_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(wintypes.BYTE)))
    return blob, buffer


def _crypt_protect(data: bytes, entropy: bytes | None = None) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_blob, _buffer = _make_blob(data)
    entropy_blob = None
    entropy_buffer = None
    if entropy:
        entropy_blob, entropy_buffer = _make_blob(entropy)
    out_blob = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, wintypes.HLOCAL))


def _crypt_unprotect(data: bytes, entropy: bytes | None = None) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_blob, _buffer = _make_blob(data)
    entropy_blob = None
    entropy_buffer = None
    if entropy:
        entropy_blob, entropy_buffer = _make_blob(entropy)
    out_blob = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob) if entropy_blob else None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, wintypes.HLOCAL))
