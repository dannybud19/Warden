"""Deterministic red-flag rules over `case.messages`. Pure functions, no I/O.

Spec: `red_flags.md`. Anything a pattern can catch reliably lives here, not in the LLM pass.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.agents.message_checker.catalog import AGENT, SPECS, Spec
from app.contracts import Case, EvidenceRef, Fact, FactKey, Finding, Message, Severity

MAX_QUOTE = 200
MAX_REFS = 3
_I = re.IGNORECASE

# One-to-one replacements only, so match positions in the normalised text fit the original.
_TRANS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})
_BOUNDARY = re.compile(r"[.!?]+(?:\s+|$)|\n+")


@dataclass(frozen=True)
class Hit:
    """One message that supports a finding, with the exact text to quote."""

    message: Message
    quote: str


@dataclass
class RuleResult:
    findings: list[Finding] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)

    @property
    def fired(self) -> set[str]:
        return {f.id.split(":", 1)[1] for f in self.findings}


# ---------------------------------------------------------------- helpers


def norm(text: str) -> str:
    """Straighten curly quotes without changing the length of the text."""
    return text.translate(_TRANS)


def quote_around(text: str, start: int, end: int) -> str:
    """The sentence(s) of `text` that contain `start:end`, as an exact substring of `text`."""
    bounds = [m.end() for m in _BOUNDARY.finditer(text)]
    left = max((b for b in bounds if b <= start), default=0)
    right = min((b for b in bounds if b >= end), default=len(text))
    if right - left > MAX_QUOTE:
        left, right = start, min(len(text), start + MAX_QUOTE)
    return text[left:right].strip()


def parse_money(raw: str) -> int | None:
    """`1,384.00` -> 1384. The shared normaliser keeps digits only, so we parse here."""
    try:
        return round(float(raw.replace(",", "")))
    except ValueError:
        return None


def _search(pattern: re.Pattern[str], message: Message) -> Hit | None:
    m = pattern.search(norm(message.text))
    return Hit(message, quote_around(message.text, m.start(), m.end())) if m else None


def _hits(pattern: re.Pattern[str], messages: Iterable[Message]) -> list[Hit]:
    return [h for h in (_search(pattern, m) for m in messages) if h]


def finding(
    spec: Spec,
    hits: Sequence[Hit],
    *,
    confidence: float | None = None,
    hard_flag: bool = False,
    detail: str | None = None,
) -> Finding:
    """Build the one Finding for `spec`, citing up to MAX_REFS messages."""
    refs: list[EvidenceRef] = []
    for hit in hits:
        ref = EvidenceRef(evidence_id=hit.message.evidence_id, quote=hit.quote[:MAX_QUOTE])
        if ref not in refs:
            refs.append(ref)
    return Finding(
        id=f"{AGENT}:{spec.id}",
        agent=AGENT,
        check_id=spec.check,
        title=spec.title,
        detail=detail or spec.detail,
        category=spec.category,
        severity=spec.severity,
        confidence=spec.confidence if confidence is None else confidence,
        evidence=refs[:MAX_REFS],
        supports="cleared" if spec.clears else "suspicious",
        hard_flag=hard_flag,
    )


def reconcile(findings: Sequence[Finding]) -> list[Finding]:
    """Drop clears that a real flag on the same check contradicts, and the weaker viewing clear."""
    flagged = {
        f.check_id
        for f in findings
        if f.supports == "suspicious" and f.severity not in (Severity.LOW, Severity.INFO)
    }
    ids = {f.id for f in findings}
    kept: list[Finding] = []
    for f in findings:
        if f.supports == "cleared" and f.check_id in flagged:
            continue
        if f.id == f"{AGENT}:viewing_offered" and f"{AGENT}:viewing_completed" in ids:
            continue
        kept.append(f)
    return kept


# ---------------------------------------------------------------- patterns

_PAYMENT_WORD = re.compile(
    r"\b(deposit|holding fee|first month|rent in advance|bank details|sort code|"
    r"account (?:number|no)|payments?|transfer|pay|paid|fee)\b",
    _I,
)
_PAYMENT_INSTRUCTION = re.compile(
    r"\b(send|pay|transfer|wire)\b|\bto (?:hold|secure|reserve)\b|"
    r"\bonce\b.{0,60}\b(?:paid|received|cleared)\b|"
    r"\b(?:before|prior to) (?:the |a |any )?viewing\b|"
    r"\bI (?:only )?accept\b|\bup ?front\b|\bin advance\b|"
    r"\bwe take\b|\bis (?:payable|due|required)\b",
    _I,
)
_NO_PAYMENT_YET = re.compile(
    r"\b(?:no|not|nothing|never|don't|do not|won't)\b.{0,30}\b(?:pay|payment|deposit|money|"
    r"transfer)\b.{0,40}\b(?:until|before|unless)\b|"
    r"\b(?:pay|send|transfer)\b.{0,15}\b(?:nothing|no money)\b.{0,40}\b(?:until|before|unless)\b|"
    r"\bno (?:payment|deposit|money)\b.{0,20}\b(?:needed|required|yet)\b",
    _I,
)
# Each pattern also matches the masked form intake stores (app/intake/redact.py), since uploads
# arrive masked: sort code "**-**-56", account "****1234", IBAN "DE** **** **** 3000".
_SORT_CODE = re.compile(
    r"\b(\d{2})[- ](\d{2})[- ](\d{2})\b|\bsort ?code:? ?(\d{6})\b|(?<![\w*])\*\*-\*\*-(\d{2})\b", _I
)
_ACCOUNT_NO = re.compile(r"(?<![\d-])(\d{8})(?![\d-])|(?<![\w*])\*{4}(\d{4})(?!\d)")
_IBAN = re.compile(
    r"\b([A-Z]{2})(?:\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b|\*\* \*{4} \*{4} \d{4}\b)"
)
_SWIFT = re.compile(r"\b(swift|bic)\b", _I)
_HOLD_OR_KEYS = re.compile(r"\bto (?:hold|secure|reserve)\b|\bkeys?\b", _I)

_VIEWING_DONE_ANY = re.compile(
    r"\bthank(?:s| you) for (?:coming|visiting|viewing)\b|\bnice (?:to meet|meeting) you\b|"
    r"\b(?:good|great|lovely) to (?:see|meet) you\b",
    _I,
)
_VIEWING_DONE_STUDENT = re.compile(
    r"\b(?:I|we)(?:'ve| have)? (?:saw|seen|viewed|visited) (?:the |your |that |this )?"
    r"(?:flat|room|place|property|house|studio|it)\b(?! (?:on|online|in (?:the|your) ad))|"
    r"\bthank(?:s| you) for showing\b",
    _I,
)
_UNTRACEABLE = re.compile(
    r"\bwestern union\b|\bmoney ?gram\b|\bgift ?cards?\b|\bvouchers?\b|"
    r"\b(?:itunes|amazon|steam|google play|apple) (?:gift )?cards?\b|\bpre-?paid\b|"
    r"\bpaysafe(?:card)?\b|\bcrypto(?:currency)?\b|\bbitcoin\b|\bbtc\b|\busdt\b|\bethereum\b|"
    r"\bcash (?:in|by) (?:the )?post\b",
    _I,
)
_EMONEY = re.compile(
    r"\b(?:revolut|monzo)\b|\b(?:via|by|through|on|using|with|my) wise\b|"
    r"\bwise (?:account|transfer|app)\b",
    _I,
)
_COMPANY_PAYEE = re.compile(r"\b(ltd|limited|llp|plc|lettings|estates|properties)\b", _I)
_OVERPAYMENT = re.compile(
    r"\boverpa(?:id|y|yment)\b|\b(?:refund|return|send)\b.{0,25}\bthe (?:difference|balance|"
    r"rest|excess)\b|\bpay (?:a bit |a little )?(?:more|extra) and\b",
    _I,
)
_POSE = re.compile(
    r"\b(?:say|tell them|pretend|pose|act)\b.{0,40}\b(?:buyer|purchas\w*|friend|relative|"
    r"family member|cousin)\b|\bfriends (?:and|&) family\b|\bfamily (?:and|&) friends\b|\bF&F\b",
    _I,
)
# Being away is not a red flag on its own: many genuine landlords live abroad and use an agent.
# `landlord_abroad` needs both _AWAY (or a key hand-off) and a sign that nobody will show the flat.
_AWAY = re.compile(
    r"\b(?:abroad|overseas|offshore)\b|\b(?:out of|outside|not in) the (?:country|uk)\b",
    _I,
)
_KEYS_HANDOFF = re.compile(
    r"\b(?:courier|post|mail|dhl|fedex|ups)\b.{0,40}\bkeys?\b|"
    r"\bkeys?\b.{0,40}\b(?:courier|by post|mail|dhl|fedex|ups)\b|"
    r"\b(?:agent|colleague|friend|lawyer|solicitor|brother|sister|cousin)\b.{0,40}"
    r"\b(?:give|hand|deliver|send|pass)\b.{0,30}\bkeys?\b",
    _I,
)
# someone else offers to show the property: the genuine way to handle being away
_PROXY_VIEWING = re.compile(
    r"\b(?:agent|colleague|friend|brother|sister|cousin|neighbour|neighbor|caretaker|"
    r"property manager|letting agent|someone)\b.{0,40}"
    r"\b(?:show you|show it|let you in|do (?:the|a) viewing|meet you|take you round)\b",
    _I,
)
_REFUSED = re.compile(
    r"\bviewings?\b.{0,30}(?:not|n't|no longer)\b.{0,15}\b(?:possible|available|allowed)\b|"
    r"(?:\bcannot|\bcan't|\bcan not|\bunable to|\bnot able to|\bwon't be able to)\b.{0,25}"
    r"\b(?:show|view|viewing|meet|let you see)\b|\bno viewings?\b|"
    r"\b(?:video|virtual)(?: tour| viewing| call)? only\b",
    _I,
)
_NOT_POSSIBLE = re.compile(r"\b(?:not|isn't|is not) possible\b|\bimpossible\b", _I)
_ASKED_TO_VIEW = re.compile(r"\b(?:view|viewing|see|visit|look at|come (?:round|over|by))\b", _I)
_OFF_PLATFORM = re.compile(
    r"\b(?:whats ?app|telegram|signal|viber|text|e-?mail|message|contact) me (?:directly|on|at)\b|"
    r"\bmy (?:personal|private) (?:e-?mail|number)\b|\boff (?:the )?(?:platform|site|app)\b|"
    r"\boutside (?:of )?(?:the )?(?:platform|spareroom|openrent|rightmove)\b",
    _I,
)
_VIEWING_WORD = re.compile(r"\b(?:slots?|viewings?|view|come (?:and|to) see|show you)\b", _I)
_DAY_OR_TIME = re.compile(
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|\b\d{1,2}[:.]\d{2}\b|\b\d{1,2} ?(?:am|pm)\b|"
    r"\bour office is\b",
    _I,
)
_PORTAL = re.compile(
    r"\b(?:portal|online payment|by card|card payment|at (?:the|our) office|"
    r"through (?:spareroom|openrent|rightmove|the platform|the site))\b",
    _I,
)
_SCHEME = re.compile(
    r"\b(?:TDS|DPS|my ?deposits|tenancy deposit scheme|deposit protection (?:service|scheme))\b", _I
)
_URLISH = re.compile(r"(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})(?:/\S*)?", _I)
_BRANDS: dict[str, tuple[str, ...]] = {
    "airbnb": ("airbnb.com", "airbnb.co.uk"),
    "spareroom": ("spareroom.co.uk", "spareroom.com"),
    "rightmove": ("rightmove.co.uk",),
    "zoopla": ("zoopla.co.uk",),
    "openrent": ("openrent.co.uk", "openrent.com"),
    "booking-com": ("booking.com",),
    "booking.com": ("booking.com",),
}
_EMAIL = re.compile(r"\b[\w.+-]+@((?:[a-z0-9-]+\.)+[a-z]{2,})\b", _I)
_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", _I)
_ADDRESS_START = re.compile(r"\b(?:flat|room|apartment|apt|studio|unit)\b|\d", _I)
_AMOUNT = r"£\s?(\d[\d,]*(?:\.\d{1,2})?)"
_RENT = re.compile(
    _AMOUNT + r"\s*(?:pcm|p\.c\.m\.?|per (?:calendar )?month|a month|/ ?month|monthly|pm\b)|"
    r"\brent (?:is|of|will be|at)\s*" + _AMOUNT,
    _I,
)
_DEPOSIT = re.compile(
    r"(?<!holding )\bdeposit\b(?: (?:of|is|will be))?\s*"
    + _AMOUNT
    + r"|"
    + _AMOUNT
    + r"\s+(?:tenancy |security |damage )?deposit\b",
    _I,
)


# ---------------------------------------------------------------- rule pieces


def _agent(messages: Sequence[Message]) -> list[Message]:
    return [m for m in messages if m.sender == "agent"]


def is_payment_request(message: Message) -> bool:
    """An agent message that asks for money: a payment word plus an instruction or bank details."""
    text = norm(message.text)
    if not _PAYMENT_WORD.search(text) or _NO_PAYMENT_YET.search(text):
        return False
    return bool(_PAYMENT_INSTRUCTION.search(text) or _SORT_CODE.search(text) or _IBAN.search(text))


def viewing_done_index(messages: Sequence[Message]) -> int | None:
    """Index of the first message showing an in-person viewing has happened, if any."""
    for i, m in enumerate(messages):
        if _search(_VIEWING_DONE_ANY, m):
            return i
        if m.sender == "student" and _search(_VIEWING_DONE_STUDENT, m):
            return i
    return None


def _refusal_hits(messages: Sequence[Message]) -> list[Hit]:
    hits: list[Hit] = []
    asked = False
    for m in messages:
        if m.sender == "student":
            asked = asked or bool(_ASKED_TO_VIEW.search(norm(m.text)))
            continue
        if m.sender != "agent":
            continue
        hit = _search(_REFUSED, m) or (_search(_NOT_POSSIBLE, m) if asked else None)
        if hit:
            hits.append(hit)
    return hits


def lookalike_hosts(text: str) -> list[tuple[str, int, int]]:
    """(host, start, end) for each link whose host uses a brand name on someone else's domain."""
    out: list[tuple[str, int, int]] = []
    for m in _URLISH.finditer(text):
        host = m.group(1).lower().removeprefix("www.")
        for brand, real in _BRANDS.items():
            if brand in host and not any(host == d or host.endswith("." + d) for d in real):
                out.append((host, m.start(), m.end()))
                break
    return out


