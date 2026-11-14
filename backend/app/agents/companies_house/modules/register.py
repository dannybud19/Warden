"""Register module: resolve the landlord's company and run the Companies House rules (plan 5).

Pure rules come first (functions over parsed models, taking `today` explicitly); the I/O
`run()` at the bottom resolves the company, fetches officers and disqualifications, and applies
them. Hard flags come only from here: a number that returns 404, or a dead company status.
"""

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import quote_plus

from app.agents.companies_house.ch_client import CompaniesHouseClient
from app.agents.companies_house.constants import (
    AGENT_NAME,
    CONF,
    DEAD_STATUSES,
    ESTABLISHED_MONTHS,
    EV_REGISTER,
    MAX_DISQUALIFIED_LOOKUPS,
    NAME_MATCH_GAP,
    NAME_MATCH_MIN,
    NAME_NUMBER_MISMATCH_MAX,
    PROPERTY_SIC,
    STRIKE_OFF_DETAILS,
    VIRTUAL_OFFICE_MARKERS,
    YOUNG_MONTHS,
)
from app.agents.companies_house.evidence import ch_ref, make_finding, register_url, student_refs
from app.agents.companies_house.models import (
    CompanyProfile,
    DisqualifiedHit,
    Fetch,
    Officer,
    OfficerList,
    Outcome,
    RegisterResult,
    ResolvedCompany,
    SearchHit,
)
from app.agents.companies_house.normalise import (
    months_between,
    name_score,
    normalise_name,
    normalise_number,
    parse_dob,
    person_matches_officer,
    strip_title,
)
from app.agents.companies_house.retry import Sleep
from app.contracts import Case, EvidenceRef, Fact, FactKey, Finding, Severity
from app.core.agent import AgentContext

SEARCH_PAGE_URL = (
    "https://find-and-update.company-information.service.gov.uk/search/companies?q={q}"
)
ASK_FOR_NUMBER = (
    "Ask the agent for their company number (shown on their website and paperwork by law)."
)


# --- subject of the rules --------------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """A resolved company plus how we got to it and what the student's own messages say."""

    profile: CompanyProfile
    number: str  # normalised
    matched_by: Literal["number", "name"]
    supplied_name: str | None = None  # the company name the student was given, if any
    student: tuple[EvidenceRef, ...] = ()  # student messages that name the company

    @property
    def name(self) -> str:
        return self.profile.company_name or self.supplied_name or self.number

    @property
    def url(self) -> str:
        return register_url(self.number)

    @property
    def status(self) -> str:
        return (self.profile.company_status or "").lower()


def _flag(value: bool) -> str:
    return "true" if value else "false"


def is_dead(profile: CompanyProfile) -> bool:
    """True for a status that means the company cannot be trading (DEAD_STATUSES)."""
    return (profile.company_status or "").lower() in DEAD_STATUSES


def number_name_mismatch(s: Subject) -> bool:
    """True when a number was given with a name and the register name is clearly different."""
    if s.matched_by != "number" or not s.supplied_name or not s.profile.company_name:
        return False
    return name_score(s.supplied_name, s.profile.company_name) < NAME_NUMBER_MISMATCH_MAX


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _office_sentence(s: Subject) -> str:
    office = s.profile.registered_office
    return f" Registered office: {office}." if office else ""


# --- pure rules (plan 5.3) -------------------------------------------------------------------


def rule_not_found(number: str, student: list[EvidenceRef]) -> Finding:
    """The company number returned 404: hard flag."""
    return make_finding(
        "not-found",
        title=f"No company with number {number} on Companies House",
        detail="The company number you were given doesn't exist in the official UK register.",
        severity=Severity.CRITICAL,
        confidence=CONF["not-found"],
        evidence=[
            ch_ref("company_number", number),
            ch_ref("http_status", "404 not found"),
            *student,
        ],
        sources=[register_url(number)],
        hard_flag=True,
    )


