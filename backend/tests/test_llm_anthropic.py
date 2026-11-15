"""AnthropicLLM request shape, with the SDK client replaced (no network)."""

from types import SimpleNamespace
from typing import Any

from app.core.llm import AnthropicLLM, OpenAICompatibleLLM
from app.core.settings import Settings


class _Messages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])


async def test_vision_calls_have_room_for_a_dense_document() -> None:
    settings = Settings(_env_file=None, anthropic_api_key="test")  # type: ignore[call-arg]
    llm = AnthropicLLM(settings)
    messages = _Messages()
    llm._client = SimpleNamespace(messages=messages)  # type: ignore[assignment]

    assert await llm.describe_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "read it") == "ok"

    assert messages.calls[0]["max_tokens"] == 4096
    assert messages.calls[0]["messages"][0]["content"][0]["source"]["media_type"] == "image/png"
    assert OpenAICompatibleLLM.MAX_TOKENS >= AnthropicLLM.MAX_TOKENS
