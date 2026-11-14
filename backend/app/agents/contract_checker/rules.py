"""Reproducible calculations and conservative contract-local checks."""

import hashlib
import re
from datetime import date
from decimal import ROUND_DOWN, Decimal

from app.agents.contract_checker.documents import cite, cite_all
from app.agents.contract_checker.models import (
    Candidate,
    Citation,
    Document,
    Issue,
    MoneyTerm,
    Question,
    Quote,
    ReviewContext,
    RuleId,
)
from app.agents.contract_checker.rulebook import Rulebook

MONEY = r"(?:\u00a3|GBP\s*)\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)(?!\d|[,.]\d)"
REFORM_DATE = date(2026, 5, 1)


def money_values(text: str) -> set[Decimal]:
    """Parse explicit sterling amounts without losing decimal places."""
    return {Decimal(m.group(1).replace(",", "")) for m in re.finditer(MONEY, text, re.I)}


def frequency(text: str) -> str:
    """Recognise unambiguous rent frequencies without converting the amount."""
    if re.search(r"per calendar month|\bpcm\b|per month|monthly", text, re.I):
        return "month"
    if re.search(r"per week|\bpw\b|weekly", text, re.I):
        return "week"
    if re.search(r"per year|per annum|annually|annual rent|yearly", text, re.I):
        return "year"
    return "unknown"


def extract_money(document: Document) -> list[MoneyTerm]:
    """Recognise explicit labelled amounts; semantic extraction handles other wording."""
    terms: list[MoneyTerm] = []
    patterns = (
        ("holding_deposit", r"\bholding\s+deposit"),
        ("deposit", r"(?<!holding )\b(?:(?:tenancy|security)\s+)?deposit"),
        ("advance_rent", r"\b(?:advance rent|rent in advance)"),
        ("rent", r"\b(?:monthly |weekly |annual )?rent"),
    )
    for segment in document.segments:
        for kind, label in patterns:
            pattern = label + r"\s*(?:is|of|:|=)?\s*" + MONEY
            for match in re.finditer(pattern, segment.text, re.I):
                # A semantic label must not be split into a second kind of payment.
                if kind == "rent" and re.search(
                    r"advance\s*$|holding\s*$", segment.text[: match.start()], re.I
                ):
                    continue
                if kind == "deposit" and re.search(
                    r"holding\s*$", segment.text[: match.start()], re.I
                ):
                    continue
                snippet = segment.text[match.start() : match.start() + 190]
                terms.append(
                    MoneyTerm.model_validate(
                        {
                            "kind": kind,
                            "amount": match.group(1).replace(",", ""),
                            "frequency": frequency(snippet) if kind == "rent" else "one_off",
                            "evidence": {"segment_id": segment.id, "quote": snippet},
                        }
                    )
                )
    return terms


def validate_money(document: Document, terms: list[MoneyTerm]) -> tuple[list[MoneyTerm], int]:
    """Reject invented amounts and frequencies; deduplicate identical observations."""
    valid: list[MoneyTerm] = []
    dropped = 0
    seen: set[tuple[str, Decimal, str, str]] = set()
    for term in terms:
        ref = cite(document, term.evidence)
        segment = next((s for s in document.segments if s.id == term.evidence.segment_id), None)
        if (
            ref is None
            or term.amount not in money_values(term.evidence.quote)
            or segment is None
            or term.amount not in money_values(segment.text)
        ):
            dropped += 1
            continue
        if term.kind == "rent":
            observed = frequency(term.evidence.quote)
            if observed == "unknown":
                observed = frequency(segment.text)
            if observed != "unknown" and term.frequency != observed:
                dropped += 1
                continue
        key = (term.kind, term.amount, term.frequency, term.evidence.segment_id)
        if key not in seen:
            seen.add(key)
            valid.append(term)
    return valid, dropped


def annual_rent(term: MoneyTerm) -> Decimal | None:
    """Return annual rent exactly for supported payment periods."""
    factor = {"month": 12, "week": 52, "year": 1}.get(term.frequency)
    return term.amount * factor if factor and term.amount > 0 else None


def scope_uncertainty(context: ReviewContext, rule: RuleId, book: Rulebook) -> list[str]:
    """Identify assumptions that prevent a definitive legal conclusion."""
    if rule in {RuleId.CONFLICT, RuleId.SCHEDULE}:
        return []
    uncertainty: list[str] = []
    if context.jurisdiction != "england":
        uncertainty.append("Confirm that the rented property is in England.")
    if context.tenancy_type != "ordinary_private":
        uncertainty.append(
            "Confirm this is an ordinary private tenancy, not an excluded arrangement."
        )
    effective = book.rules[rule].effective_from
    if effective and context.assessment_date < effective:
        uncertainty.append(f"This rule is not applicable before {effective.isoformat()}.")
    if context.assessment_date > book.verified_on:
        uncertainty.append(f"Legal sources were last verified on {book.verified_on.isoformat()}.")
    if rule in {RuleId.ADVANCE, RuleId.NOTICE} and (
        context.agreement_date is None or context.agreement_date < REFORM_DATE
    ):
        uncertainty.append("Confirm whether the agreement was made on or after 1 May 2026.")
    return uncertainty


