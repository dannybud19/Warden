"""Every flag and clear this agent can raise: one place for check, category, severity and wording.

Both the rules and the LLM pass look flags up here, so the model never chooses a severity.
The full reasoning for each row is in `red_flags.md`.
"""

from dataclasses import dataclass

from app.contracts import Category, CheckId, Severity

AGENT = "message_checker"
LLM_MAX_CONFIDENCE = 0.8
LLM_MIN_CONFIDENCE = 0.5


@dataclass(frozen=True)
class Spec:
    id: str
    check: CheckId
    category: Category
    severity: Severity
    confidence: float
    title: str
    detail: str
    clears: bool = False


def _flag(
    id_: str,
    check: CheckId,
    category: Category,
    severity: Severity,
    confidence: float,
    title: str,
    detail: str,
) -> Spec:
    return Spec(id_, check, category, severity, confidence, title, detail)


def _clear(
    id_: str, check: CheckId, category: Category, confidence: float, title: str, detail: str
):
    return Spec(id_, check, category, Severity.INFO, confidence, title, detail, clears=True)


_PAY, _VIEW, _ID, _LET = (
    CheckId.PAYMENT_SAFETY,
    CheckId.IN_PERSON_VIEWING,
    CheckId.LANDLORD_IDENTITY,
    CheckId.RIGHT_TO_LET,
)

