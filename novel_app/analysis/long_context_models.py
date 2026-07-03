from __future__ import annotations

import re
from typing import Any

ONE_SHOT_CONTEXT_THRESHOLD_TOKENS = 1_000_000


_MODEL_CONTEXTS: dict[str, tuple[str, int, str]] = {
    # OpenAI
    "gpt-5.5": ("openai", 1_000_000, "OpenAI 1M context model"),
    "gpt-5.5-pro": ("openai", 1_000_000, "OpenAI 1M context model"),
    "gpt-5.4": ("openai", 1_000_000, "OpenAI 1M context model"),
    "gpt-5.4-pro": ("openai", 1_000_000, "OpenAI 1M context model"),
    "gpt-4.1": ("openai", 1_000_000, "OpenAI GPT-4.1 1M context model"),
    "gpt-4.1-mini": ("openai", 1_000_000, "OpenAI GPT-4.1 1M context model"),
    "gpt-4.1-nano": ("openai", 1_000_000, "OpenAI GPT-4.1 1M context model"),
    # Google Gemini
    "gemini-3.1-pro-preview": ("google", 1_048_576, "Gemini 1M input-token model"),
    "gemini-3.1-pro-preview-customtools": ("google", 1_048_576, "Gemini 1M input-token model"),
    "gemini-3.5-flash": ("google", 1_048_576, "Gemini 1M input-token model"),
    "gemini-3-flash-preview": ("google", 1_048_576, "Gemini 1M input-token model"),
    "gemini-2.5-pro": ("google", 1_048_576, "Gemini 1M input-token model"),
    "gemini-2.5-flash": ("google", 1_048_576, "Gemini 1M input-token model"),
    "gemini-2.5-flash-lite": ("google", 1_048_576, "Gemini 1M input-token model"),
    # DeepSeek
    "deepseek-v4-pro": ("deepseek", 1_000_000, "DeepSeek V4 1M context model"),
    "deepseek-v4-flash": ("deepseek", 1_000_000, "DeepSeek V4 1M context model"),
    # Anthropic
    "claude-fable-5": ("anthropic", 1_000_000, "Claude 1M context model"),
    "claude-mythos-5": ("anthropic", 1_000_000, "Claude 1M context model"),
    "claude-opus-4-8": ("anthropic", 1_000_000, "Claude 1M context model"),
    "claude-sonnet-4-6": ("anthropic", 1_000_000, "Claude 1M context model"),
    # xAI
    "grok-4.3": ("xai", 1_000_000, "xAI Grok 1M+ context model"),
    "grok-4.3-latest": ("xai", 1_000_000, "xAI Grok 1M+ context model"),
    "grok-latest": ("xai", 1_000_000, "xAI Grok 1M+ context model"),
    "grok-4-1-fast": ("xai", 2_000_000, "xAI Grok 4.1 Fast long-context model"),
    "grok-4-1-fast-latest": ("xai", 2_000_000, "xAI Grok 4.1 Fast long-context model"),
    "grok-4-1-fast-reasoning": ("xai", 2_000_000, "xAI Grok 4.1 Fast long-context model"),
    "grok-4-1-fast-reasoning-latest": ("xai", 2_000_000, "xAI Grok 4.1 Fast long-context model"),
    "grok-4-1-fast-non-reasoning": ("xai", 2_000_000, "xAI Grok 4.1 Fast long-context model"),
    "grok-4-1-fast-non-reasoning-latest": ("xai", 2_000_000, "xAI Grok 4.1 Fast long-context model"),
    # Qwen / DashScope
    "qwen3.6-plus": ("qwen", 1_000_000, "Qwen / DashScope 1M context model"),
    "qwen3.6-flash": ("qwen", 1_000_000, "Qwen / DashScope 1M context model"),
    "qwen3.5-plus": ("qwen", 1_000_000, "Qwen / DashScope 1M context model"),
    "qwen3-coder-plus": ("qwen", 1_000_000, "Qwen coding model with 1M context"),
    "qwen2.5-7b-instruct-1m": ("qwen", 1_000_000, "Qwen2.5 1M context model"),
    "qwen2.5-14b-instruct-1m": ("qwen", 1_000_000, "Qwen2.5 1M context model"),
}


_EXCLUDED_EXACT = {
    "deepseek-chat",
    "deepseek-reasoner",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
}


_EXCLUDED_PREFIXES = ("kimi-", "grok-build-")


def detect_long_context_model(model: str, base_url: str = "") -> dict[str, Any]:
    """Return whether a configured chat-completions model is safe for one-shot analysis."""
    normalized = normalize_model_name(model)
    if not normalized:
        return _not_matched(model, "model name is empty")
    if normalized in _EXCLUDED_EXACT or normalized.startswith(_EXCLUDED_PREFIXES):
        return _not_matched(model, "model is explicitly not treated as 1M context")

    candidate_names = [normalized]
    if "/" in normalized:
        candidate_names.append(normalized.rsplit("/", 1)[-1])
    if ":" in normalized:
        candidate_names.append(normalized.rsplit(":", 1)[-1])
    if normalized.startswith("models/"):
        candidate_names.append(normalized.removeprefix("models/"))

    for candidate in dict.fromkeys(candidate_names):
        if candidate in _EXCLUDED_EXACT or candidate.startswith(_EXCLUDED_PREFIXES):
            return _not_matched(model, "model is explicitly not treated as 1M context")
        info = _MODEL_CONTEXTS.get(candidate)
        if not info:
            continue
        provider, context_tokens, reason = info
        return {
            "matched": context_tokens >= ONE_SHOT_CONTEXT_THRESHOLD_TOKENS,
            "provider": provider,
            "context_tokens": context_tokens,
            "model": candidate,
            "configured_model": str(model or "").strip(),
            "base_url": str(base_url or "").strip(),
            "reason": reason,
        }

    return _not_matched(model, "model is not in the built-in 1M+ context table")


def normalize_model_name(model: str) -> str:
    value = str(model or "").strip().lower()
    value = value.removeprefix("models/")
    value = re.sub(r"\s+", "", value)
    return value


def _not_matched(model: str, reason: str) -> dict[str, Any]:
    return {
        "matched": False,
        "provider": "",
        "context_tokens": 0,
        "model": normalize_model_name(model),
        "configured_model": str(model or "").strip(),
        "reason": reason,
    }


__all__ = ["ONE_SHOT_CONTEXT_THRESHOLD_TOKENS", "detect_long_context_model", "normalize_model_name"]
