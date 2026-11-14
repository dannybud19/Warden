"""Consultant: proposes the next questions and actions for the student.

Which actions are offered, and in what order, is plain code over `action_library.yaml`. The LLM
only rewords the chosen actions to fit the case, and the library wording is used if it fails.
"""

import json
from functools import lru_cache
from pathlib import Path

import yaml

from app.aggregators.consultant.models import LibraryAction, RewordOutput
from app.aggregators.consultant.stub import stub_actions
from app.contracts import Action, ActionStatus, Case, CheckId, CheckState, ScoreResult
from app.core.agent import AgentContext

NAME = "consultant"  # `AGENT_MODE_CONSULTANT=real` switches the library version on
LIBRARY_PATH = Path(__file__).parent / "action_library.yaml"
MAX_LEAD = 200
MAX_CONTEXT_FINDINGS = 6


@lru_cache
def load_library(path: Path = LIBRARY_PATH) -> tuple[LibraryAction, ...]:
    """Every candidate action, in library order."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(
        LibraryAction(check_id=CheckId(check), **entry)
        for check, entries in raw.items()
        for entry in entries
    )


@lru_cache
def reword_prompt() -> str:
    return (Path(__file__).parent / "prompts" / "reword.md").read_text(encoding="utf-8")


def select_candidates(
    case: Case, score: ScoreResult, library: tuple[LibraryAction, ...], max_actions: int
) -> list[LibraryAction]:
    """The next action for each check that can still move the score, biggest contribution first.

    A check is worth asking about only while it is UNVERIFIED: a cleared check is settled, and a
    suspicious one cannot be cleared by an answer. One action per check per round, never one the
    student has already been given, and nothing new for a check that still has an open action.
    """
    given = {a.id for a in case.actions}
    waiting = {a.check_id for a in case.actions if a.status == ActionStatus.OPEN}
    unverified = {c.id for c in case.checks if c.state == CheckState.UNVERIFIED}

    next_per_check: dict[CheckId, LibraryAction] = {}
    for entry in library:
        check = entry.check_id
        if check in unverified and check not in waiting and entry.id not in given:
            next_per_check.setdefault(check, entry)

    order: dict[CheckId, int] = {}
    for i, entry in enumerate(library):
        order.setdefault(entry.check_id, i)
    ranked = sorted(
        next_per_check.values(),
        key=lambda e: (-score.contributions.get(e.check_id, 0.0), order[e.check_id]),
    )
    return ranked[:max_actions]


def _case_context(case: Case) -> dict[str, object]:
    findings = [f for report in case.reports.values() for f in report.findings]
    return {
        "landlord": case.landlord.model_dump(mode="json", exclude_none=True)
        if case.landlord
        else {},
        "listing": case.listing.model_dump(mode="json", exclude_none=True) if case.listing else {},
        "findings": [f.title for f in findings[:MAX_CONTEXT_FINDINGS]],
        "agent_questions": [q for r in case.reports.values() for q in r.questions][:4],
    }


async def _reword(case: Case, chosen: list[LibraryAction], ctx: AgentContext) -> dict[str, str]:
    """Case-specific wording for each lead, by action id. Empty when the LLM fails."""
    steps = [{"id": e.id, "lead": e.lead.strip(), "why": e.why} for e in chosen]
    user = (
        f"<case>\n{json.dumps(_case_context(case), ensure_ascii=False)}\n</case>\n\n"
        f"<steps>\n{json.dumps(steps, ensure_ascii=False)}\n</steps>"
    )
    try:
        output = await ctx.llm.complete_json(reword_prompt(), user, RewordOutput)
    except Exception as exc:  # noqa: BLE001 - the library wording is always good enough
        ctx.log.warning("consultant: rewording failed, using library text (%r)", exc)
        return {}
    wanted = {e.id for e in chosen}
    return {
        a.id: a.lead.strip()
        for a in output.actions
        if a.id in wanted and 0 < len(a.lead.strip()) <= MAX_LEAD and "?" not in a.lead
    }


async def propose_actions(
    case: Case, score: ScoreResult, ctx: AgentContext, max_actions: int = 3
) -> list[Action]:
    """The next 1 to `max_actions` actions for the student.

    An empty list means nothing useful is left to ask, which triggers the final decision.
    """
    if ctx.settings.agent_mode(NAME) != "real":
        return stub_actions(case, max_actions)

    chosen = select_candidates(case, score, load_library(), max_actions)
    if not chosen:
        return []
    leads = await _reword(case, chosen, ctx)
    return [
        Action(
            id=entry.id,
            check_id=entry.check_id,
            kind=entry.kind,
            text=f"{leads.get(entry.id, entry.lead.strip())} {entry.ask.strip()}",
        )
        for entry in chosen
    ]
