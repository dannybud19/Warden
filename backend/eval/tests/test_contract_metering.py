import json
from decimal import Decimal
from pathlib import Path

import pytest

from eval.contract_metering import PRICES, BudgetExceeded, UsageLedger, usage_cost


def test_actual_usage_prices_input_output_and_cache_separately() -> None:
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 200,
        "cache_creation": {"ephemeral_5m_input_tokens": 150, "ephemeral_1h_input_tokens": 50},
    }
    assert usage_cost(usage, PRICES["claude-sonnet-5-5"]) == Decimal("0.007585")


def test_ledger_survives_restart_and_keeps_unknown_cost_reservations(tmp_path: Path) -> None:
    file = tmp_path / "usage.json"
    ledger = UsageLedger(file)
    ledger.reserve("claude-sonnet-5-5", Decimal("4.95"))
    resumed = UsageLedger(file)
    assert resumed.summary()["unknown_cost_calls"] == 1
    with pytest.raises(BudgetExceeded):
        resumed.reserve("claude-sonnet-5-5", Decimal("0.06"))


def test_measured_usage_replaces_reservation_and_records_no_prompts(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "usage.json")
    index = ledger.reserve("claude-sonnet-5-5", Decimal("0.1"))
    ledger.record(index, {"input_tokens": 1000, "output_tokens": 500}, PRICES["claude-sonnet-5-5"])
    assert ledger.charged_bound_usd == Decimal("0.007")
    stored = json.loads(ledger.path.read_text())
    assert stored["unknown_cost_calls"] == 0 and "prompts" not in stored
    assert "key" not in stored


def test_budget_cannot_exceed_user_authorisation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at most GBP 5"):
        UsageLedger(tmp_path / "usage.json", Decimal("5.01"))
