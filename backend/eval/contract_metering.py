"""Evaluation-only usage recording; agents continue using the injected LLM protocol."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.llm import AnthropicLLM
from app.core.settings import Settings

PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
FX_SOURCE = "https://www.ecb.europa.eu/stats/eurofxref/"
# ECB 13 Nov 2026: USD/EUR 1.1052 and GBP/EUR 0.83559.
USD_PER_GBP = Decimal("1.1052") / Decimal("0.83559")
PRICES = {
    # USD per million tokens: input, output, 5m write, 1h write, cache hit.
    "claude-sonnet-5-5": ("2", "10", "2.5", "4", "0.10"),
    "claude-sonnet-4-6": ("3", "15", "3.75", "6", "0.30"),
}


class BudgetExceeded(RuntimeError):
    """No further paid request can fit under the explicitly authorised budget."""


class UsageLedger:
    """Persist reservations before API calls, so failures and restarts retain a spending bound."""

    def __init__(self, path: Path, budget_gbp: Decimal = Decimal("5")) -> None:
        if not Decimal("0") < budget_gbp <= Decimal("5"):
            raise ValueError("The authorised total evaluation budget is at most GBP 5.")
        self.path = path
        self.budget_gbp = budget_gbp
        self.entries: list[dict[str, Any]] = []
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.entries = data["entries"]
        # A second, conservative USD 5 ceiling leaves FX headroom below the GBP 5 limit.
        self.cap_usd = min(budget_gbp * USD_PER_GBP, Decimal("5"))

    @property
    def charged_bound_usd(self) -> Decimal:
        """Measured costs plus upper-bound reservations for calls with unknown billing."""
        return sum(
            (Decimal(e.get("cost_usd") or e["reserved_usd"]) for e in self.entries), Decimal(0)
        )

    def save(self) -> None:
        """Persist only usage metadata, never prompts, responses or credentials."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.summary(), indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def reserve(self, model: str, amount: Decimal) -> int:
        """Reserve the maximum expected cost before submitting a billable request."""
        if amount <= 0 or self.charged_bound_usd + amount > self.cap_usd:
            raise BudgetExceeded("The next request would exceed the remaining evaluation budget.")
        entry = {
            "at": datetime.now(UTC).isoformat(),
            "model": model,
            "reserved_usd": str(amount),
            "cost_usd": None,
            "usage": None,
            "status": "reserved",
        }
        self.entries.append(entry)
        self.save()
        return len(self.entries) - 1

    def record(self, index: int, usage: dict[str, Any], prices: tuple[str, ...]) -> None:
        """Calculate published-price cost from provider-reported token usage."""
        cost = usage_cost(usage, prices)
        self.entries[index].update(cost_usd=str(cost), usage=usage, status="measured")
        self.save()

    def summary(self) -> dict[str, Any]:
        """Separate measured API cost from unknown-cost reservations and FX estimates."""
        measured = sum(
            (Decimal(e["cost_usd"]) for e in self.entries if e["cost_usd"] is not None), Decimal(0)
        )
        return {
            "budget_gbp": str(self.budget_gbp),
            "hard_cap_usd": str(self.cap_usd),
            "measured_cost_usd": str(measured),
            "estimated_gbp_at_reference_rate": str(measured / USD_PER_GBP),
            "charged_bound_usd": str(self.charged_bound_usd),
            "unknown_cost_calls": sum(e["cost_usd"] is None for e in self.entries),
            "pricing_source": PRICING_SOURCE,
            "pricing_verified_on": "2026-11-14",
            "fx_source": FX_SOURCE,
            "fx_date": "2026-11-13",
            "usd_per_gbp": str(USD_PER_GBP),
            "entries": self.entries,
        }


def usage_cost(usage: dict[str, Any], prices: tuple[str, ...]) -> Decimal:
    """Apply input/output/cache rates without treating cached tokens as free."""
    input_rate, output_rate, write5_rate, write60_rate, read_rate = map(Decimal, prices)
    cache = usage.get("cache_creation") or {}
    writes60 = int(cache.get("ephemeral_1h_input_tokens", 0))
    writes5 = int(
        cache.get("ephemeral_5m_input_tokens", usage.get("cache_creation_input_tokens", 0))
    )
    if any(int(usage.get(key, 0)) < 0 for key in ("input_tokens", "output_tokens")):
        raise ValueError("Provider reported invalid token counts.")
    return (
        Decimal(usage["input_tokens"]) * input_rate
        + Decimal(usage["output_tokens"]) * output_rate
        + Decimal(writes5) * write5_rate
        + Decimal(writes60) * write60_rate
        + Decimal(usage.get("cache_read_input_tokens", 0)) * read_rate
    ) / 1_000_000


class MeteredAnthropicLLM(AnthropicLLM):
    """Use the existing adapter interface, recording every paid attempt including retries."""

    def __init__(self, settings: Settings, ledger: UsageLedger) -> None:
        if settings.llm_model not in PRICES:
            raise ValueError(
                "No verified price for this model; update the evaluation price table first."
            )
        super().__init__(settings)
        self._client = self._client.with_options(max_retries=0, timeout=75.0)
        self.ledger = ledger
        self._lock = asyncio.Lock()

    async def _create(self, system: str, content: Any, model: str | None) -> str:
        selected = model or self._model
        if selected not in PRICES:
            raise ValueError("No verified price for the requested model.")
        prices = PRICES[selected]
        messages: Any = [{"role": "user", "content": content}]
        async with self._lock:
            tokens = await self._client.messages.count_tokens(
                model=selected,
                system=system,
                messages=messages,
            )
            # Count estimates can differ from actual usage; reserve input headroom and max output.
            bound = (
                (Decimal(tokens.input_tokens) * Decimal("1.25") + 1024) * Decimal(prices[0])
                + 4096 * Decimal(prices[1])
            ) / 1_000_000
            index = self.ledger.reserve(selected, bound)
            # Failed/time-out calls keep their reservation because their billing is uncertain.
            response = await self._client.messages.create(
                model=selected,
                max_tokens=4096,
                system=system,
                messages=messages,
            )
            self.ledger.record(index, response.usage.model_dump(), prices)
            if response.stop_reason == "max_tokens":
                raise ValueError("Model output was truncated; no partial JSON was accepted.")
            return "".join(block.text for block in response.content if block.type == "text")

    async def close(self) -> None:
        """Release the SDK transport after an evaluation run."""
        await self._client.close()
