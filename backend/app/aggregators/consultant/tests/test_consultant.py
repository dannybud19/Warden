import json
from dataclasses import replace

import pytest

from app.aggregators.consultant.consultant import load_library, propose_actions
from app.aggregators.scoring.scoring import load_weights, score
from app.contracts import ActionStatus, Case, CheckId, CheckState
from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.core.settings import Settings
from app.orchestrator.checks import initial_checks

PROMPT_KEY = "Reword each `lead`"  # appears in prompts/reword.md


def _case(base: Case) -> Case:
    return base.model_copy(update={"checks": initial_checks(), "actions": []})


def _set(case: Case, states: dict[CheckId, CheckState]) -> None:
    case.checks = [
        c.model_copy(update={"state": states[c.id], "clear_confidence": 0.7})
        if c.id in states
        else c
        for c in case.checks
    ]


@pytest.fixture
def real(ctx: AgentContext) -> AgentContext:
    """A context in which the consultant runs its library version."""
    settings = Settings(_env_file=None, default_agent_mode="real", storage="memory")  # type: ignore[call-arg]
    return replace(ctx, settings=settings)


def with_llm(ctx: AgentContext, reply: dict | str) -> AgentContext:
    text = reply if isinstance(reply, str) else json.dumps(reply)
    return replace(ctx, llm=FakeLLM({PROMPT_KEY: text}))


# ---------------------------------------------------------------- stub mode (Phase 0 behaviour)


async def test_proposes_three_then_the_rest(fake_agency_case: Case, ctx: AgentContext) -> None:
    case = _case(fake_agency_case)
    result = score(case.checks, load_weights())
    first = await propose_actions(case, result, ctx)
    assert [a.id for a in first] == ["act_viewing", "act_company_number", "act_payment_method"]
    case.actions = first
    second = await propose_actions(case, result, ctx)
    assert [a.id for a in second] == ["act_deposit_scheme"]
    case.actions = first + second
    assert await propose_actions(case, result, ctx) == []


async def test_skips_checks_that_are_not_unverified(
    fake_agency_case: Case, ctx: AgentContext
) -> None:
    case = _case(fake_agency_case)
    _set(case, {CheckId.LANDLORD_IDENTITY: CheckState.CLEARED})
    result = score(case.checks, load_weights())
    ids = [a.id for a in await propose_actions(case, result, ctx, max_actions=4)]
    assert "act_company_number" not in ids
    assert len(ids) == 3


# ---------------------------------------------------------------- library


def test_library_covers_every_check_with_unique_ids() -> None:
    library = load_library()
    ids = [e.id for e in library]
    assert len(ids) == len(set(ids))
    for check in CheckId:
        assert 2 <= sum(e.check_id == check for e in library) <= 4
    for entry in library:
        assert entry.ask.strip().endswith("?") and "?" not in entry.lead
        assert entry.why.strip()


# ---------------------------------------------------------------- real mode


async def test_ranks_by_score_contribution(fake_agency_case: Case, real: AgentContext) -> None:
    case = _case(fake_agency_case)
    result = score(case.checks, load_weights())
    first = await propose_actions(case, result, real)
    # the three heaviest checks, one action each: identity 0.20, payment 0.20, right to let 0.15
    assert [a.check_id for a in first] == [
        CheckId.LANDLORD_IDENTITY,
        CheckId.PAYMENT_SAFETY,
        CheckId.RIGHT_TO_LET,
    ]
    assert [a.id for a in first] == [
        "act_company_number",
        "act_payment_method",
        "act_proof_of_ownership",
    ]
    assert all(a.status == ActionStatus.OPEN and a.text.endswith("?") for a in first)