def question_for(rule: RuleId) -> Question:
    """Select a focused question with an explicit effect on the analysis."""
    content = {
        RuleId.DEPOSIT: (
            "What rent period and tenancy does the deposit cover, and can the amount be revised?",
            "The cap calculation needs the rent and deposit for the same tenancy.",
            "An applicable calculation or revised deposit clause settles the amount issue.",
        ),
        RuleId.HOLDING: (
            "Is this a holding deposit, and what is the rent for the tenancy it reserves?",
            "A holding deposit has a different cap from a tenancy deposit.",
            "The payment type and applicable amount are documented or corrected.",
        ),
        RuleId.FEES: (
            "What is this charge for, is it compulsory, and what evidence supports any exception?",
            "The purpose, trigger and actual costs determine whether an exception applies.",
            "The charge is removed or its permitted purpose and required evidence are established.",
        ),
        RuleId.ADVANCE: (
            "When was the agreement made, have both parties signed, and when is this rent due?",
            "Signing, agreement date and payment stage determine the applicable advance-rent rule.",
            "Dated terms establish permitted timing and amount, or the requirement changes.",
        ),
        RuleId.STRUCTURE: (
            "Can the landlord explain this term under the current periodic tenancy rules?",
            "An old template or transitional situation can change how the clause should be read.",
            "An applicable explanation or corrected operative clause addresses the concern.",
        ),
        RuleId.NOTICE: (
            "When was this tenancy agreed, and can the tenant notice clause be corrected?",
            "The date and whether this is tenant notice determine the relevant limit.",
            "The applicable tenant notice entitlement is documented consistently.",
        ),
        RuleId.CONFLICT: (
            "Which of these clauses governs, and is there an explicit amendment resolving them?",
            "An amendment or different scope may explain an apparent internal contradiction.",
            "The supplied terms unambiguously state the operative obligation.",
        ),
        RuleId.SCHEDULE: (
            "Can you supply the schedule or appendix referenced by this clause?",
            "Its contents may change the obligations or exceptions being reviewed.",
            "The referenced material is supplied and the affected clauses are rechecked.",
        ),
        RuleId.OBLIGATION: (
            "Can the landlord explain the scope and legal basis of this obligation or amend it?",
            "Exceptions and responsibility for actual damage can change the interpretation.",
            "Supporting terms establish a permitted obligation or the clause is corrected.",
        ),
    }
    text, why, resolves = content[rule]
    return Question(
        id=f"contract_checker:question:{rule.value}",
        rule_id=rule,
        text=text,
        why=why,
        resolves_when=resolves,
    )


def make_issue(
    rule: RuleId,
    title: str,
    explanation: str,
    evidence: list[Citation],
    context: ReviewContext,
    book: Rulebook,
    *,
    origin: str = "rule",
    uncertainty: list[str] | None = None,
    calculation: str | None = None,
    cleared: bool = False,
) -> Issue:
    """Assign stable clause-based IDs and keep priority distinct from confidence."""
    unknown = list(dict.fromkeys(scope_uncertainty(context, rule, book) + (uncertainty or [])))
    if rule == RuleId.SCHEDULE:
        unknown.append("The referenced material was not found in the supplied contract.")
    identity = "|".join(sorted({f"{ref.clause_id}@{ref.segment_id}" for ref in evidence}))
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:10]
    status = "conditional" if unknown else ("cleared" if cleared else "confirmed")
    priority = {
        RuleId.DEPOSIT: 85,
        RuleId.HOLDING: 75,
        RuleId.FEES: 80,
        RuleId.ADVANCE: 85,
        RuleId.STRUCTURE: 65,
        RuleId.NOTICE: 65,
        RuleId.CONFLICT: 80,
        RuleId.SCHEDULE: 45,
        RuleId.OBLIGATION: 75,
    }[rule]
    return Issue.model_validate(
        {
            "id": f"contract_checker:{rule.value}:{suffix}",
            "rule_id": rule,
            "status": status,
            "supports": "cleared" if status == "cleared" else "suspicious",
            "title": title,
            "explanation": explanation,
            "evidence": evidence,
            "legal_sources": book.references(rule),
            "assumptions": (
                ["Applicable ordinary private tenancy in England."]
                if book.rules[rule].sources
                else []
            ),
            "uncertainty": unknown,
            "importance": 0 if status == "cleared" else priority,
            "confidence": 0.5 if unknown else (0.95 if origin == "rule" else 0.75),
            "calculation": calculation,
            "question": None if status == "cleared" else question_for(rule),
            "origin": origin,
        }
    )


