"""LLM client protocol, the Anthropic adapter and a fake for tests."""

import base64
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.settings import Settings

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    async def complete(self, system: str, user: str, *, model: str | None = None) -> str: ...

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T: ...

    async def describe_image(self, image: bytes, prompt: str) -> str: ...


def _extract_json(text: str) -> str:
    """The substring from the first `{` to the last `}` (the whole text if there is none)."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def _sniff_media_type(image: bytes) -> str:
    if image.startswith(b"\x89PNG"):
        return "image/png"
    if image.startswith(b"\xff\xd8"):
        return "image/jpeg"
    raise ValueError("unsupported image type: expected PNG or JPEG")


class AnthropicLLM:
    """Thin adapter over `anthropic.AsyncAnthropic`. Not exercised in tests (no network)."""

    def __init__(self, settings: Settings) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.llm_model

    async def _create(self, system: str, content: Any, model: str | None) -> str:
        response = await self._client.messages.create(
            model=model or self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    async def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        """Plain text completion."""
        return await self._create(system, user, model)

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        """Completion parsed into `schema`; retries once with the validation error appended."""
        json_system = (
            f"{system}\n\nReply with only a JSON object that matches this schema: "
            f"{schema.model_json_schema()}"
        )
        text = await self._create(json_system, user, model)
        try:
            return schema.model_validate_json(_extract_json(text))
        except ValidationError as exc:
            retry_system = f"{json_system}\n\nYour previous reply was invalid: {exc}"
            text = await self._create(retry_system, user, model)
            return schema.model_validate_json(_extract_json(text))

    async def describe_image(self, image: bytes, prompt: str) -> str:
        """Send one image plus a prompt to the vision model and return its text."""
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _sniff_media_type(image),
                    "data": base64.b64encode(image).decode(),
                },
            },
            {"type": "text", "text": prompt},
        ]
        return await self._create("You read images accurately.", content, None)


class FakeLLM:
    """Canned LLM for tests: the first response whose key is in `system + user` wins."""

    def __init__(self, responses: dict[str, str] | None = None, default: str = "{}") -> None:
        self.responses = responses or {}
        self.default = default
        self.calls: list[dict[str, Any]] = []

    def _match(self, haystack: str) -> str:
        for key, value in self.responses.items():
            if key in haystack:
                return value
        return self.default

    async def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        self.calls.append({"method": "complete", "system": system, "user": user, "model": model})
        return self._match(system + user)

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        self.calls.append(
            {"method": "complete_json", "system": system, "user": user, "model": model}
        )
        return schema.model_validate_json(self._match(system + user))

    async def describe_image(self, image: bytes, prompt: str) -> str:
        self.calls.append({"method": "describe_image", "prompt": prompt, "size": len(image)})
        return self._match(prompt)