def rule_dissolved(s: Subject) -> Finding | None:
    """Status is dissolved, in liquidation, administration and so on: hard flag."""
    if not is_dead(s.profile):
        return None
    label = s.status.replace("-", " ")
    return make_finding(
        "dissolved",
        title=f"{s.name} is {label} on Companies House",
        detail=(
            f"The official register lists this company as {label}, so it can't legally be "
            f"trading.{_office_sentence(s)}"
        ),
        severity=Severity.CRITICAL,
        confidence=CONF["dissolved"],
        evidence=[ch_ref("company_status", s.status), *s.student],
        sources=[s.url],
        hard_flag=True,
    )


def rule_strike_off(s: Subject) -> Finding | None:
    """Still listed as live but about to disappear. Never clears. Dead statuses fire `dissolved`."""
    detail = (s.profile.company_status_detail or "").lower()
    if is_dead(s.profile) or detail not in STRIKE_OFF_DETAILS:
        return None
    return make_finding(
        "strike-off-proposed",
        title=f"{s.name} may be about to be struck off",
        detail=(
            "The register shows a proposal to strike this company off, or a petition to restore "
            f"it after dissolution ({detail.replace('-', ' ')}). A company in this state may "
            f"stop existing soon.{_office_sentence(s)}"
        ),
        severity=Severity.MEDIUM,
        confidence=CONF["strike-off-proposed"],
        evidence=[ch_ref("company_status_detail", detail), *s.student],
        sources=[s.url],
    )


def rule_name_number_mismatch(s: Subject) -> Finding | None:
    """The number resolves to a company with a different name from the one supplied."""
    if not number_name_mismatch(s):
        return None
    registered = s.profile.company_name or ""
    supplied = s.supplied_name or ""
    return make_finding(
        "name-number-mismatch",
        title=f"The company number doesn't match the name {supplied}",
        detail=f"The company number belongs to {registered}, not {supplied}.{_office_sentence(s)}",
        severity=Severity.HIGH,
        confidence=CONF["name-number-mismatch"],
        evidence=[
            ch_ref("company_number", s.number),
            ch_ref("company_name", registered),
            *s.student,
        ],
        sources=[s.url],
    )


def rule_young_company(s: Subject, today: date) -> Finding | None:
    created = s.profile.date_of_creation
    if created is None:
        return None
    months = months_between(created, today)
    if not 0 <= months < YOUNG_MONTHS:
        return None
    return make_finding(
        "young-company",
        title=f"{s.name} was set up {_plural(months, 'month')} ago",
        detail=(
            "Very new companies are more often used in rental scams. It isn't proof, but check "
            f"everything else carefully. Registered on {created.isoformat()}.{_office_sentence(s)}"
        ),
        severity=Severity.MEDIUM,
        confidence=CONF["young-company"],
        evidence=[ch_ref("date_of_creation", created.isoformat()), *s.student],
        sources=[s.url],
    )


def rule_officer_mismatch(
    s: Subject,
    officers: OfficerList | None,
    landlord_name: str | None,
    person_refs: list[EvidenceRef] | None = None,
) -> Finding | None:
    """The named person matches no current officer. Only when we saw every active officer."""
    person = strip_title(landlord_name or "").strip()
    if not person or officers is None or not officers.complete:
        return None
    people = [o for o in officers.active if not o.is_corporate]
    if not people:
        return None
    if any(person_matches_officer(person, o.name) for o in people):
        return None
    listed = "; ".join(o.name for o in people[:5])
    return make_finding(
        "officer-mismatch",
        title=f"{person} isn't listed as a director of {s.name}",
        detail=(
            f"The name you were given ({person}) is not a current officer of {s.name}. This is "
            "common for staff, so ask the agent who the director is."
            f" Current officers: {listed}."
        ),
        severity=Severity.MEDIUM,
        confidence=CONF["officer-mismatch"],
        evidence=[ch_ref("officers", listed), *(person_refs or [])],
        sources=[s.url],
    )


