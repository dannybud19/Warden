"""The OpenAI-compatible adapter against a mock transport (no network)."""

import base64
import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.factory import build_context
from app.core.llm import AnthropicLLM, FakeLLM, OpenAICompatibleLLM
from app.core.settings import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8


class Reply(BaseModel):
    answer: str


def _settings(**kwargs: object) -> Settings:
    base = {"llm_provider": "openai_compatible", "llm_api_key": "k", "llm_model": "gemini-x"}
    return Settings(_env_file=None, **(base | kwargs))  # type: ignore[call-arg]


def _llm(replies: list[httpx.Response], seen: list[httpx.Request], **kwargs: object):
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    llm = OpenAICompatibleLLM(
        _settings(**kwargs), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    llm.retry_delay_s = 0
    return llm


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_complete_sends_a_chat_completion() -> None:
    seen: list[httpx.Request] = []
    llm = _llm([_ok("hello")], seen, llm_base_url="https://example.test/v1/")
    assert await llm.complete("sys", "user") == "hello"
    request = seen[0]
    assert str(request.url) == "https://example.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer k"
    body = json.loads(request.content)
    assert body["model"] == "gemini-x" and body["temperature"] == 0
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    assert "response_format" not in body and "reasoning_effort" not in body


async def test_complete_json_parses_and_retries_once_on_bad_json() -> None:
    seen: list[httpx.Request] = []
    llm = _llm([_ok("not json"), _ok('```json\n{"answer": "42"}\n```')], seen)
    assert await llm.complete_json("sys", "user", Reply) == Reply(answer="42")
    first, second = (json.loads(r.content) for r in seen)
    assert first["response_format"] == {"type": "json_object"}
    assert "previous reply was invalid" in second["messages"][0]["content"]


async def test_rate_limit_is_retried_then_raised() -> None:
    seen: list[httpx.Request] = []
    llm = _llm([httpx.Response(429), _ok("ok")], seen)
    assert await llm.complete("s", "u") == "ok" and len(seen) == 2

    seen.clear()
    llm = _llm([httpx.Response(429)] * OpenAICompatibleLLM.ATTEMPTS, seen)
    with pytest.raises(httpx.HTTPStatusError):
        await llm.complete("s", "u")
    assert len(seen) == OpenAICompatibleLLM.ATTEMPTS


async def test_claude_model_overrides_are_ignored_and_effort_is_optional() -> None:
    seen: list[httpx.Request] = []
    llm = _llm([_ok("a"), _ok("b")], seen, llm_reasoning_effort="low")
    await llm.complete("s", "u", model="claude-haiku-5-5")
    await llm.complete("s", "u", model="gemini-lite")
    bodies = [json.loads(r.content) for r in seen]
    assert [b["model"] for b in bodies] == ["gemini-x", "gemini-lite"]
    assert bodies[0]["reasoning_effort"] == "low"


async def test_describe_image_sends_a_data_url() -> None:
    seen: list[httpx.Request] = []
    llm = _llm([_ok("a chat")], seen)
    assert await llm.describe_image(PNG, "read this") == "a chat"
    content = json.loads(seen[0].content)["messages"][1]["content"]
    assert content[0]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(PNG).decode()
    )
    assert content[1] == {"type": "text", "text": "read this"}


async def test_factory_picks_the_client_from_settings() -> None:
    cases = [
        (_settings(), OpenAICompatibleLLM),
        (_settings(llm_api_key=""), FakeLLM),
        (Settings(_env_file=None, anthropic_api_key="a"), AnthropicLLM),  # type: ignore[call-arg]
        (Settings(_env_file=None), FakeLLM),  # type: ignore[call-arg]
        # an Anthropic key alone must not be used when another provider is selected
        (_settings(llm_api_key="", anthropic_api_key="a"), FakeLLM),
    ]
    for settings, expected in cases:
        ctx = build_context(settings)
        assert isinstance(ctx.llm, expected)
        await ctx.http.aclose()


def _with_handler(handler, **kwargs: object) -> OpenAICompatibleLLM:  # noqa: ANN001
    llm = OpenAICompatibleLLM(
        _settings(**kwargs), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    llm.retry_delay_s = 0
    return llm


async def test_a_timeout_is_retried_once_then_raised() -> None:
    timeouts: list[float | None] = []

    def slow(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(httpx.ReadTimeout):
        await _with_handler(slow, llm_timeout_s=7.5).complete("system", "user")
    assert timeouts == [7.5, 7.5]  # its own timeout, and exactly one retry


async def test_a_timeout_then_an_answer_succeeds() -> None:
    replies: list[httpx.Response | None] = [None, _ok("hello")]

    def flaky(request: httpx.Request) -> httpx.Response:
        reply = replies.pop(0)
        if reply is None:
            raise httpx.ReadTimeout("slow", request=request)
        return reply

    assert await _with_handler(flaky).complete("system", "user") == "hello"


def _models(seen: list[httpx.Request]) -> list[str]:
    return [json.loads(r.content)["model"] for r in seen]


async def test_overloaded_model_switches_to_the_fallback() -> None:
    seen: list[httpx.Request] = []
    replies = [httpx.Response(503), httpx.Response(503), _ok("ok")]
    llm = _llm(replies, seen, llm_fallback_model="gemini-backup")
    assert await llm.complete("s", "u") == "ok"
    assert _models(seen) == ["gemini-x", "gemini-x", "gemini-backup"]


async def test_one_overload_or_a_rate_limit_keeps_the_main_model() -> None:
    seen: list[httpx.Request] = []
    replies = [httpx.Response(503), httpx.Response(429), httpx.Response(429), _ok("ok")]
    llm = _llm(replies, seen, llm_fallback_model="gemini-backup")
    assert await llm.complete("s", "u") == "ok"
    assert _models(seen) == ["gemini-x"] * 4


async def test_without_a_fallback_the_main_model_is_retried() -> None:
    seen: list[httpx.Request] = []
    llm = _llm([httpx.Response(503)] * 3 + [_ok("ok")], seen)
    assert await llm.complete("s", "u") == "ok"
    assert _models(seen) == ["gemini-x"] * 4


def test_backoff_doubles_is_capped_and_jittered() -> None:
    llm = OpenAICompatibleLLM(_settings(), httpx.AsyncClient())
    for attempt, base in ((1, 1.0), (2, 2.0), (3, 4.0), (4, 4.0)):
        delays = {llm._backoff(attempt) for _ in range(20)}  # noqa: SLF001
        assert all(0.5 * base <= d <= 1.5 * base for d in delays)
        assert len(delays) > 1
