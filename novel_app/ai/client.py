from __future__ import annotations

import ipaddress
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from threading import Event
from typing import Any, Self
from urllib import error, request
from urllib.parse import urlparse

import httpx

from novel_app.json_utils import (
    balance_json_like_text,
    extract_json_array,
    extract_json_object,
    json_candidate_text,
    loads_json_payload,
    repair_json_like_text,
)
from novel_app.prompt_utils import prompt_value

from .limits import JSON_OBJECT_DEFAULT_MAX_TOKENS
from .types import DEFAULT_BASE_URL

JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}
JSON_OBJECT_PROMPT_FOOTER = (
    "\n\nReturn only valid JSON. Do not include Markdown fences, "
    "comments, or explanatory text. Example: {\"ok\": true}."
)

class AIClientMixin:
    @classmethod
    def from_env(cls) -> Self:
        """Build a service instance from OPENAI_* environment variables."""
        service = cls()
        try:
            service.configure(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL),
                model=os.getenv("OPENAI_MODEL"),
            )
        except ValueError as exc:
            service.configure(api_key=None, base_url=DEFAULT_BASE_URL, model=None)
            service._remember_remote_error("环境变量配置", exc)
        return service

    def configure(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        """Apply remote API credentials and normalize the base URL."""
        self.api_key = (api_key or "").strip() or None
        self.base_url = self._normalize_base_url(base_url)
        self.model = (model or "").strip() or None
        self.last_remote_error = None
        self._request_timeout = int(os.environ.get("LINGSHU_AI_TIMEOUT", "30")) or None

    def set_model_router(self, model_router: Any) -> None:
        """Attach the model router used for purpose-specific requests."""
        self._model_router = model_router

    def set_prompt_overrides(self, prompt_overrides: dict[str, str] | None) -> None:
        """Replace stored prompt overrides with normalized string values."""
        self.prompt_overrides = {
            str(key): str(value)
            for key, value in (prompt_overrides or {}).items()
        }

    def get_prompt_overrides(self) -> dict[str, str]:
        """Return a copy of the active prompt override mapping."""
        return dict(self.prompt_overrides or {})

    def prompt_text(self, key: str, default: str = "") -> str:
        """Resolve one prompt override with a fallback default."""
        return prompt_value(self.prompt_overrides or {}, key, default)

    def is_remote_configured(self) -> bool:
        """Return whether remote API credentials are ready to use."""
        return bool(self.api_key and self.model)

    def get_mode_label(self) -> str:
        """Return a short human-readable label for the active AI mode."""
        if self.is_remote_configured():
            return f"远程接口 / {self.model}"
        return "本地 Mock"

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        cancel_event: Event | None = None,
        require_remote: bool = True,
    ) -> Iterator[str]:
        """Yield chat response text chunks from the remote API or local fallback."""
        if require_remote:
            self.require_remote("AI 对话")
        safe_messages = [
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in messages
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ]
        if self.api_key and self.model:
            try:
                for chunk in self._stream_chat_completion(safe_messages, temperature=0.45, cancel_event=cancel_event):
                    text = self._stream_delta_text(chunk)
                    if text:
                        yield text
                return
            except Exception as exc:
                self._remember_remote_error("AI 对话", exc)
                if require_remote:
                    raise
        yield from self._chunk_text(self._chat_mock(safe_messages), chunk_size=60, cancel_event=cancel_event)

    async def async_stream_chat(
        self,
        messages: list[dict[str, str]],
        cancel_event: Event | None = None,
        require_remote: bool = True,
    ) -> AsyncIterator[str]:
        """异步版本的流式对话，使用 httpx.AsyncClient 避免阻塞事件循环。"""
        if require_remote:
            self.require_remote("AI 对话")
        safe_messages = [
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in messages
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ]
        if self.api_key and self.model:
            try:
                async for chunk in self._async_stream_chat_completion(safe_messages, temperature=0.45, cancel_event=cancel_event):
                    text = self._stream_delta_text(chunk)
                    if text:
                        yield text
                return
            except Exception as exc:
                self._remember_remote_error("AI 对话", exc)
                if require_remote:
                    raise
        for text_chunk in self._chunk_text(self._chat_mock(safe_messages), chunk_size=60, cancel_event=cancel_event):
            yield text_chunk

    def clone(self) -> Self:
        """Create a new service instance with the same configuration."""
        return self.__class__(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            prompt_overrides=self.get_prompt_overrides(),
        )

    def require_remote(self, purpose: str = "当前功能") -> None:
        """Raise when a feature requires remote AI but credentials are missing."""
        if not self.is_remote_configured():
            raise RuntimeError(f"{purpose}没有配置可用 AI 接口。")

    @staticmethod
    def _normalize_base_url(base_url: str | None) -> str:
        value = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if any(char in value for char in "\r\n\t"):
            raise ValueError("Base URL 不能包含换行或制表符。")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL 必须是 http:// 或 https:// 开头的完整地址。")
        if parsed.scheme == "http" and not AIClientMixin._is_local_http_host(parsed.hostname or ""):
            raise ValueError("远程 Base URL 必须使用 HTTPS；HTTP 仅允许本机模型接口。")
        # SSRF 防护：拒绝指向私有 IP 段的远程 URL
        if parsed.hostname:
            try:
                import ipaddress as _ip
                resolved_ip = _ip.ip_address(parsed.hostname)
                if resolved_ip.is_private or resolved_ip.is_link_local or resolved_ip.is_reserved:
                    raise ValueError("远程 Base URL 不能指向私有网络地址。")
            except ValueError as e:
                if "私有网络地址" in str(e):
                    raise
                # hostname is not a direct IP (e.g. domain name), allow through
                pass
        return value

    @staticmethod
    def _is_local_http_host(host: str) -> bool:
        normalized = host.strip().strip("[]").lower().rstrip(".")
        if normalized in {"localhost", "127.0.0.1", "::1"}:
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    def _chat_completion_endpoint(self) -> str:
        return f"{self._normalize_base_url(self.base_url)}/chat/completions"

    def _remember_remote_error(self, action: str, exc: Exception) -> None:
        message = str(exc)
        if self.api_key:
            message = message.replace(self.api_key, "***")
        self.last_remote_error = f"{action}失败，已回退本地 Mock：{message[:800]}"

    def clear_last_remote_error(self) -> None:
        """Clear the last recorded remote API error."""
        self.last_remote_error = None

    @staticmethod
    def _sleep_with_event_loop_awareness(delay: float) -> None:
        """Sleep for *delay* seconds without starving a running event loop.

        When called from a thread that was dispatched via ``asyncio.to_thread``
        (i.e. a running event loop exists in the main thread), we schedule a
        no-op coroutine on that loop and block only this worker thread until the
        delay elapses.  This avoids holding the thread-pool thread while the
        event loop could schedule other work.

        If no event loop is running, falls back to ``time.sleep``.
        """
        import asyncio as _asyncio
        import time as _time
        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            # No event loop in this thread – safe to use plain sleep.
            _time.sleep(delay)
            return

        # We are inside a thread spawned by the event loop (e.g. to_thread).
        # Use a threading.Event that fires after *delay* seconds so this worker
        # thread blocks without busy-waiting while the event loop remains free
        # to schedule other work.
        from threading import Event as _ThreadEvent
        event = _ThreadEvent()

        async def _fire() -> None:
            await _asyncio.sleep(delay)
            event.set()

        _asyncio.run_coroutine_threadsafe(_fire(), loop)
        event.wait()

    def _retry_request(
        self,
        fn: Callable,
        *,
        max_retries: int = 3,
        retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504),
    ) -> Any:
        """执行 HTTP 请求，对可重试的状态码进行指数退避重试。"""
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except RuntimeError as exc:
                last_exc = exc
                msg = str(exc)
                # 检查是否为可重试的 HTTP 错误
                is_retryable = False
                for code in retryable_status_codes:
                    if f"HTTP {code}" in msg:
                        is_retryable = True
                        break
                if not is_retryable or attempt >= max_retries:
                    raise
                delay = 2 ** attempt  # 1s, 2s, 4s
                self._sleep_with_event_loop_awareness(delay)
        raise last_exc  # 不应到达此处

    async def _async_post_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        extra_body: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """异步发送 chat completion 请求（使用 httpx）。"""
        merged_extra = dict(self.extra_body) if isinstance(self.extra_body, dict) else {}
        if isinstance(extra_body, dict):
            merged_extra.update(extra_body)
        # max_tokens 为 0 或 None 时不传，允许模型自由输出
        if not merged_extra.get("max_tokens"):
            merged_extra.pop("max_tokens", None)
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if merged_extra:
            payload.update(merged_extra)
        endpoint = self._chat_completion_endpoint()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        timeout = timeout or self._request_timeout
        started_at = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            latency_ms = int((time.monotonic() - started_at) * 1000)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
            result = response.json()
            self._capture_usage_event(payload, result, latency_ms=latency_ms)
            return result

    async def _async_stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        cancel_event: Event | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """异步流式 chat completion 请求（使用 httpx）。"""
        merged_extra = dict(self.extra_body) if isinstance(self.extra_body, dict) else {}
        if isinstance(extra_body, dict):
            merged_extra.update(extra_body)
        # max_tokens 为 0 或 None 时不传，允许模型自由输出
        if not merged_extra.get("max_tokens"):
            merged_extra.pop("max_tokens", None)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if merged_extra:
            payload.update(merged_extra)
        endpoint = self._chat_completion_endpoint()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        timeout = self._request_timeout
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream("POST", endpoint, json=payload, headers=headers) as response,
        ):
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(f"HTTP {response.status_code}: {body.decode('utf-8', errors='ignore')}")
            async for raw_line in response.aiter_lines():
                if cancel_event and cancel_event.is_set():
                    break
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue
                payload_text = line[5:].strip()
                if payload_text == "[DONE]":
                    break
                try:
                    yield json.loads(payload_text)
                except json.JSONDecodeError:
                    continue

    async def _async_retry_request(
        self,
        fn: Callable,
        *,
        max_retries: int = 3,
        retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504),
    ) -> Any:
        """异步执行 HTTP 请求，对可重试的状态码进行指数退避重试。"""
        import asyncio as _asyncio
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await fn()
            except RuntimeError as exc:
                last_exc = exc
                msg = str(exc)
                is_retryable = any(f"HTTP {code}" in msg for code in retryable_status_codes)
                if not is_retryable or attempt >= max_retries:
                    raise
                delay = 2 ** attempt
                await _asyncio.sleep(delay)
        raise last_exc

    async def async_post_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """异步发送 chat completion 请求（含重试）。"""
        return await self._async_retry_request(
            lambda: self._async_post_chat_completion(messages, temperature, extra_body)
        )

    async def async_post_json_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        extra_body: dict[str, Any] | None = None,
        *,
        min_max_tokens: int | None = JSON_OBJECT_DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        """异步发送强制 JSON 输出的 chat completion 请求（含重试）。"""
        json_messages = self._messages_with_json_object_instruction(messages)
        json_extra_body = self._json_object_extra_body(extra_body, min_max_tokens=min_max_tokens)
        result = await self._async_retry_request(
            lambda: self._async_post_chat_completion(json_messages, temperature, json_extra_body)
        )
        self._raise_if_truncated(result)
        return result

    def consume_usage_events(self) -> list[dict[str, Any]]:
        """Return captured remote usage events and clear the local buffer."""
        events = list(getattr(self, "_usage_events", []) or [])
        self._usage_events = []
        return events

    def _capture_usage_event(self, payload: dict[str, Any], result: dict[str, Any], *, latency_ms: int = 0) -> None:
        usage = result.get("usage") if isinstance(result, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        messages = payload.get("messages") if isinstance(payload, dict) else []
        input_chars = 0
        if isinstance(messages, list):
            input_chars = sum(len(str(item.get("content", ""))) for item in messages if isinstance(item, dict))
        output_text = ""
        choices = result.get("choices") if isinstance(result, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                output_text = str(message.get("content") or "")
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens) or 0)
        event = {
            "trace_id": str(uuid.uuid4()),
            "model": str(payload.get("model") or ""),
            "provider": urlparse(self._chat_completion_endpoint()).netloc,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "token_source": "provider" if usage else "unknown",
            "input_chars": input_chars,
            "output_chars": len(output_text),
            "latency_ms": max(0, int(latency_ms or 0)),
        }
        events = list(getattr(self, "_usage_events", []) or [])
        events.append(event)
        self._usage_events = events

    def consume_last_remote_error(self) -> str | None:
        """Return and clear the last recorded remote API error."""
        message = self.last_remote_error
        self.last_remote_error = None
        return message

    def _post_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        extra_body: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Post a chat completion request with retry logic.

        timeout: 可选超时秒数，覆盖默认的 _request_timeout。
        分级超时由调用方（AIAnalysisProvider）根据输入文本长度传入。
        """
        merged_extra = dict(self.extra_body) if isinstance(self.extra_body, dict) else {}
        if isinstance(extra_body, dict):
            merged_extra.update(extra_body)
        # max_tokens 为 0 或 None 时不传，允许模型自由输出
        if not merged_extra.get("max_tokens"):
            merged_extra.pop("max_tokens", None)
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if merged_extra:
            payload.update(merged_extra)
        endpoint = self._chat_completion_endpoint()
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = request.Request(endpoint, data=data, headers=headers, method="POST")
        opener = self._chat_completion_opener(endpoint)
        timeout = timeout or self._request_timeout

        def _do_request() -> dict[str, Any]:
            started_at = time.monotonic()
            try:
                use_opener = opener is not None and getattr(request.urlopen, "__module__", "") == "urllib.request"
                response_context = opener.open(req, timeout=timeout) if use_opener else request.urlopen(req, timeout=timeout)
                with response_context as response:
                    result = json.loads(response.read().decode("utf-8"))
                    latency_ms = int((time.monotonic() - started_at) * 1000)
                    self._capture_usage_event(payload, result, latency_ms=latency_ms)
                    return result
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"HTTP {exc.code}: {body}") from exc

        return self._retry_request(_do_request)

    @classmethod
    def _chat_completion_opener(cls, endpoint: str):
        proxy = cls._system_proxy_for_endpoint(endpoint)
        if proxy:
            return request.build_opener(request.ProxyHandler({"http": proxy, "https": proxy}))
        return None

    @classmethod
    def _system_proxy_for_endpoint(cls, endpoint: str) -> str:
        parsed = urlparse(endpoint)
        if cls._is_local_http_host(parsed.hostname or ""):
            return ""
        if os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or os.environ.get("ALL_PROXY"):
            return ""
        if os.name != "nt":
            return ""
        return cls._windows_user_proxy()

    @staticmethod
    def _windows_user_proxy() -> str:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                proxy_enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
                proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
        except Exception:
            return ""
        if not proxy_enabled or not proxy_server:
            return ""
        proxy = _select_windows_proxy(proxy_server)
        if not proxy:
            return ""
        if "://" not in proxy:
            proxy = f"http://{proxy}"
        return proxy

    def _post_json_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        extra_body: dict[str, Any] | None = None,
        *,
        min_max_tokens: int | None = JSON_OBJECT_DEFAULT_MAX_TOKENS,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Post a chat completion request that is forced to return a JSON object."""
        result = self._post_chat_completion(
            self._messages_with_json_object_instruction(messages),
            temperature=temperature,
            extra_body=self._json_object_extra_body(extra_body, min_max_tokens=min_max_tokens),
            timeout=timeout,
        )
        self._raise_if_truncated(result)
        return result

    @staticmethod
    def _raise_if_truncated(result: dict[str, Any]) -> None:
        """Raise if the response was truncated by max_tokens."""
        choices = result.get("choices") if isinstance(result, dict) else None
        if not isinstance(choices, list) or not choices:
            return
        first = choices[0]
        if not isinstance(first, dict):
            return
        finish_reason = str(first.get("finish_reason") or "").strip().lower()
        if finish_reason == "length":
            # 思考模型可能因 reasoning 耗尽 token 报 length，但 content/reasoning_content 仍有内容
            message = first.get("message") or {}
            has_content = bool(str(message.get("content") or "").strip())
            has_reasoning = bool(str(message.get("reasoning_content") or "").strip())
            if not has_content and not has_reasoning:
                raise RuntimeError("AI 返回被 max_tokens 截断，JSON 可能不完整")

    @staticmethod
    def _json_object_extra_body(
        extra_body: dict[str, Any] | None,
        *,
        min_max_tokens: int | None = JSON_OBJECT_DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        normalized = dict(extra_body) if isinstance(extra_body, dict) else {}
        normalized["response_format"] = dict(JSON_OBJECT_RESPONSE_FORMAT)
        # 仅当显式指定 min_max_tokens 时才设置 max_tokens；None 表示不限制输出
        if min_max_tokens is not None:
            try:
                current_max_tokens = int(normalized.get("max_tokens", 0) or 0)
            except (TypeError, ValueError):
                current_max_tokens = 0
            if current_max_tokens < min_max_tokens:
                normalized["max_tokens"] = int(min_max_tokens)
        else:
            # 不限制输出：移除上层传入的 max_tokens，让模型自由输出
            normalized.pop("max_tokens", None)
        return normalized

    @staticmethod
    def _messages_with_json_object_instruction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "") or "")
            if not content.strip():
                continue
            normalized.append(
                {
                    "role": str(item.get("role", "user") or "user"),
                    "content": content,
                }
            )
        for item in reversed(normalized):
            if item["role"] == "user":
                item["content"] = item["content"].rstrip() + JSON_OBJECT_PROMPT_FOOTER
                return normalized
        normalized.append({"role": "user", "content": JSON_OBJECT_PROMPT_FOOTER.strip()})
        return normalized

    @staticmethod
    def _chat_completion_content(result: dict[str, Any], purpose: str = "AI 请求") -> str:
        choices = result.get("choices") if isinstance(result, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"{purpose}失败：AI 接口未返回 choices。")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError(f"{purpose}失败：AI 接口返回格式无效。")
        message = first.get("message")
        if not isinstance(message, dict):
            raise RuntimeError(f"{purpose}失败：AI 接口未返回 message。")
        content = message.get("content")
        text = str(content).strip() if content else ""
        if not text:
            # 思考模型（如 deepseek-v4-flash）可能将内容放在 reasoning_content
            reasoning = message.get("reasoning_content")
            text = str(reasoning).strip() if reasoning else ""
        if not text:
            raise RuntimeError(f"{purpose}失败：AI 接口返回内容为空。")
        return text

    def _stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        cancel_event: Event | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        merged_extra = dict(self.extra_body) if isinstance(self.extra_body, dict) else {}
        if isinstance(extra_body, dict):
            merged_extra.update(extra_body)
        # max_tokens 为 0 或 None 时不传，允许模型自由输出
        if not merged_extra.get("max_tokens"):
            merged_extra.pop("max_tokens", None)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if merged_extra:
            payload.update(merged_extra)
        endpoint = self._chat_completion_endpoint()
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self._request_timeout) as response:
                for raw_line in response:
                    if cancel_event and cancel_event.is_set():
                        break
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload_text = line[5:].strip()
                    if payload_text == "[DONE]":
                        break
                    try:
                        yield json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc

    @staticmethod
    def _stream_delta_text(chunk: dict[str, Any]) -> str:
        choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content", "")
        text = content if isinstance(content, str) else ""
        if not text.strip():
            # 思考模型流式响应可能将内容放在 reasoning_content
            reasoning = delta.get("reasoning_content", "")
            text = reasoning if isinstance(reasoning, str) else ""
        return text

    def _extract_json_payload(self, text: str) -> list[Any]:
        return extract_json_array(text, fallback_array_key="skills")

    def _extract_json_object_payload(self, text: str) -> dict[str, Any]:
        return extract_json_object(text)

    @staticmethod
    def _json_candidate_text(text: str, open_char: str, close_char: str) -> str:
        return json_candidate_text(text, open_char, close_char)

    @classmethod
    def _loads_json_payload(cls, text: str) -> Any:
        return loads_json_payload(text)

    @staticmethod
    def _repair_json_like_text(text: str) -> str:
        return repair_json_like_text(text)

    @staticmethod
    def _balance_json_like_text(text: str) -> str:
        return balance_json_like_text(text)

    def _chunk_text(
        self,
        text: str,
        chunk_size: int = 80,
        cancel_event: Event | None = None,
    ) -> Iterator[str]:
        for index in range(0, len(text), chunk_size):
            if cancel_event and cancel_event.is_set():
                break
            yield text[index : index + chunk_size]


def _select_windows_proxy(proxy_server: str) -> str:
    value = str(proxy_server or "").strip()
    if not value:
        return ""
    if ";" not in value and "=" not in value:
        return value
    entries: dict[str, str] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        key, raw_proxy = part.split("=", 1)
        key = key.strip().lower()
        raw_proxy = raw_proxy.strip()
        if key and raw_proxy:
            entries[key] = raw_proxy
    return entries.get("https") or entries.get("http") or entries.get("socks") or ""