def _lookalike_hits(messages: Iterable[Message]) -> list[Hit]:
    hits: list[Hit] = []
    for m in messages:
        found = lookalike_hosts(norm(m.text))
        if found:
            _, start, end = found[0]
            hits.append(Hit(m, quote_around(m.text, start, end)))
    return hits


def _emoney_hits(messages: Iterable[Message]) -> list[Hit]:
    return [
        hit
        for m in messages
        if is_payment_request(m)
        and not _COMPANY_PAYEE.search(norm(m.text))
        and (hit := _search(_EMONEY, m))
    ]


def _overseas_bank_hits(messages: Iterable[Message]) -> list[Hit]:
    hits: list[Hit] = []
    for m in messages:
        text = norm(m.text)
        iban = next((i for i in _IBAN.finditer(text) if i.group(1) != "GB"), None)
        match = iban or (_SWIFT.search(text) if _PAYMENT_WORD.search(text) else None)
        if match:
            hits.append(Hit(m, quote_around(m.text, match.start(), match.end())))
    return hits


# ---------------------------------------------------------------- facts


def mask_bank(text: str) -> str | None:
    """Bank details in `text`, masked to the last digits. None when there are none."""
    iban = _IBAN.search(text)
    if iban:
        return f"IBAN {iban.group(1)}** ****{re.sub(r'\s', '', iban.group(0))[-4:]}"
    sort = _SORT_CODE.search(text)
    account = _ACCOUNT_NO.search(text)
    last4 = (account.group(1) or account.group(2))[-4:] if account else ""
    if sort and account:
        last2 = sort.group(3) or sort.group(5) or sort.group(4)[-2:]
        return f"sort **-**-{last2}, account ****{last4}"
    if account and re.search(r"\baccount\b", text, _I):
        return f"account ****{last4}"
    return None


