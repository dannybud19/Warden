"""Names and ids shared by the Cross-checker's modules."""

from app.contracts import FactKey

AGENT = "crosscheck"
ID_PREFIX = f"{AGENT}:"
NOT_RUN_ID = f"{AGENT}:not-run"

# The rule-based crosscheck (orchestrator) names its findings `crosscheck:<fact key>`. LLM findings
# never take these ids, so a rerun can tell the two apart.
RULE_IDS = frozenset(f"{ID_PREFIX}{key.value}" for key in FactKey)