def check_amounts(
    document: Document, terms: list[MoneyTerm], context: ReviewContext, book: Rulebook
) -> list[Issue]:
    """Calculate deposit caps, preserving unrounded arithmetic and scope limitations."""
    rents = [term for term in terms if term.kind == "rent" and annual_rent(term) is not None]
    values = {annual_rent(term) for term in rents}
    issues: list[Issue] = []
    if len(values) > 1:
        refs = cite_all(document, [term.evidence for term in rents])
        if refs:
            issues.append(
                make_issue(
                    RuleId.CONFLICT,
                    "Different rent amounts appear in the contract",
                    "The quoted rent amounts do not agree after converting their stated periods.",
                    refs,
                    context,
                    book,
                    uncertainty=[
                        "An explicit amendment or different payment scope may explain this."
                    ],
                )
            )
    for kind, rule in (("deposit", RuleId.DEPOSIT), ("holding_deposit", RuleId.HOLDING)):
        payments = [term for term in terms if term.kind == kind]
        for payment in payments:
            refs = cite_all(document, [payment.evidence] + [term.evidence for term in rents])
            if not refs:
                continue
            unknown: list[str] = []
            if len(values) != 1:
                unknown.append("A single unambiguous annual rent has not been established.")
            if len({p.amount for p in payments}) > 1:
                unknown.append("Multiple deposit amounts need an operative-clause explanation.")
            if context.rent_basis != "whole_tenancy":
                unknown.append("Confirm that rent and deposit cover the same whole tenancy.")
            yearly = next(iter(values)) if len(values) == 1 else None
            if yearly is not None and yearly > 100_000:
                unknown.append("Annual rent exceeds this checker's supported GBP 100,000 scope.")
                yearly = None
            if yearly is None:
                issues.append(
                    make_issue(
                        rule,
                        "Deposit amount needs clarification",
                        "The amount cannot be checked against an applicable cap yet.",
                        refs,
                        context,
                        book,
                        uncertainty=unknown,
                    )
                )
                continue
            weeks = 1 if kind == "holding_deposit" else (5 if yearly < 50_000 else 6)
            # Compare cross-products: no rounding of the legal cap before deciding.
            above = payment.amount * 52 > yearly * weeks
            cap = (yearly * weeks / 52).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            calculation = (
                f"Annual rent GBP {yearly}; cap = {yearly} / 52 * {weeks} "
                f"(GBP {cap} rounded down to pennies); requested GBP {payment.amount}."
            )
            issues.append(
                make_issue(
                    rule,
                    "Deposit exceeds the calculated cap"
                    if above
                    else "Deposit is within the amount cap",
                    "This amount check does not verify deposit protection or authenticity.",
                    refs,
                    context,
                    book,
                    uncertainty=unknown,
                    calculation=calculation,
                    cleared=not above,
                )
            )
    return issues