def address_text(text: str, pc_start: int, pc_end: int) -> str:
    """The address ending in the postcode at `pc_start:pc_end`: from "Flat"/the house number on."""
    sentence_start = max((b.end() for b in _BOUNDARY.finditer(text, 0, pc_start)), default=0)
    lead = _ADDRESS_START.search(text, sentence_start, pc_start)
    return text[lead.start() if lead else pc_start : pc_end].strip()


def extract_facts(case: Case) -> list[Fact]:
    """Facts stated outright in the messages: bank account, email domain, address, rent, deposit."""
    seen: set[tuple[FactKey, str]] = set()
    facts: list[Fact] = []

    def add(key: FactKey, value: str, source: str) -> None:
        if (key, value) not in seen:
            seen.add((key, value))
            facts.append(Fact(key=key, value=value, source=source, agent=AGENT))

    if case.landlord and case.landlord.email and (m := _EMAIL.search(case.landlord.email)):
        add(FactKey.EMAIL_DOMAIN, m.group(1).lower(), "landlord")

    address_found = False
    for msg in case.messages:
        text = norm(msg.text)
        # NOTE: only the first postcode becomes the address fact. Later ones are often the
        # agency's office, and the crosscheck would report those as an address mismatch.
        if not address_found and (pc := _POSTCODE.search(text)):
            address_found = True
            add(FactKey.ADDRESS, address_text(msg.text, pc.start(), pc.end()), msg.evidence_id)
        if msg.sender != "agent":
            continue
        if bank := mask_bank(text):
            add(FactKey.BANK_ACCOUNT, bank, msg.evidence_id)
        for email in _EMAIL.finditer(text):
            add(FactKey.EMAIL_DOMAIN, email.group(1).lower(), msg.evidence_id)
        if rent := _RENT.search(text):
            value = parse_money(rent.group(1) or rent.group(2))
            if value:
                add(FactKey.RENT_PCM, str(value), msg.evidence_id)
        if dep := _DEPOSIT.search(text):
            value = parse_money(dep.group(1) or dep.group(2))
            if value:
                add(FactKey.DEPOSIT, str(value), msg.evidence_id)
    return facts


