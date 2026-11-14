"""Phase 0 behaviour, kept as the consultant's stub mode: four fixed actions in a fixed order."""

from app.contracts import Action, ActionKind, Case, CheckId, CheckState

_STUB_ACTIONS: list[Action] = [
    Action(
        id="act_viewing",
        check_id=CheckId.IN_PERSON_VIEWING,
        kind=ActionKind.ACTION,
        text="Ask to view the property in person, or send a friend, before paying anything. "
        "What did the agent say?",
    ),
    Action(
        id="act_company_number",
        check_id=CheckId.LANDLORD_IDENTITY,
        kind=ActionKind.QUESTION,
        text="Ask the agent for their Companies House number. Did they give you one?",
    ),
    Action(
        id="act_payment_method",
        check_id=CheckId.PAYMENT_SAFETY,
        kind=ActionKind.QUESTION,
        text="How are they asking you to pay (bank transfer, cash, card)? "
        "Has anyone asked for money before a viewing?",
    ),
    Action(
        id="act_deposit_scheme",
        check_id=CheckId.DEPOSIT_PROTECTION,
        kind=ActionKind.QUESTION,
        text="Which government-approved scheme will your deposit be protected in? "
        "Ask for the scheme name.",
    ),
]


def stub_actions(case: Case, max_actions: int) -> list[Action]:
    """Up to `max_actions` unasked stub actions whose check is still UNVERIFIED."""
    asked = {a.id for a in case.actions}
    unverified = {c.id for c in case.checks if c.state == CheckState.UNVERIFIED}
    candidates = [a for a in _STUB_ACTIONS if a.id not in asked and a.check_id in unverified]
    return [a.model_copy(deep=True) for a in candidates[:max_actions]]
