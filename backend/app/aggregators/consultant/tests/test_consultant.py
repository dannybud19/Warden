from app.aggregators.consultant.consultant import propose_actions
from app.aggregators.scoring.scoring import load_weights, score
from app.contracts import Case, CheckId, CheckState
from app.core.agent import AgentContext
from app.orchestrator.checks import initial_checks


def _case(base: Case) -> Case:
    return base.model_copy(update={"checks": initial_checks(), "actions": []})


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
    case.checks = [
        c.model_copy(update={"state": CheckState.CLEARED})
        if c.id == CheckId.LANDLORD_IDENTITY
        else c
        for c in case.checks
    ]
    result = score(case.checks, load_weights())
    ids = [a.id for a in await propose_actions(case, result, ctx, max_actions=4)]
    assert "act_company_number" not in ids
    assert len(ids) == 3
