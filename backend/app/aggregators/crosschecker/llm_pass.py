"""The single LLM call: render the sources, ask for disagreements, parse the reply."""

from pathlib import Path

from pydantic import ValidationError

from app.aggregators.crosschecker.models import ReviewOutput
from app.aggregators.crosschecker.sources import Source
from app.core.agent import AgentContext

PROMPT_PATH = Path(__file__).parent / "prompts" / "review.md"
INDENT = "   "  # continuation lines of a source are indented by this
CLOSING = "Return the JSON object only."
UNREADABLE = "the model's reply could not be read"
FAILED = "the model call failed"


class LLMPassError(Exception):
    """The LLM step failed. `reason` is short, safe to show the student, and holds no secrets."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def system_prompt() -> str:
    """The system prompt in `prompts/review.md`."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_user(sources: list[Source]) -> str:
    """The user message: the numbered sources (plan Appendix A format)."""
    lines = ["SOURCES"]
    for source in sources:
        first, *rest = source.text.split("\n")
        lines.append(f"{source.id} [{source.agent} | {source.evidence_id}] {source.kind}: {first}")
        lines.extend(f"{INDENT}{line}".rstrip() for line in rest)
    return "\n".join(lines) + f"\n\n{CLOSING}"


async def run(sources: list[Source], ctx: AgentContext) -> ReviewOutput:
    """Ask the LLM for disagreements between `sources`; any failure raises `LLMPassError`."""
    try:
        return await ctx.llm.complete_json(system_prompt(), render_user(sources), ReviewOutput)
    except Exception as exc:  # not BaseException: CancelledError must reach wait_for
        ctx.log.warning("crosscheck llm pass failed: %s", type(exc).__name__)
        reason = UNREADABLE if isinstance(exc, ValidationError) else FAILED
        raise LLMPassError(reason) from exc