def explicit_candidates(document: Document) -> list[Candidate]:
    """Find narrow, explicit clauses without depending on an LLM."""
    candidates: list[Candidate] = []
    for segment in document.segments:
        text = segment.text
        hits: list[tuple[RuleId, str, str]] = []
        negated = bool(re.search(r"\b(?:no|not|never|waived|removed)\b", text, re.I))
        if (
            not negated
            and re.search(r"(?:administration|admin|referencing|inventory) fee", text, re.I)
            and money_values(text)
        ):
            hits.append(
                (
                    RuleId.FEES,
                    "A separate administration or referencing charge is required",
                    "This charge may fall outside the permitted payment categories.",
                )
            )
        if not negated and re.search(
            r"(?:fixed term|term\s*:)\s*(?:of\s*)?\d+\s*months?", text, re.I
        ):
            hits.append(
                (
                    RuleId.STRUCTURE,
                    "A fixed tenancy term needs clarification",
                    "Check whether this clause purports to bind a covered periodic tenancy.",
                )
            )
        if (
            not negated
            and re.search(r"section\s+21", text, re.I)
            and re.search(
                r"(?:may|can|shall|will).*?(?:evict|possession|notice|terminate)", text, re.I
            )
        ):
            hits.append(
                (
                    RuleId.STRUCTURE,
                    "The contract claims a section 21 possession right",
                    "The current regime and any transitional proceedings need checking.",
                )
            )
        if not negated and re.search(
            r"tenant.*(?:3|4|5|6|three|four|five|six)\s*months?.*notice", text, re.I
        ):
            hits.append(
                (
                    RuleId.NOTICE,
                    "The tenant is asked for more than two months' notice",
                    "This may exceed the notice required under the applicable periodic regime.",
                )
            )
        if not negated and re.search(r"rent.*before.*(?:sign|signature)", text, re.I):
            hits.append(
                (
                    RuleId.ADVANCE,
                    "Rent is requested before signing",
                    "For covered new tenancies, rent cannot be requested before both parties sign.",
                )
            )
        for match in re.finditer(r"\b(?:schedule|appendix)\s+([A-Z0-9]+)\b", text, re.I):
            label = match.group(0)
            is_heading = re.match(r"^\s*" + re.escape(label) + r"(?:\s*[:.\-]|\s*$)", text, re.I)
            supplied = any(
                re.match(r"^\s*" + re.escape(label) + r"(?:\s*[:.\-]|\s*$)", s.text, re.I)
                for s in document.segments
            )
            if not is_heading and not supplied:
                hits.append(
                    (
                        RuleId.SCHEDULE,
                        f"Referenced {label} was not found",
                        "Its contents may qualify the obligations in the supplied contract.",
                    )
                )
        for rule, title, explanation in hits:
            # Large clauses are left to semantic extraction to choose a short relevant quote.
            if len(text) <= 200:
                candidates.append(
                    Candidate(
                        rule_id=rule,
                        title=title,
                        explanation=explanation,
                        evidence=[Quote(segment_id=segment.id, quote=text)],
                    )
                )
    return candidates


def check_candidates(
    document: Document,
    candidates: list[Candidate],
    context: ReviewContext,
    book: Rulebook,
    *,
    origin: str = "llm",
) -> tuple[list[Issue], int]:
    """Accept only supported, in-scope observations with valid evidence."""
    issues: list[Issue] = []
    dropped = 0
    for candidate in candidates:
        refs = cite_all(document, candidate.evidence)
        excluded = re.search(
            r"deposit.{0,30}(?:protect|scheme)|(?:protect|scheme).{0,30}deposit",
            candidate.title,
            re.I,
        )
        if (
            not refs
            or candidate.rule_id in {RuleId.DEPOSIT, RuleId.HOLDING}
            or excluded
            or (candidate.rule_id == RuleId.CONFLICT and len(refs) < 2)
        ):
            dropped += 1
            continue
        issues.append(
            make_issue(
                candidate.rule_id,
                candidate.title,
                candidate.explanation,
                refs,
                context,
                book,
                origin=origin,
                uncertainty=candidate.uncertainty,
            )
        )
    return issues, dropped


def check_advance_amounts(
    document: Document, terms: list[MoneyTerm], context: ReviewContext, book: Rulebook
) -> list[Issue]:
    """Compare explicit pre-tenancy advance rent with the applicable payment period."""
    rents = [t for t in terms if t.kind == "rent" and t.frequency in {"month", "week"}]
    issues: list[Issue] = []
    for payment in (t for t in terms if t.kind == "advance_rent"):
        refs = cite_all(document, [payment.evidence] + [t.evidence for t in rents])
        if not refs:
            continue
        limits = {t.amount * (4 if t.frequency == "week" else 1) for t in rents}
        if len(limits) != 1:
            issues.append(
                make_issue(
                    RuleId.ADVANCE,
                    "Advance rent amount needs clarification",
                    "An unambiguous monthly or weekly rent is needed for this calculation.",
                    refs,
                    context,
                    book,
                    uncertainty=["The applicable rent period is unresolved."],
                )
            )
            continue
        limit = next(iter(limits))
        if payment.amount <= limit:
            continue  # Amount compliance alone cannot verify the signing/payment timing.
        segment = next(s for s in document.segments if s.id == payment.evidence.segment_id)
        unknown = []
        if not re.search(r"before.{0,40}(?:start|move)|pre.tenancy", segment.text, re.I):
            unknown.append("Confirm this payment is required before the tenancy starts.")
        if context.rent_basis != "whole_tenancy":
            unknown.append("Confirm the rent and advance cover the same tenancy.")
        issues.append(
            make_issue(
                RuleId.ADVANCE,
                "Required advance rent exceeds the usual pre-tenancy limit",
                "The applicable dates, payment stage and tenancy scope must be established.",
                refs,
                context,
                book,
                uncertainty=unknown,
                calculation=f"Requested GBP {payment.amount}; usual period limit GBP {limit}.",
            )
        )
    return issues