def officer_search_name(officer_name: str) -> str:
    """'CLARKE, Hannah Louise' becomes 'Hannah Louise CLARKE'; names with no comma pass through."""
    if "," not in officer_name:
        return officer_name.strip()
    surname, _, rest = officer_name.partition(",")
    return f"{rest.strip()} {surname.strip()}".strip()


def dob_agrees(a: object, b: object) -> bool | None:
    """True/False when both sides give a date of birth, None when either is missing."""
    da, db = parse_dob(a), parse_dob(b)
    if da is None or db is None:
        return None
    if da[0] != db[0]:
        return False
    return da[1] is None or db[1] is None or da[1] == db[1]


def find_disqualified(officer: Officer, hits: list[DisqualifiedHit]) -> DisqualifiedHit | None:
    """The first hit that is really this officer: name score, and DOB when both sides give one.

    With either DOB missing we need an exact name (score 100) before we call it a match.
    """
    query = officer_search_name(officer.name)
    for hit in hits:
        score = name_score(query, hit.title)
        if score < NAME_MATCH_MIN:
            continue
        agrees = dob_agrees(officer.date_of_birth, hit.date_of_birth)
        if agrees is True or (agrees is None and score == 100):
            return hit
    return None


def rule_disqualified(s: Subject, matches: list[tuple[Officer, DisqualifiedHit]]) -> Finding | None:
    if not matches:
        return None
    officer, hit = matches[0]
    names = "; ".join(o.name for o, _ in matches)
    extra = f" {hit.description}" if hit.description else ""
    return make_finding(
        "disqualified-director",
        title=f"A director of {s.name} is disqualified",
        detail=(
            f"The register shows {names} is disqualified from being a company director.{extra}"
        ),
        severity=Severity.HIGH,
        confidence=CONF["disqualified-director"],
        evidence=[ch_ref("disqualified_officer", h.title) for _, h in matches]
        + [ch_ref("officer", officer.name)],
        sources=[s.url],
    )


def rule_overdue_filings(s: Subject) -> Finding | None:
    refs: list[EvidenceRef] = []
    if s.profile.accounts is not None and s.profile.accounts.overdue is True:
        refs.append(ch_ref("accounts.overdue", _flag(True)))
    cs = s.profile.confirmation_statement
    if cs is not None and cs.overdue is True:
        refs.append(ch_ref("confirmation_statement.overdue", _flag(True)))
    if not refs:
        return None
    return make_finding(
        "overdue-filings",
        title=f"{s.name} is behind on its filings",
        detail="Its accounts or confirmation statement are overdue at Companies House.",
        severity=Severity.LOW,
        confidence=CONF["overdue-filings"],
        evidence=refs,
        sources=[s.url],
    )


def _is_dormant(profile: CompanyProfile) -> bool:
    last = profile.accounts.last_accounts if profile.accounts else None
    return bool(last and (last.type or "").lower() == "dormant")


def rule_dormant(s: Subject) -> Finding | None:
    if not _is_dormant(s.profile):
        return None
    return make_finding(
        "dormant",
        title=f"{s.name} files dormant accounts",
        detail="Its latest accounts say it isn't trading, which doesn't fit a letting agency.",
        severity=Severity.MEDIUM,
        confidence=CONF["dormant"],
        evidence=[ch_ref("accounts.last_accounts.type", "dormant")],
        sources=[s.url],
    )


def rule_insolvency_history(s: Subject) -> Finding | None:
    if s.profile.has_insolvency_history is not True or is_dead(s.profile):
        return None
    return make_finding(
        "insolvency-history",
        title=f"{s.name} has an insolvency history",
        detail="The register shows past insolvency proceedings.",
        severity=Severity.MEDIUM,
        confidence=CONF["insolvency-history"],
        evidence=[ch_ref("has_insolvency_history", _flag(True))],
        sources=[s.url],
    )


