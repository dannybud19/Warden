"""Rule-based comparison of facts across sources."""

import re

from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Category,
    CheckId,
    EvidenceKind,
    EvidenceRef,
    Fact,
    FactKey,
    Finding,
    Severity,
)

POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
NAME_NOISE = {"ltd", "limited", "lettings", "plc", "llp"}

# key -> (label, check, severity)
RULES: dict[FactKey, tuple[str, CheckId, Severity]] = {
    FactKey.ADDRESS: ("Address", CheckId.CONTRACT_CONSISTENCY, Severity.CRITICAL),
    FactKey.LANDLORD_NAME: ("Landlord name", CheckId.LANDLORD_IDENTITY, Severity.HIGH),
    FactKey.COMPANY_NUMBER: ("Company number", CheckId.LANDLORD_IDENTITY, Severity.HIGH),
    FactKey.RENT_PCM: ("Rent", CheckId.CONTRACT_CONSISTENCY, Severity.HIGH),
    FactKey.DEPOSIT: ("Deposit", CheckId.CONTRACT_CONSISTENCY, Severity.MEDIUM),
}


def facts_from_case(case: Case) -> list[Fact]:
    """Facts the student already gave us: listing and landlord fields."""
    facts: list[Fact] = []
    if case.listing:
        if case.listing.address:
            facts.append(
                Fact(
                    key=FactKey.ADDRESS, value=case.listing.address, source="listing", agent="case"
                )
            )
        if case.listing.rent_pcm is not None:
            facts.append(
                Fact(
                    key=FactKey.RENT_PCM,
                    value=str(case.listing.rent_pcm),
                    source="listing",
                    agent="case",
                )
            )
        if case.listing.deposit is not None:
            facts.append(
                Fact(
                    key=FactKey.DEPOSIT,
                    value=str(case.listing.deposit),
                    source="listing",
                    agent="case",
                )
            )
    if case.landlord:
        if case.landlord.name:
            facts.append(
                Fact(
                    key=FactKey.LANDLORD_NAME,
                    value=case.landlord.name,
                    source="landlord",
                    agent="case",
                )
            )
        if case.landlord.company_number:
            facts.append(
                Fact(
                    key=FactKey.COMPANY_NUMBER,
                    value=case.landlord.company_number,
                    source="landlord",
                    agent="case",
                )
            )
    return facts


def normalise(key: FactKey, value: str) -> str:
    """Canonical form of a fact value so equal facts compare equal."""
    match key:
        case FactKey.RENT_PCM | FactKey.DEPOSIT:
            return re.sub(r"\D", "", value)
        case FactKey.COMPANY_NUMBER:
            number = re.sub(r"\s", "", value).upper()
            # NOTE: only all-digit numbers are zero-padded; prefixed ones (SC, NI) are 8 chars.
            return number.zfill(8) if number.isdigit() else number
        case FactKey.ADDRESS:
            match_ = POSTCODE_RE.search(value)
            if match_:
                return re.sub(r"\s", "", match_.group(0)).upper()
            return re.sub(r"[^a-z0-9]", "", value.lower())
        case FactKey.LANDLORD_NAME:
            words = re.sub(r"[^\w\s]", "", value.lower()).split()
            return " ".join(w for w in words if w not in NAME_NOISE)
        case _:
            return value.strip().lower()


def _comparable(fact: Fact) -> bool:
    """An address is compared only when it has a full postcode.

    Listings and students often give a partial address ("Elm Road, London, W12", "Flat 2, 41 Mile
    End Road"). Compared as text with a contract's postcode it always differs, which raised a
    critical address hard flag and closed genuine cases as likely scams.
    """
    return fact.key != FactKey.ADDRESS or POSTCODE_RE.search(fact.value) is not None


def _contract_ids(case: Case) -> set[str]:
    return {e.id for e in case.evidence if e.kind == EvidenceKind.CONTRACT}


def _address_is_hard_flag(case: Case, facts: list[Fact]) -> bool:
    """A contract address that differs from the listing address."""
    contracts = _contract_ids(case)
    listing = {normalise(f.key, f.value) for f in facts if f.source == "listing"}
    contract = {normalise(f.key, f.value) for f in facts if f.source in contracts}
    # NOTE: stricter than the plan's wording: a hard flag needs the contract and the listing
    # themselves to disagree, not merely some other source (e.g. chat) disagreeing with one.
    return bool(listing and contract and listing.isdisjoint(contract))


def compare(case: Case, reports: dict[str, AgentReport]) -> list[Finding]:
    """One CONSISTENCY finding per fact key that has 2+ distinct normalised values."""
    facts = facts_from_case(case)
    for report in reports.values():
        if report.status == AgentStatus.OK:
            facts.extend(report.facts)

    findings: list[Finding] = []
    for key, (label, check_id, severity) in RULES.items():
        keyed = [f for f in facts if f.key == key and _comparable(f)]
        if len({normalise(key, f.value) for f in keyed}) < 2:
            continue
        hard = key == FactKey.ADDRESS and _address_is_hard_flag(case, keyed)
        findings.append(
            Finding(
                id=f"crosscheck:{key.value}",
                agent="crosscheck",
                check_id=check_id,
                title=f"{label} differs between sources",
                detail="; ".join(f"{f.value!r} (from {f.source})" for f in keyed),
                category=Category.CONSISTENCY,
                severity=severity,
                confidence=0.9,
                evidence=[EvidenceRef(evidence_id=f.source, quote=f.value) for f in keyed],
                hard_flag=hard,
            )
        )
    return findings
