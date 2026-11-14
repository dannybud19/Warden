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
    llm = _llm([httpx.Response(429)] * 3, seen)
    with pytest.raises(httpx.HTTPStatusError):
        await llm.complete("s", "u")
    assert len(seen) == 3


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