def rule_non_property_sic(s: Subject) -> Finding | None:
    """Only when SIC codes are listed and none is a property code (no codes = unknown)."""
    codes = s.profile.sic_codes
    if not codes or any(c in PROPERTY_SIC for c in codes):
        return None
    listed = ", ".join(codes)
    return make_finding(
        "non-property-sic",
        title=f"{s.name} isn't registered as a property business",
        detail=(
            f"Its registered business activity ({listed}) isn't letting or property management."
        ),
        severity=Severity.LOW,
        confidence=CONF["non-property-sic"],
        evidence=[ch_ref("sic_codes", listed)],
        sources=[s.url],
    )


def rule_virtual_office(s: Subject) -> Finding | None:
    office = s.profile.registered_office
    lowered = office.lower()
    if not office or not any(marker in lowered for marker in VIRTUAL_OFFICE_MARKERS):
        return None
    return make_finding(
        "virtual-office",
        title=f"{s.name} uses a virtual office address",
        detail=(
            f"Its registered office ({office}) is a common virtual office / formation agent "
            "address, used by many legitimate companies too, so ask to visit their real office."
        ),
        severity=Severity.LOW,
        confidence=CONF["virtual-office"],
        evidence=[ch_ref("registered_office_address", office)],
        sources=[s.url],
    )


def rule_registered_active(s: Subject, today: date) -> Finding | None:
    """Clear: active, established, name agrees, filings fine, not dormant, no strike-off."""
    p = s.profile
    created = p.date_of_creation
    if s.status != "active" or created is None:
        return None
    months = months_between(created, today)
    if months < ESTABLISHED_MONTHS or number_name_mismatch(s):
        return None
    if (p.accounts and p.accounts.overdue is True) or (
        p.confirmation_statement and p.confirmation_statement.overdue is True
    ):
        return None
    if _is_dormant(p) or (p.company_status_detail or "").lower() in STRIKE_OFF_DETAILS:
        return None
    years = months // 12
    return make_finding(
        "registered-active",
        title=f"{s.name} is active on Companies House",
        detail=(
            f"Registered on {created.day} {created:%B %Y} ({_plural(years, 'year')} ago), "
            f"active, filings up to date. Registered office: {p.registered_office or 'not listed'}."
        ),
        severity=Severity.LOW,
        confidence=CONF["registered-active"],
        evidence=[
            ch_ref("company_status", "active"),
            ch_ref("date_of_creation", created.isoformat()),
            *s.student,
        ],
        sources=[s.url],
        supports="cleared",
    )


def evaluate(
    s: Subject,
    *,
    today: date,
    officers: OfficerList | None = None,
    landlord_name: str | None = None,
    person_refs: list[EvidenceRef] | None = None,
    disqualified: list[tuple[Officer, DisqualifiedHit]] | None = None,
) -> list[Finding]:
    """Every register rule over one resolved company, in display order."""
    candidates = [
        rule_dissolved(s),
        rule_strike_off(s),
        rule_name_number_mismatch(s),
        rule_young_company(s, today),
        rule_officer_mismatch(s, officers, landlord_name, person_refs),
        rule_disqualified(s, disqualified or []),
        rule_overdue_filings(s),
        rule_dormant(s),
        rule_insolvency_history(s),
        rule_non_property_sic(s),
        rule_virtual_office(s),
        rule_registered_active(s, today),
    ]
    return [f for f in candidates if f is not None]


# --- name resolution (plan 5.1, pure) --------------------------------------------------------


@dataclass(frozen=True)
class MatchDecision:
    kind: Literal["resolved", "ambiguous", "none"]
    hit: SearchHit | None  # the chosen hit when resolved
    candidates: tuple[SearchHit, ...]  # close hits when ambiguous
    scored: tuple[tuple[int, SearchHit], ...]  # every hit with its score, best first


