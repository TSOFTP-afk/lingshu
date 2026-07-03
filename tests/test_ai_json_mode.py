from __future__ import annotations

from typing import Any

import pytest

from novel_app.ai.client import _select_windows_proxy
from novel_app.ai.limits import BOOK_ANALYSIS_LEVEL3_MAX_TOKENS
from novel_app.ai.service import SimpleAIService


class CapturingAIService(SimpleAIService):
    def __init__(self, response_text: str = '{"ok": true}', *, finish_reason: str | None = None) -> None:
        super().__init__(api_key="test-key", model="deepseek-chat")
        self.response_text = response_text
        self.finish_reason = finish_reason
        self.calls: list[dict[str, Any]] = []

    def _post_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "extra_body": dict(extra_body or {}),
            }
        )
        choice: dict[str, Any] = {"message": {"content": self.response_text}}
        if self.finish_reason is not None:
            choice["finish_reason"] = self.finish_reason
        return {"choices": [choice]}


def test_generation_prompt_overrides_remote_generation_templates() -> None:
    service = CapturingAIService("generated text")
    service.set_prompt_overrides(
        {
            "ai.generation.system": "SYSTEM OVERRIDE",
            "ai.generation.template": "Book={book_title};Task={task_instruction};Skills={skill_block};Context={sourcebook_context}",
            "ai.generation.continue_task": "CONTINUE TASK",
        }
    )

    result = service._generate_remote(
        mode="continue",
        book_title="Book",
        chapter_title="Chapter",
        outline="Outline",
        current_content="Current",
        summary_text="Summary",
        selected_skills=[{"name": "Skill", "category": "节奏", "instruction": "Use beats"}],
        sourcebook_context="Sourcebook context",
    )

    call = service.calls[-1]
    assert result == "generated text"
    assert call["messages"][0]["content"] == "SYSTEM OVERRIDE"
    prompt = call["messages"][1]["content"]
    assert "Book=Book" in prompt
    assert "Task=CONTINUE TASK" in prompt
    assert "Skill（节奏）：Use beats" in prompt
    assert "Context=Sourcebook context" in prompt


def test_summary_prompt_overrides_remote_templates() -> None:
    service = CapturingAIService("summary text")
    service.set_prompt_overrides(
        {
            "ai.summary.system": "SUMMARY SYSTEM",
            "ai.summary.template": "Summary for {book_title}/{chapter_title}: {content}",
        }
    )

    result = service._summarize_remote("Book", "Chapter", "Outline", "Body text")

    call = service.calls[-1]
    assert result == "summary text"
    assert call["messages"][0]["content"] == "SUMMARY SYSTEM"
    assert call["messages"][1]["content"] == "Summary for Book/Chapter: Body text"


def test_skill_distill_prompt_overrides_remote_templates() -> None:
    service = CapturingAIService(
        '[{"name":"Scene Beat","category":"结构","summary":"s","instruction":"i","use_cases":"u","risk_note":"r"}]'
    )
    service.set_prompt_overrides(
        {
            "ai.skill_distill.system": "SKILL SYSTEM",
            "ai.skill_distill.template": "Skill source {source_title}: {source_text}",
        }
    )

    result = service._distill_remote("Source", "Reference text")

    call = service.calls[-1]
    assert result[0]["name"] == "Scene Beat"
    assert call["messages"][0]["content"] == "SKILL SYSTEM"
    assert call["messages"][1]["content"] == "Skill source Source: Reference text"


def test_post_json_chat_completion_forces_deepseek_json_mode_contract() -> None:
    service = CapturingAIService()

    service._post_json_chat_completion(
        [
            {"role": "system", "content": "You answer with data."},
            {"role": "user", "content": "Return the result."},
        ],
        temperature=0.2,
        extra_body={"response_format": {"type": "text"}, "max_tokens": 16, "custom": True},
        min_max_tokens=1234,
    )

    call = service.calls[-1]
    assert call["extra_body"]["response_format"] == {"type": "json_object"}
    assert call["extra_body"]["max_tokens"] == 1234
    assert call["extra_body"]["custom"] is True
    assert "json" in call["messages"][-1]["content"].lower()
    assert '{"ok": true}' in call["messages"][-1]["content"]


def test_simple_ai_service_direct_init_configures_timeout_state() -> None:
    service = SimpleAIService(api_key="test", base_url="https://api.deepseek.com", model="m")

    assert service.is_remote_configured()
    assert hasattr(service, "_request_timeout")


