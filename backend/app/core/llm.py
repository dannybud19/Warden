"""LLM client protocol, the Anthropic adapter and a fake for tests."""

import asyncio
import base64
import random
from typing import Any, Protocol, TypeVar

import anthropic
import httpx
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
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    if image.startswith(b"GIF8"):
        return "image/gif"
    raise ValueError("unsupported image type: expected PNG, JPEG, WebP or GIF")


class AnthropicLLM:
    """Thin adapter over `anthropic.AsyncAnthropic`. Not exercised in tests (no network)."""

    MAX_TOKENS = 4096  # a dense document photo, transcribed verbatim inside JSON, needs the room

    def __init__(self, settings: Settings) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.llm_model

    async def _create(self, system: str, content: Any, model: str | None) -> str:
        response = await self._client.messages.create(
            model=model or self._model,
            max_tokens=self.MAX_TOKENS,
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


class OpenAICompatibleLLM:
    """Any provider that speaks the OpenAI Chat Completions format (Gemini, Groq, Cerebras...).

    Lets the team build and test on a free tier and keep Anthropic for the live run. Uses the
    shared `httpx` client, so there is no extra dependency.
    """

    MAX_TOKENS = 8192  # roomy: some models spend output tokens on reasoning first
    RETRY_STATUSES = (429, 500, 502, 503, 504, 529)
    OVERLOADED = (503, 529)  # "the model is experiencing high demand": another model may not be
    ATTEMPTS = 5
    FALLBACK_AFTER = 2  # overloaded answers from the main model before the fallback is tried
    TIMEOUT_RETRIES = 1  # with the default 20 s timeout, two attempts fit an agent's 45 s
    retry_delay_s = 1.0  # first wait; doubles each retry, capped at MAX_DELAY_S, with jitter
    MAX_DELAY_S = 4.0

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._http = http
        self._url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
        self._model = settings.llm_model
        self._fallback = settings.llm_fallback_model
        self._reasoning_effort = settings.llm_reasoning_effort
        self._timeout = settings.llm_timeout_s

    def _backoff(self, attempt: int) -> float:
        """Seconds to wait before retry `attempt + 1`: exponential, capped, with jitter, so agents
        that were refused together (they run in parallel) do not all retry at the same moment."""
        delay = min(self.retry_delay_s * 2 ** (attempt - 1), self.MAX_DELAY_S)
        return delay * random.uniform(0.5, 1.5)  # noqa: S311 - timing jitter, not security

    def _pick_model(self, model: str | None) -> str:
        # An agent may ask for a specific Claude model; that id means nothing to another provider.
        return model if model and not model.startswith("claude") else self._model

    async def _create(
        self, system: str, content: Any, model: str | None, *, json_mode: bool = False
    ) -> str:
        body: dict[str, Any] = {
            "model": self._pick_model(model),
            "max_tokens": self.MAX_TOKENS,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort
        response: httpx.Response | None = None
        timeouts = overloaded = 0
        for attempt in range(1, self.ATTEMPTS + 1):
            if self._fallback and overloaded >= self.FALLBACK_AFTER:
                body["model"] = self._fallback
            try:
                response = await self._http.post(
                    self._url, json=body, headers=self._headers, timeout=self._timeout
                )
            except httpx.TimeoutException:
                # a slow free tier: retry once, then give up so the agent falls back to its rules
                timeouts += 1
                if timeouts > self.TIMEOUT_RETRIES or attempt == self.ATTEMPTS:
                    raise
                continue
            if response.status_code not in self.RETRY_STATUSES or attempt == self.ATTEMPTS:
                break
            overloaded += response.status_code in self.OVERLOADED
            await asyncio.sleep(self._backoff(attempt))
        assert response is not None
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return (choices[0].get("message", {}).get("content") or "") if choices else ""

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
        text = await self._create(json_system, user, model, json_mode=True)
        try:
            return schema.model_validate_json(_extract_json(text))
        except ValidationError as exc:
            retry_system = f"{json_system}\n\nYour previous reply was invalid: {exc}"
            text = await self._create(retry_system, user, model, json_mode=True)
            return schema.model_validate_json(_extract_json(text))

    async def describe_image(self, image: bytes, prompt: str) -> str:
        """Send one image plus a prompt to the vision model and return its text."""
        data_url = f"data:{_sniff_media_type(image)};base64,{base64.b64encode(image).decode()}"
        content = [
            {"type": "image_url", "image_url": {"url": data_url}},
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
