"""Meter real evaluation requests without changing production clients or contract budgets."""

import asyncio
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from app.core.llm import AnthropicLLM
from app.core.settings import Settings
from eval.contract_metering import PRICES, PRICING_SOURCE, usage_cost

T = TypeVar("T", bound=BaseModel)


class EvaluationSettings(Settings):
    """Explicit evaluation mode cannot accidentally replay a stub from a local override."""

    def agent_mode(self, agent_name: str) -> Literal["real"]:
        """Run the implemented pipeline including the real consultant."""
        return "real"


class RecordedLLM(AnthropicLLM):
    """Record every paid attempt, including schema retries, errors and cancellations."""

    def __init__(self, settings: Settings, journal: Path) -> None:
        if settings.llm_model not in PRICES:
            raise ValueError("Verify a model's price before evaluating it.")
        super().__init__(settings)
        self._client = self._client.with_options(max_retries=0, timeout=90.0)
        self.journal = journal
        self.events: list[dict[str, Any]] = []
        if journal.exists():
            self.events = [json.loads(line) for line in journal.read_text().splitlines() if line]
        self._journal_lock = asyncio.Lock()
        self._scope: ContextVar[dict[str, Any] | None] = ContextVar(
            "evaluation_scope", default=None
        )
        self.authentication_failed = False

    @contextmanager
    def scope(self, **values: Any) -> Iterator[None]:
        """Carry case and stage through asynchronous agent calls without prompt changes."""
        token = self._scope.set({**(self._scope.get() or {}), **values})
        try:
            yield
        finally:
            self._scope.reset(token)

    async def _record(self, event: dict[str, Any]) -> None:
        async with self._journal_lock:
            await asyncio.to_thread(self._append, event)
            self.events.append(event)

    def _append(self, event: dict[str, Any]) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()

    async def _create(self, system: str, content: Any, model: str | None) -> str:
        selected = model or self._model
        if selected not in PRICES:
            raise ValueError("No verified price for requested model.")
        call = {
            "request_id": uuid4().hex,
            "at": datetime.now(UTC).isoformat(),
            "model": selected,
            "max_tokens": (self._scope.get() or {}).get("max_tokens", self.MAX_TOKENS),
            **(self._scope.get() or {}),
        }
        await self._record({**call, "event": "started"})
        started = time.perf_counter()
        try:
            response = await self._client.messages.create(
                model=selected,
                max_tokens=call["max_tokens"],
                system=system,
                messages=[{"role": "user", "content": content}],
            )
        except BaseException as exc:
            status = getattr(exc, "status_code", None)
            if status in {401, 402, 403}:
                self.authentication_failed = True
            await self._record(
                {
                    **call,
                    "event": "failed",
                    "error_type": type(exc).__name__,
                    "http_status": status,
                    "billing_unknown": status is None or status >= 500,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            )
            raise
        usage = response.usage.model_dump()
        await self._record(
            {
                **call,
                "event": "completed",
                "usage": usage,
                "response_model": response.model,
                "provider_request_id": response.id,
                "cost_usd": str(usage_cost(usage, PRICES[selected])),
                "stop_reason": response.stop_reason,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        # Keep the production output cap and JSON-repair behavior for evaluated agents.
        return "".join(block.text for block in response.content if block.type == "text")

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        """Attach schema identity to accounting; keep production parsing and retry behavior."""
        with self.scope(schema=schema.__name__):
            return await super().complete_json(system, user, schema, model=model)

    def usage_summary(self, case_id: str | None = None) -> dict[str, Any]:
        """Compute list-price cost from provider usage, keeping unknown billing visible."""
        events = [e for e in self.events if case_id is None or e.get("case_id") == case_id]
        started = {e["request_id"] for e in events if e["event"] == "started"}
        finished = {e["request_id"] for e in events if e["event"] != "started"}
        completed = [e for e in events if e["event"] == "completed"]
        failed = [e for e in events if e["event"] == "failed"]
        totals = {}
        for stage in {e.get("stage", "unknown") for e in completed}:
            totals[stage] = str(
                sum(
                    (Decimal(e["cost_usd"]) for e in completed if e.get("stage") == stage),
                    Decimal(0),
                )
            )
        return {
            "attempts": len(started),
            "completed_requests": len(completed),
            "failed_requests": len(failed),
            "unknown_billing_requests": len(started - finished)
            + sum(bool(e["billing_unknown"]) for e in failed),
            "cost_usd": str(sum((Decimal(e["cost_usd"]) for e in completed), Decimal(0))),
            "cost_usd_by_stage": totals,
            "input_tokens": sum(e["usage"].get("input_tokens", 0) for e in completed),
            "output_tokens": sum(e["usage"].get("output_tokens", 0) for e in completed),
            "truncated_responses": sum(e["stop_reason"] == "max_tokens" for e in completed),
            "pricing_source": PRICING_SOURCE,
            "pricing_verified_on": "2026-11-14",
            "cost_basis": "Provider token usage at published list prices; before credits/tax.",
            "budget_policy": "User removed GBP 5 limit for this finite 40-case evaluation.",
        }

    async def close(self) -> None:
        """Close only the real LLM SDK client; external evidence uses a separate mock client."""
        await self._client.close()
