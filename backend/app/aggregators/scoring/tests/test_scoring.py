import pytest

from app.aggregators.scoring.scoring import load_weights, score
from app.contracts import Check, CheckId, CheckState
from app.orchestrator.checks import initial_checks


def _cleared(check: Check, confidence: float = 1.0) -> Check:
    return check.model_copy(update={"state": CheckState.CLEARED, "clear_confidence": confidence})


def test_weights_cover_every_check_and_sum_to_one() -> None:
    weights = load_weights()
    assert set(weights) == set(CheckId)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_all_unverified_scores_100() -> None:
    result = score(initial_checks(), load_weights())
    assert result.score == 100.0
    assert set(result.contributions) == set(CheckId)


def test_all_cleared_at_full_confidence_scores_0() -> None:
    checks = [_cleared(c) for c in initial_checks()]
    assert score(checks, load_weights()).score == 0.0


def test_only_landlord_identity_cleared_scores_80() -> None:
    checks = [_cleared(c) if c.id == CheckId.LANDLORD_IDENTITY else c for c in initial_checks()]
    result = score(checks, load_weights())
    assert result.score == 80.0
    assert result.contributions[CheckId.LANDLORD_IDENTITY] == 0.0


def test_suspicious_does_not_lower_the_score() -> None:
    checks = [c.model_copy(update={"state": CheckState.SUSPICIOUS}) for c in initial_checks()]
    assert score(checks, load_weights()).score == 100.0


def test_partial_clear_confidence() -> None:
    checks = [_cleared(c, 0.5) if c.id == CheckId.PAYMENT_SAFETY else c for c in initial_checks()]
    assert score(checks, load_weights()).score == 90.0
