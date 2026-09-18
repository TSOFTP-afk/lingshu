"""安全的 JSON 解析工具，带大小和深度限制。

用于解析 AI 输出或不可信 JSON 文本，防止恶意嵌套/超大输入触发 OOM 或栈溢出。
"""
from __future__ import annotations

import json as _json

MAX_JSON_SIZE = 1_000_000  # 1MB
MAX_JSON_DEPTH = 20


def safe_json_loads(text: str, max_size: int = MAX_JSON_SIZE) -> object:
    """安全的 json.loads，带大小和深度限制。

    解析前校验输入字节数不超过 max_size，解析后递归校验嵌套深度不超过
    MAX_JSON_DEPTH。超限抛出 ValueError。
    """
    if not isinstance(text, str):
        raise TypeError("safe_json_loads 要求 str 输入")
    if len(text) > max_size:
        raise ValueError(f"JSON input too large: {len(text)} > {max_size}")
    obj = _json.loads(text)
    _check_depth(obj, MAX_JSON_DEPTH)
    return obj


def _check_depth(obj: object, max_depth: int, current: int = 0) -> None:
    if current > max_depth:
        raise ValueError(f"JSON depth exceeds {max_depth}")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_depth(v, max_depth, current + 1)
    elif isinstance(obj, list):
        for v in obj:
            _check_depth(v, max_depth, current + 1)
