"""Risk score. Pure: no I/O, no LLM. Starts at 100 and only drops through clears."""

from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.contracts import Check, CheckId, CheckState, ScoreResult

Weights = dict[CheckId, float]

WEIGHTS_PATH = Path(__file__).parent / "weights.yaml"


def load_weights(path: Path | None = None) -> Weights:
    """Read check weights from `weights.yaml` (next to this module by default)."""
    raw = yaml.safe_load((path or WEIGHTS_PATH).read_text())
    return {CheckId(key): float(value) for key, value in raw.items()}


def score(checks: list[Check], weights: Weights) -> ScoreResult:
    """`100 * sum(w_i * s_i) / sum(w_i)`, with s = 1 unless the check is CLEARED.

    A CLEARED check contributes `1 - clear_confidence`. Values are rounded to 2 decimals
    so that float noise never turns 100 into 99.99999999999999.
    """
    total = sum(weights.values())
    contributions: dict[CheckId, float] = {}
    for check in checks:
        s = 1 - check.clear_confidence if check.state == CheckState.CLEARED else 1.0
        contributions[check.id] = round(100 * weights.get(check.id, 0.0) * s / total, 2)
    return ScoreResult(
        at=datetime.now(UTC),
        score=round(sum(contributions.values()), 2),
        contributions=contributions,
    )