# ---------------------------------------------------------------- entry point


def run_rules(case: Case) -> RuleResult:
    """Every rule finding and fact for this case. Clears are reconciled against the flags."""
    messages = case.messages
    agent = _agent(messages)
    found: list[Finding] = []

    def flag(
        spec_id: str,
        hits: Sequence[Hit],
        *,
        confidence: float | None = None,
        hard_flag: bool = False,
    ) -> None:
        if hits:
            spec = SPECS[spec_id]
            found.append(finding(spec, hits, confidence=confidence, hard_flag=hard_flag))

    away = _hits(_AWAY, agent)
    handoff = _hits(_KEYS_HANDOFF, agent)
    refused = _refusal_hits(messages)
    proxy = _hits(_PROXY_VIEWING, agent)
    # away is a concern only when nobody will show the flat: a refusal, or keys only after payment
    no_one_shows = (refused or handoff) and not proxy
    abroad = [*handoff, *refused, *away] if (away or handoff) and no_one_shows else []
    done = viewing_done_index(messages)

    # payment before viewing: explicit (hard) when a viewing is ruled out or money buys the keys
    requests = [
        m
        for i, m in enumerate(messages)
        if m.sender == "agent" and is_payment_request(m) and (done is None or i < done)
    ]
    if requests:
        explicit = bool(away or handoff or refused) or any(
            _HOLD_OR_KEYS.search(norm(m.text)) for m in requests
        )
        flag(
            "payment_before_viewing",
            [Hit(m, quote_around(m.text, 0, len(m.text))) for m in requests],
            confidence=0.9 if explicit else 0.7,
            hard_flag=explicit,
        )

    flag("untraceable_payment", _hits(_UNTRACEABLE, agent), hard_flag=True)
    flag("personal_emoney_transfer", _emoney_hits(agent))
    flag("overseas_bank_account", _overseas_bank_hits(agent))
    flag("lookalike_link", _lookalike_hits(agent))
    flag("overpayment_refund", _hits(_OVERPAYMENT, agent))
    flag("pose_as_buyer", _hits(_POSE, agent))
    flag("landlord_abroad", abroad)
    flag("viewing_refused", refused)
    flag("off_platform_move", _hits(_OFF_PLATFORM, agent))

    # clears
    if done is not None:
        done_msg = messages[done]
        hit = _search(_VIEWING_DONE_ANY, done_msg) or _search(_VIEWING_DONE_STUDENT, done_msg)
        flag("viewing_completed", [hit] if hit else [])
        after = [m for m in messages[done:] if m.sender == "agent" and is_payment_request(m)]
        flag("payment_after_viewing_via_portal", _hits(_PORTAL, after))
    flag(
        "viewing_offered",
        [
            h
            for m in agent
            if _VIEWING_WORD.search(norm(m.text)) and (h := _search(_DAY_OR_TIME, m))
        ],
    )
    flag("deposit_scheme_named", _hits(_SCHEME, agent))

    return RuleResult(findings=reconcile(found), facts=extract_facts(case))
