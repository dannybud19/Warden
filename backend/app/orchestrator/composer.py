"""The round message: one short chat message to the student after each analysis that does not
decide. An LLM writes it from a small structured input; a validator rejects anything risky and a
deterministic template takes over (plan 4.4)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.agent import AgentContext

COMPOSE_TIMEOUT_S = 10.0
MAX_WORDS = 60

NoteKind = Literal[
    "unmatched",
    "dropped",
    "fallback",
    "field_changed",
    "field_invalid",
    "question",
    "upload_hint",
]


@dataclass(frozen=True)
class CheckMove:
    check: str  # human label, e.g. "landlord identity"
    before: str  # CheckState value
    after: str


@dataclass(frozen=True)
class RoundNote:
    kind: NoteKind
    text: str = ""  # short plain fact, already masked, e.g. "rent set to 950"


@dataclass(frozen=True)
class RoundInput:
    score_before: int | None
    score_after: int
    moved: tuple[CheckMove, ...] = ()
    not_run: tuple[str, ...] = ()  # checks or agents that did not run this round
    new_actions: int = 0
    open_actions: int = 0
    recap_sent: bool = False  # a Cross-checker recap message went out just before this one
    notes: tuple[RoundNote, ...] = ()
    grounding: tuple[str, ...] = ()  # P2: check states and finding titles, to answer a question


def compose_prompt() -> str:
    """The system prompt for the round message."""
    return (Path(__file__).parent / "prompts" / "compose.md").read_text(encoding="utf-8")


async def compose_round(inp: RoundInput, ctx: AgentContext) -> str:
    """LLM message for this round; `template(inp)` on any error, timeout or violation."""
    raise NotImplementedError


def validate(text: str, inp: RoundInput) -> list[str]:
    """Names of the rules `text` breaks (empty list: OK to send)."""
    raise NotImplementedError


def template(inp: RoundInput) -> str:
    """Deterministic message for this round. Always passes `validate`."""
    raise NotImplementedError