_SPECS = [
    # --- raised by rules (and by the LLM for paraphrases) ---
    _flag(
        "payment_before_viewing",
        _PAY,
        Category.PAYMENT,
        Severity.CRITICAL,
        0.7,
        "Money requested before any viewing",
        "The agent asks for money before you have seen the property in person. "
        "Paying before a viewing is the most common way students lose a deposit.",
    ),
    _flag(
        "untraceable_payment",
        _PAY,
        Category.PAYMENT,
        Severity.CRITICAL,
        0.95,
        "Untraceable payment method requested",
        "Money transfer services, gift cards, pre-paid cards and crypto cannot be traced or "
        "refunded. Genuine landlords and agencies do not take rent or deposits this way.",
    ),
    _flag(
        "personal_emoney_transfer",
        _PAY,
        Category.PAYMENT,
        Severity.CRITICAL,
        0.6,
        "Transfer to a personal e-money account",
        "The payment is to a personal Revolut, Wise or Monzo account rather than a business "
        "account, which is hard to trace or recover.",
    ),
    _flag(
        "overseas_bank_account",
        _PAY,
        Category.PAYMENT,
        Severity.HIGH,
        0.8,
        "Payment to a non-UK bank account",
        "The bank details are not for a UK account. A London let should be paid into a UK "
        "account, and money sent abroad is very hard to recover.",
    ),
    _flag(
        "lookalike_link",
        _PAY,
        Category.PAYMENT,
        Severity.HIGH,
        0.85,
        "Link imitates a well-known site",
        "The link uses the name of a known rental or booking site but is not on that site's "
        "real address. Lookalike pages are used to take payments and card details.",
    ),
    _flag(
        "overpayment_refund",
        _PAY,
        Category.PAYMENT,
        Severity.CRITICAL,
        0.85,
        "Overpayment and refund request",
        "Paying more than is owed and refunding the difference is a known scam pattern: the "
        "original payment bounces or is reversed after you send the refund.",
    ),
    _flag(
        "pose_as_buyer",
        _PAY,
        Category.PAYMENT,
        Severity.CRITICAL,
        0.85,
        "Asked to misdescribe yourself or the payment",
        "You are asked to pretend to be someone else, or to label the payment as friends and "
        "family. That removes the payment protection you would otherwise have.",
    ),
    _flag(
        "landlord_abroad",
        _VIEW,
        Category.PROPERTY,
        Severity.HIGH,
        0.8,
        "Landlord says they are away and cannot meet",
        "The agent says they are abroad or unavailable, or that someone else will pass on the "
        "keys once you have paid. This is the classic reason given for not showing a property.",
    ),
    _flag(
        "viewing_refused",
        _VIEW,
        Category.PROPERTY,
        Severity.HIGH,
        0.85,
        "In-person viewing refused",
        "The agent will not let you, or someone you trust, see the property in person before "
        "you commit.",
    ),
    _flag(
        "off_platform_move",
        _VIEW,
        Category.IDENTITY,
        Severity.LOW,
        0.6,
        "Conversation moved off the listing platform",
        "The agent asks to continue by private email or chat. Listing platforms cannot "
        "monitor or protect conversations that leave their site.",
    ),
    # --- raised by the LLM only ---
    _flag(
        "escrow_story",
        _PAY,
        Category.PAYMENT,
        Severity.CRITICAL,
        0.7,
        "A third party will 'hold' your money",
        "Airbnb, Booking.com, TripAdvisor and couriers do not hold deposits for private "
        "long-term lets. This story is used to make an up-front payment feel safe.",
    ),
    _flag(
        "id_documents_early",
        _ID,
        Category.IDENTITY,
        Severity.HIGH,
        0.7,
        "Identity documents wanted before a viewing",
        "Passports, bank statements and payslips are asked for before you have seen the "
        "property. These can be used for identity theft.",
    ),
    _flag(
        "identity_inconsistent",
        _ID,
        Category.IDENTITY,
        Severity.MEDIUM,
        0.7,
        "The agent's identity changes",
        "The name, company or role the agent gives is not consistent across the conversation.",
    ),
    _flag(
        "refuses_details",
        _ID,
        Category.IDENTITY,
        Severity.MEDIUM,
        0.7,
        "Avoids giving verifiable details",
        "When asked for a company number, office address or proof of ownership, the agent "
        "does not answer.",
    ),
    _flag(
        "no_checks_needed",
        _LET,
        Category.PROPERTY,
        Severity.MEDIUM,
        0.7,
        "No references, contract or checks needed",
        "Genuine landlords must check your right to rent and normally want references and a "
        "contract. Skipping all of this suggests the person may not be able to let the property.",
    ),
    # --- clears ---
    _clear(
        "viewing_completed",
        _VIEW,
        Category.PROPERTY,
        0.7,
        "An in-person viewing has taken place",
        "The messages show the property has already been seen in person.",
    ),
    _clear(
        "viewing_offered",
        _VIEW,
        Category.PROPERTY,
        0.4,
        "An in-person viewing was offered",
        "The agent offered a specific time or place for an in-person viewing.",
    ),
    _clear(
        "payment_after_viewing_via_portal",
        _PAY,
        Category.PAYMENT,
        0.5,
        "Payment only after a viewing, through a traceable route",
        "Money was only mentioned after the viewing, and is taken through a portal, card or "
        "the listing platform rather than a direct transfer.",
    ),
    _clear(
        "deposit_scheme_named",
        CheckId.DEPOSIT_PROTECTION,
        Category.DOCUMENT,
        0.4,
        "A deposit protection scheme is named",
        "The agent names a government-approved deposit scheme. Check the certificate once "
        "you receive it.",
    ),
]

SPECS: dict[str, Spec] = {s.id: s for s in _SPECS}

# Checks the LLM may attach an `other` flag to (pressure belongs to emotion_classifier).
OTHER_CATEGORY: dict[CheckId, Category] = {
    CheckId.LANDLORD_IDENTITY: Category.IDENTITY,
    CheckId.PAYMENT_SAFETY: Category.PAYMENT,
    CheckId.RIGHT_TO_LET: Category.PROPERTY,
    CheckId.IN_PERSON_VIEWING: Category.PROPERTY,
    CheckId.CONTRACT_CONSISTENCY: Category.CONSISTENCY,
    CheckId.DEPOSIT_PROTECTION: Category.DOCUMENT,
    CheckId.FAIR_PRICE: Category.PRICING,
}
