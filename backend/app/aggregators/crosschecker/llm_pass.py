"""The single LLM call: render the sources, ask for disagreements, parse the reply."""

from pathlib import Path

from app.aggregators.crosschecker.models import ReviewOutput
from app.aggregators.crosschecker.sources import Source
from app.core.agent import AgentContext

PROMPT_PATH = Path(__file__).parent / "prompts" / "review.md"


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
    raise NotImplementedError


async def run(sources: list[Source], ctx: AgentContext) -> ReviewOutput:
    """Ask the LLM for disagreements between `sources`; any failure raises `LLMPassError`."""
    raise NotImplementedError