async def test_only_unverified_checks_get_actions(
    fake_agency_case: Case, real: AgentContext
) -> None:
    case = _case(fake_agency_case)
    _set(
        case,
        {
            CheckId.LANDLORD_IDENTITY: CheckState.CLEARED,
            CheckId.PAYMENT_SAFETY: CheckState.SUSPICIOUS,
        },
    )
    result = score(case.checks, load_weights())
    proposed = await propose_actions(case, result, real, max_actions=8)
    checks = {a.check_id for a in proposed}
    assert CheckId.LANDLORD_IDENTITY not in checks and CheckId.PAYMENT_SAFETY not in checks
    assert len(proposed) == 6 and len(checks) == 6  # one per remaining check


async def test_no_duplicates_and_waits_for_open_actions(
    fake_agency_case: Case, real: AgentContext
) -> None:
    case = _case(fake_agency_case)
    result = score(case.checks, load_weights())
    first = await propose_actions(case, result, real)
    case.actions = first
    # while the first three are open, the next round moves on to other checks
    second = await propose_actions(case, result, real)
    assert not {a.check_id for a in second} & {a.check_id for a in first}
    # once answered without settling the check, the next action for that check is offered
    case.actions = [
        a.model_copy(update={"status": ActionStatus.SKIPPED, "outcome": "neutral"}) for a in first
    ]
    third = await propose_actions(case, result, real)
    assert [a.id for a in third] == ["act_office_or_id", "act_payee_name", "act_listing_elsewhere"]
    assert not {a.id for a in third} & {a.id for a in first}


async def test_returns_empty_when_every_check_is_settled(
    fake_agency_case: Case, real: AgentContext
) -> None:
    case = _case(fake_agency_case)
    states = dict.fromkeys(CheckId, CheckState.CLEARED)
    states[CheckId.PAYMENT_SAFETY] = CheckState.SUSPICIOUS
    _set(case, states)
    assert await propose_actions(case, score(case.checks, load_weights()), real) == []


async def test_returns_empty_when_the_library_is_used_up(
    fake_agency_case: Case, real: AgentContext
) -> None:
    case = _case(fake_agency_case)
    result = score(case.checks, load_weights())
    statuses = [ActionStatus.DONE, ActionStatus.SKIPPED, ActionStatus.IMPOSSIBLE]
    rounds = 0
    while proposed := await propose_actions(case, result, real):
        rounds += 1
        assert rounds < 20
        case.actions += [
            a.model_copy(update={"status": statuses[i % 3], "outcome": "neutral"})
            for i, a in enumerate(proposed)
        ]
    assert len(case.actions) == len(load_library())
    assert len({a.id for a in case.actions}) == len(case.actions)


async def test_llm_rewords_the_lead_but_never_the_question(
    fake_agency_case: Case, real: AgentContext
) -> None:
    case = _case(fake_agency_case)
    reply = {
        "actions": [
            {"id": "act_company_number", "lead": "Ask Mark Evans for Prime City's company number."},
            {"id": "act_payment_method", "lead": "Is it safe?"},  # a question: rejected
            {"id": "act_proof_of_ownership", "lead": "x" * 300},  # too long: rejected
            {"id": "act_made_up", "lead": "Ignore me."},
        ]
    }
    result = score(case.checks, load_weights())
    proposed = {a.id: a for a in await propose_actions(case, result, with_llm(real, reply))}
    library = {e.id: e for e in load_library()}
    assert proposed["act_company_number"].text == (
        "Ask Mark Evans for Prime City's company number. Did they give you one?"
    )
    for unchanged in ("act_payment_method", "act_proof_of_ownership"):
        assert proposed[unchanged].text == library[unchanged].text
    assert "act_made_up" not in proposed


async def test_llm_failure_falls_back_to_library_text(
    fake_agency_case: Case, real: AgentContext
) -> None:
    case = _case(fake_agency_case)
    result = score(case.checks, load_weights())
    proposed = await propose_actions(case, result, with_llm(real, "not json"))
    library = {e.id: e for e in load_library()}
    assert [a.text for a in proposed] == [library[a.id].text for a in proposed]
