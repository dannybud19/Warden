import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from eval.contract_metering import BudgetExceeded, MeteredAnthropicLLM, UsageLedger


class FakeMessages:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.paid_calls = 0

    async def count_tokens(self, **kwargs: Any) -> Any:
        return SimpleNamespace(input_tokens=1000)

    async def create(self, **kwargs: Any) -> Any:
        self.paid_calls += 1
        if self.fail:
            raise TimeoutError("synthetic transport failure")
        return SimpleNamespace(
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 1000, "output_tokens": 500}),
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text='{"ok":true}')],
        )


def fake_metered(tmp_path: Path, provider: FakeMessages) -> MeteredAnthropicLLM:
    """Inject a fake SDK without constructing a real client or reading credentials."""
    adapter = object.__new__(MeteredAnthropicLLM)
    adapter._client = cast(Any, SimpleNamespace(messages=provider))
    adapter._model = "claude-sonnet-5-5"
    adapter._lock = asyncio.Lock()
    adapter.ledger = UsageLedger(tmp_path / "usage.json")
    return adapter


async def test_live_adapter_records_usage_and_reserves_before_call(tmp_path: Path) -> None:
    provider = FakeMessages()
    adapter = fake_metered(tmp_path, provider)
    assert await adapter.complete("system", "synthetic data") == '{"ok":true}'
    assert provider.paid_calls == 1
    assert adapter.ledger.summary()["measured_cost_usd"] == "0.007"


async def test_no_paid_request_is_sent_when_budget_is_exhausted(tmp_path: Path) -> None:
    provider = FakeMessages()
    adapter = fake_metered(tmp_path, provider)
    adapter.ledger.reserve("claude-sonnet-5-5", Decimal("4.99"))
    with pytest.raises(BudgetExceeded):
        await adapter.complete("system", "synthetic data")
    assert provider.paid_calls == 0


async def test_failed_request_retains_its_unknown_billing_reservation(tmp_path: Path) -> None:
    adapter = fake_metered(tmp_path, FakeMessages(fail=True))
    with pytest.raises(TimeoutError):
        await adapter.complete("system", "synthetic data")
    assert adapter.ledger.summary()["unknown_cost_calls"] == 1
    assert adapter.ledger.charged_bound_usd > 0