def rank_hits(supplied: str, hits: list[SearchHit]) -> MatchDecision:
    """Decide between one clear match, several close matches, or none.

    Resolved: exactly one exact normalised match, or the best hit scores >= NAME_MATCH_MIN and
    the next best is at least NAME_MATCH_GAP lower. Ambiguous: a strong best hit with a close
    runner-up. None: nothing scores >= NAME_MATCH_MIN.
    """
    scored = tuple(
        sorted(((name_score(supplied, h.title), h) for h in hits), key=lambda p: p[0], reverse=True)
    )
    target = normalise_name(supplied)
    exact = [h for _, h in scored if target and normalise_name(h.title) == target]
    if len(exact) == 1:
        return MatchDecision("resolved", exact[0], (), scored)
    if not scored or scored[0][0] < NAME_MATCH_MIN:
        return MatchDecision("none", None, (), scored)
    best = scored[0][0]
    if len(scored) == 1 or best - scored[1][0] >= NAME_MATCH_GAP:
        return MatchDecision("resolved", scored[0][1], (), scored)
    close = tuple(h for score, h in scored if best - score < NAME_MATCH_GAP)[:3]
    return MatchDecision("ambiguous", None, close, scored)


def _candidate_line(hit: SearchHit) -> str:
    return f"{hit.title} ({hit.company_number}, {hit.company_status or 'status unknown'})"


def _search_page(supplied: str) -> str:
    return SEARCH_PAGE_URL.format(q=quote_plus(supplied))


def finding_ambiguous(
    supplied: str, decision: MatchDecision, student: list[EvidenceRef]
) -> Finding:
    best_score, best_hit = decision.scored[0]
    listed = ", ".join(_candidate_line(h) for h in decision.candidates)
    return make_finding(
        "ambiguous-match",
        title=f'Several companies match "{supplied}"',
        detail=(
            f"These registered companies have similar names: {listed}. "
            "Ask which one by company number."
        ),
        severity=Severity.MEDIUM,
        confidence=CONF["ambiguous-match"],
        evidence=[
            ch_ref("search_query", supplied),
            ch_ref(
                "search_results",
                f"{len(decision.scored)} hits, best match {best_hit.title} ({best_score})",
            ),
            *student,
        ],
        sources=[_search_page(supplied)],
    )


def finding_name_no_match(
    supplied: str, decision: MatchDecision, student: list[EvidenceRef]
) -> Finding:
    if decision.scored:
        best_score, best_hit = decision.scored[0]
        results = f"0 hits >= {NAME_MATCH_MIN} (best match {best_hit.title}, {best_score})"
    else:
        results = f"0 hits >= {NAME_MATCH_MIN} (no results)"
    return make_finding(
        "name-no-match",
        title=f'Couldn\'t find "{supplied}" on Companies House',
        detail=(
            "No registered company closely matches this name. Ask for the company number to "
            "check it properly."
        ),
        severity=Severity.HIGH,
        confidence=CONF["name-no-match"],
        evidence=[ch_ref("search_query", supplied), ch_ref("search_results", results), *student],
        sources=[_search_page(supplied)],
    )


# --- I/O -------------------------------------------------------------------------------------


def _fatal(fetch: Fetch) -> RegisterResult:
    error = fetch.error or ("404 not found" if fetch.outcome == Outcome.NOT_FOUND else "unknown")
    return RegisterResult(name="register", fatal=True, error=f"companies house: {error}")


