from __future__ import annotations

import pytest

from novel_app.analysis.long_context_models import detect_long_context_model, normalize_model_name


@pytest.mark.parametrize(
    "model,provider",
    [
        ("gpt-5.5", "openai"),
        ("openai/gpt-4.1", "openai"),
        ("google/gemini-2.5-pro", "google"),
        ("deepseek-v4-pro", "deepseek"),
        ("anthropic/claude-sonnet-4-6", "anthropic"),
        ("x-ai/grok-4-1-fast", "xai"),
        ("dashscope/qwen3.6-plus", "qwen"),
        ("qwen2.5-14b-instruct-1m", "qwen"),
    ],
)
def test_detect_long_context_model_matches_1m_models(model: str, provider: str) -> None:
    result = detect_long_context_model(model, "https://router.example.test/v1")

    assert result["matched"] is True
    assert result["provider"] == provider
    assert result["context_tokens"] >= 1_000_000


@pytest.mark.parametrize(
    "model",
    [
        "deepseek-chat",
        "deepseek-reasoner",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "kimi-k2",
        "grok-build-beta",
        "unknown-large-model",
    ],
)
def test_detect_long_context_model_rejects_unconfirmed_models(model: str) -> None:
    result = detect_long_context_model(model)

    assert result["matched"] is False
    assert result["context_tokens"] == 0


def test_normalize_model_name_strips_models_prefix_and_whitespace() -> None:
    assert normalize_model_name(" models/Gemini-2.5-Pro \n") == "gemini-2.5-pro"
