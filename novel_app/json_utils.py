from __future__ import annotations

import json
import re
from typing import Any


def json_candidate_text(text: str, open_char: str = "{", close_char: str = "}") -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find(open_char)
    end = stripped.rfind(close_char)
    if start != -1 and end != -1 and end > start:
        stripped = stripped[start : end + 1]
    return stripped


def repair_json_like_text(text: str) -> str:
    repaired = str(text or "").strip().lstrip("\ufeff")
    repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", repaired)
    repaired = (
        repaired
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    key_pattern = r'"[^"\n\r]+":'
    repaired = re.sub(rf'([}}\]"])\s*\n\s*({key_pattern})', r"\1,\n\2", repaired)
    repaired = re.sub(rf'((?:true|false|null)|-?\d+(?:\.\d+)?)\s*\n\s*({key_pattern})', r"\1,\n\2", repaired)
    repaired = re.sub(r'([}\]"])\s*\n\s*([{\[])', r"\1,\n\2", repaired)
    repaired = re.sub(r'(")\s*\n\s*(")', r'\1,\n\2', repaired)
    return repaired


def balance_json_like_text(text: str) -> str:
    balanced = str(text or "")
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in balanced:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    if in_string:
        balanced += '"'
    if stack:
        balanced += "".join(reversed(stack))
    return balanced


def loads_json_payload(text: str) -> Any:
    candidates = [str(text or "")]
    repaired = repair_json_like_text(candidates[0])
    if repaired != candidates[0]:
        candidates.append(repaired)
    balanced = balance_json_like_text(repaired)
    if balanced != repaired:
        candidates.append(balanced)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return json.loads(candidates[0])


def extract_json_object(text: str) -> dict[str, Any]:
    parsed = loads_json_payload(json_candidate_text(text, "{", "}"))
    if isinstance(parsed, dict):
        return parsed
    raise ValueError("Model did not return a JSON object.")


def extract_json_array(text: str, fallback_array_key: str | None = None) -> list[Any]:
    parsed = loads_json_payload(json_candidate_text(text, "[", "]"))
    if isinstance(parsed, list):
        return parsed
    if fallback_array_key and isinstance(parsed, dict) and isinstance(parsed.get(fallback_array_key), list):
        return parsed[fallback_array_key]
    raise ValueError("Model did not return a JSON array.")


def extract_json_dict(raw: Any) -> dict[str, Any]:
    """Parse *raw* into a dict.  If *raw* is already a dict it is returned
    as-is; otherwise the value is stringified and parsed as JSON.
    Returns an empty dict on parse failure or when the result is not a dict.
    """
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


__all__ = [
    "json_candidate_text",
    "repair_json_like_text",
    "balance_json_like_text",
    "loads_json_payload",
    "extract_json_object",
    "extract_json_array",
    "extract_json_dict",
]