def test_windows_proxy_parser_prefers_https_proxy() -> None:
    assert _select_windows_proxy("127.0.0.1:20085") == "127.0.0.1:20085"
    assert _select_windows_proxy("http=127.0.0.1:7890;https=127.0.0.1:20085") == "127.0.0.1:20085"


def test_chat_completion_proxy_skips_localhost_and_explicit_env(monkeypatch) -> None:
    service = SimpleAIService(api_key="test", base_url="http://127.0.0.1:8080/v1", model="m")
    monkeypatch.setattr(SimpleAIService, "_windows_user_proxy", staticmethod(lambda: "http://127.0.0.1:20085"))
    assert service._system_proxy_for_endpoint("http://127.0.0.1:8080/v1/chat/completions") == ""

    service = SimpleAIService(api_key="test", base_url="https://api.deepseek.com", model="m")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    assert service._system_proxy_for_endpoint("https://api.deepseek.com/chat/completions") == ""


@pytest.mark.skip(reason="DEPRECATED: 三层金字塔系统已移除，analyze_book_level3_draft 不再可用")
def test_book_analysis_level3_draft_forces_json_mode_even_when_extra_body_is_wrong() -> None:
    service = CapturingAIService('{"book_outline_form":{"fields":{}},"analysis_unresolved":[]}')

    payload = service.analyze_book_level3_draft(
        book_title="Test Book",
        book_outline="",
        level2_results=[{"level": 2, "story_summary": "summary"}],
        chapters=[{"id": 1, "title": "Chapter 1", "outline": "", "content": "content"}],
        characters=[],
        world_entries=[],
        source_index=[],
        extra_body={"response_format": {"type": "text"}, "max_tokens": 128},
        require_remote=True,
    )

    call = service.calls[-1]
    assert payload["book_outline_form"]["fields"] == {}
    assert call["temperature"] is None
    assert call["extra_body"]["response_format"] == {"type": "json_object"}
    assert call["extra_body"]["max_tokens"] == BOOK_ANALYSIS_LEVEL3_MAX_TOKENS


@pytest.mark.skip(reason="DEPRECATED: 三层金字塔系统已移除，analyze_book_one_shot 不再可用")
def test_book_analysis_one_shot_prompt_includes_templates_and_forms() -> None:
    service = CapturingAIService(
        '{"book_outline_form":{"fields":{"working_title":{"value":"Test Book"}}},'
        '"world_form":{"fields":{}},'
        '"characters":[{"name":"Lin Yi","role":"protagonist","profile_form":{"fields":{}}}],'
        '"chapter_updates":[]}'
    )

    payload = service.analyze_book_one_shot(
        book_title="Test Book",
        book_outline="existing outline",
        chapters=[{"id": 1, "title": "Chapter 1", "outline": "", "content": "Lin Yi enters the city."}],
        source_blocks=[
            {
                "block_uid": "analysis-chapter-1-part-001",
                "chunk_id": "chunk-1",
                "chapter_ids": [1],
                "chapter_refs": [{"id": 1, "title": "Chapter 1"}],
                "text": "Lin Yi enters the city.",
            }
        ],
        characters=[],
        world_entries=[],
        extra_body={"response_format": {"type": "text"}, "max_tokens": 128},
        require_remote=True,
    )

    call = service.calls[-1]
    prompt = call["messages"][-1]["content"]
    assert payload["book_outline_form"]["fields"]["working_title"]["value"] == "Test Book"
    assert call["temperature"] is None
    assert call["extra_body"]["response_format"] == {"type": "json_object"}
    assert call["extra_body"]["max_tokens"] == BOOK_ANALYSIS_LEVEL3_MAX_TOKENS
    assert "json" in prompt.lower()
    assert "book_outline_form" in prompt
    assert "world_form" in prompt
    assert "profile_form" in prompt
    assert "character_profile_form" in prompt
    assert "source_blocks" in prompt
    assert "Lin Yi enters the city." in prompt


@pytest.mark.skip(reason="DEPRECATED: 三层金字塔系统已移除，analyze_book_one_shot 不再可用")
def test_book_analysis_one_shot_rejects_truncated_json_response() -> None:
    service = CapturingAIService('{"book_outline":"unfinished"', finish_reason="length")

    with pytest.raises(RuntimeError, match="截断"):
        service.analyze_book_one_shot(
            book_title="Test Book",
            book_outline="",
            chapters=[{"id": 1, "title": "Chapter 1", "outline": "", "content": "content"}],
            source_blocks=[{"block_uid": "b1", "chapter_ids": [1], "text": "content"}],
            characters=[],
            world_entries=[],
            require_remote=True,
        )