async def _disqualified_matches(
    client: CompaniesHouseClient, officers: OfficerList, failed: list[str]
) -> list[tuple[Officer, DisqualifiedHit]]:
    """Look up the first few active people officers; a failed lookup is noted, not fatal."""
    people = [o for o in officers.active if not o.is_corporate][:MAX_DISQUALIFIED_LOOKUPS]
    fetches = await asyncio.gather(
        *(client.search_disqualified(officer_search_name(o.name)) for o in people)
    )
    matches: list[tuple[Officer, DisqualifiedHit]] = []
    for officer, fetch in zip(people, fetches, strict=True):
        if not fetch.ok or fetch.value is None:
            note = f"disqualified officers (Companies House: {fetch.error})"
            if note not in failed:
                failed.append(note)
            continue
        hit = find_disqualified(officer, fetch.value)
        if hit is not None:
            matches.append((officer, hit))
    return matches


async def run(
    ctx: AgentContext,
    case: Case,
    *,
    today: date | None = None,
    sleep: Sleep = asyncio.sleep,
) -> RegisterResult:
    """Resolve the landlord's company, fetch officers, apply the 5.3 rules."""
    today = today or date.today()
    landlord = case.landlord
    raw_number = ((landlord.company_number if landlord else None) or "").strip()
    supplied = ((landlord.company_name if landlord else None) or "").strip()
    person = (landlord.name if landlord else None) or None
    result = RegisterResult(name="register")
    if not raw_number and not supplied:
        return result

    client = CompaniesHouseClient(ctx, sleep=sleep)
    profile: CompanyProfile
    matched_by: Literal["number", "name"]

    if raw_number:
        number = normalise_number(raw_number)
        fetch = await client.get_company(number)
        if fetch.outcome == Outcome.NOT_FOUND:
            student = student_refs(case, [supplied, raw_number, number])
            result.findings.append(rule_not_found(number, student))
            return result
        if not fetch.ok or fetch.value is None:
            return _fatal(fetch)
        profile, matched_by = fetch.value, "number"
    else:
        search = await client.search_companies(supplied)
        if not search.ok or search.value is None:
            return _fatal(search)
        decision = rank_hits(supplied, search.value)
        student = student_refs(case, [supplied])
        if decision.kind == "ambiguous":
            result.findings.append(finding_ambiguous(supplied, decision, student))
            result.questions.append(ASK_FOR_NUMBER)
            return result
        if decision.kind == "none" or decision.hit is None:
            result.findings.append(finding_name_no_match(supplied, decision, student))
            result.questions.append(ASK_FOR_NUMBER)
            return result
        number = normalise_number(decision.hit.company_number)
        profile_fetch = await client.get_company(number)
        if not profile_fetch.ok or profile_fetch.value is None:
            return _fatal(profile_fetch)
        profile, matched_by = profile_fetch.value, "name"

    subject = Subject(
        profile=profile,
        number=number,
        matched_by=matched_by,
        supplied_name=supplied or None,
        student=tuple(student_refs(case, [supplied, raw_number, profile.company_name or ""])),
    )

    officers: OfficerList | None = None
    disqualified: list[tuple[Officer, DisqualifiedHit]] = []
    if not is_dead(profile):  # a dead company already carries the hard flag; skip the extras
        officer_fetch = await client.get_officers(number)
        if officer_fetch.ok and officer_fetch.value is not None:
            officers = officer_fetch.value
            disqualified = await _disqualified_matches(client, officers, result.failed_checks)
        elif officer_fetch.outcome == Outcome.FAILED:
            result.failed_checks.append(f"officers (Companies House: {officer_fetch.error})")
        # NOT_FOUND on officers: the register lists none, so there is nothing to compare.

    result.findings.extend(
        evaluate(
            subject,
            today=today,
            officers=officers,
            landlord_name=person,
            person_refs=student_refs(case, [strip_title(person or "")]) if person else None,
            disqualified=disqualified,
        )
    )
    result.facts.append(
        Fact(key=FactKey.COMPANY_NUMBER, value=number, source=EV_REGISTER, agent=AGENT_NAME)
    )
    result.resolved_company = ResolvedCompany(
        profile=profile, number=number, matched_by=matched_by, supplied_name=supplied or None
    )
    ctx.log.info("companies_house: register resolved %s by %s", number, matched_by)
    return result
