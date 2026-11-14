"""Contact module: email, phone and domain checks (plan section 7).

Reads the landlord's (or the agent's) email and phone. Emits `email_domain` facts and
suspicious findings only, never a hard flag.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime

from app.agents.companies_house import constants as k
from app.agents.companies_house.evidence import make_finding, student_refs
from app.agents.companies_house.models import (
    FilterContext,
    ModuleResult,
    Outcome,
    QueryBudget,
    ResolvedCompany,
    Snippet,
)
from app.agents.companies_house.normalise import (
    domain_of,
    extract_contacts,
    host_matches,
    url_hash8,
)
from app.agents.companies_house.retry import Sleep
from app.agents.companies_house.snippet_filter import filter_snippets
from app.agents.companies_house.web import http_get, web_search
from app.contracts import Case, EvidenceRef, Fact, FactKey, Finding, Severity
from app.core.agent import AgentContext

# --- pure rules ------------------------------------------------------------------------------


def is_webmail(domain: str) -> bool:
    """True for free personal mail domains (gmail.com, hotmail.co.uk, yahoo.com ...)."""
    return domain in k.WEBMAIL_DOMAINS or domain.startswith(k.WEBMAIL_PREFIXES)


def lookalike_brand(domain: str) -> str | None:
    """The brand a domain imitates (contains its name but is not its real domain), else None."""
    for brand, real in k.BRAND_DOMAINS.items():
        if brand in domain and not host_matches(domain, real):
            return brand
    return None


def parse_registration_date(payload: object) -> date | None:
    """Date of the RDAP 'registration' event; None when missing or unparseable."""
    if not isinstance(payload, dict):
        return None
    events = payload.get("events")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict) or event.get("eventAction") != "registration":
            continue
        raw = event.get("eventDate")
        if not isinstance(raw, str):
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                continue
    return None


def domain_age_days(registered: date, today: date) -> int:
    return (today - registered).days


# --- evidence helpers ------------------------------------------------------------------------


@dataclass
class _Email:
    address: str
    source: str  # "landlord" or the evidence id of the agent message


def _email_sources(case: Case, emails: list[str]) -> list[_Email]:
    landlord_email = (case.landlord.email or "").strip().lower() if case.landlord else ""
    found: list[_Email] = []
    for email in emails:
        if email == landlord_email:
            found.append(_Email(email, "landlord"))
            continue
        source = "unknown"
        for message in case.messages:
            if message.sender == "agent" and email in message.text.lower():
                source = message.evidence_id
                break
        found.append(_Email(email, source))
    return found


def _email_refs(case: Case, email: str) -> list[EvidenceRef]:
    refs = student_refs(case, [email])
    return refs or [EvidenceRef(evidence_id="landlord", quote=email)]


# --- findings --------------------------------------------------------------------------------


def _webmail_finding(case: Case, email: str) -> Finding:
    return make_finding(
        "webmail",
        title="The agent uses a personal email address",
        detail=f"Messages come from {email}, a free personal address, not a company domain.",
        severity=Severity.LOW,
        confidence=k.CONF["webmail"],
        evidence=_email_refs(case, email),
    )


def _lookalike_finding(case: Case, email: str, domain: str, brand: str) -> Finding:
    return make_finding(
        "lookalike-domain",
        title=f"The email domain imitates {brand.capitalize()}",
        detail=f"{domain} looks like {brand.capitalize()} but isn't its real domain.",
        severity=Severity.HIGH,
        confidence=k.CONF["lookalike-domain"],
        evidence=_email_refs(case, email),
    )


def _new_domain_finding(domain: str, registered: date, days: int, url: str) -> Finding:
    return make_finding(
        "new-domain",
        title=f"The email domain is only {days} days old",
        detail=f"{domain} was registered on {registered.isoformat()}.",
        severity=Severity.MEDIUM,
        confidence=k.CONF["new-domain"],
        evidence=[EvidenceRef(evidence_id=k.EV_RDAP, quote=f"registration: {registered}")],
        sources=[url],
    )


# --- I/O -------------------------------------------------------------------------------------


async def _check_domain_age(
    ctx: AgentContext, domain: str, today: date, sleep: Sleep
) -> tuple[Finding | None, str | None]:
    """(finding, failed-check text) for one domain's RDAP registration date."""
    url = k.RDAP_URL.format(domain=domain)
    result = await http_get(
        ctx, url, per_try_timeout=k.RDAP_TIMEOUT_S, follow_redirects=True, sleep=sleep
    )
    if result.outcome == Outcome.NOT_FOUND:
        return None, None
    if result.outcome != Outcome.OK or result.value is None:
        return None, f"email domain age (RDAP: {result.error})"
    try:
        payload = result.value.json()
    except (json.JSONDecodeError, ValueError):
        return None, "email domain age (RDAP: unreadable response)"
    registered = parse_registration_date(payload)
    if registered is None:
        return None, None
    days = domain_age_days(registered, today)
    if not 0 <= days < k.NEW_DOMAIN_DAYS:
        return None, None
    return _new_domain_finding(domain, registered, days, result.url or url), None


async def _check_phone(
    ctx: AgentContext,
    phone: str,
    company: ResolvedCompany | None,
    budget: QueryBudget,
    sleep: Sleep,
) -> tuple[list[Finding], str | None]:
    result = await web_search(
        ctx, budget, k.QUERY_PHONE.format(phone=phone), depth="standard", sleep=sleep
    )
    if result.outcome != Outcome.OK or result.value is None:
        if result.error == "query budget":
            return [], "phone scam reports (query budget)"
        return [], f"phone scam reports (Linkup: {result.error})"
    snippets = [
        Snippet(index=i, title=r.title, url=r.url, content=r.snippet, query_key="phone")
        for i, r in enumerate(result.value)
    ]
    if not snippets:
        return [], None
    context = FilterContext(
        subject="phone",
        phone=phone,
        registered_name=company.registered_name if company else "",
        company_number=company.number if company else "",
    )
    try:
        kept = await filter_snippets(ctx, snippets, context)
    except Exception as exc:  # noqa: BLE001 - a filter crash is a failed check, never a crash
        return [], f"phone scam reports (filter: {exc.__class__.__name__})"
    findings: list[Finding] = []
    seen: set[str] = set()
    for item in kept:
        if item.label != "scam_report" or item.snippet.url in seen:
            continue
        seen.add(item.snippet.url)
        findings.append(
            make_finding(
                f"phone-scam-{url_hash8(item.snippet.url)}",
                title="The phone number appears in a scam report",
                detail=f'A public post links {phone} to a scam: "{item.quote}".',
                severity=Severity.HIGH,
                confidence=k.CONF["phone-scam"],
                evidence=[EvidenceRef(evidence_id=k.EV_WEB, quote=item.quote)],
                sources=[item.snippet.url],
            )
        )
        if len(findings) >= k.MAX_FINDINGS_PER_KIND:
            break
    return findings, None


async def run(
    ctx: AgentContext,
    case: Case,
    company: ResolvedCompany | None,
    budget: QueryBudget,
    *,
    today: date | None = None,
    sleep: Sleep = asyncio.sleep,
) -> ModuleResult:
    """Checks on the landlord's email domain and phone. `company` is None when unresolved."""
    out = ModuleResult(name="contact")
    today = today or date.today()
    contacts = extract_contacts(case)
    emails = _email_sources(case, contacts.emails)

    domains: list[str] = []
    for item in emails:
        domain = domain_of(item.address)
        if not domain:
            continue
        try:
            if is_webmail(domain):
                out.findings.append(_webmail_finding(case, item.address))
            else:
                brand = lookalike_brand(domain)
                if brand:
                    out.findings.append(_lookalike_finding(case, item.address, domain, brand))
        except ValueError as exc:
            ctx.log.warning("companies_house: contact finding dropped: %s", exc)
        if domain not in domains:
            domains.append(domain)
            out.facts.append(
                Fact(
                    key=FactKey.EMAIL_DOMAIN,
                    value=domain,
                    source=item.source,
                    agent=k.AGENT_NAME,
                )
            )

    rdap_domains = [d for d in domains if not is_webmail(d)]
    age_tasks = [_check_domain_age(ctx, d, today, sleep) for d in rdap_domains]
    phone_task = (
        _check_phone(ctx, contacts.phones[0], company, budget, sleep) if contacts.phones else None
    )
    age_results, phone_result = await asyncio.gather(
        asyncio.gather(*age_tasks, return_exceptions=True),
        asyncio.gather(phone_task, return_exceptions=True) if phone_task else _none(),
    )
    for age in age_results:
        if isinstance(age, BaseException):
            ctx.log.warning("companies_house: domain age check crashed: %r", age)
            out.failed_checks.append("email domain age (unexpected error)")
            continue
        finding, failed = age
        if finding is not None:
            out.findings.append(finding)
        if failed:
            out.failed_checks.append(failed)
    for phone in phone_result:
        if isinstance(phone, BaseException):
            ctx.log.warning("companies_house: phone check crashed: %r", phone)
            out.failed_checks.append("phone scam reports (unexpected error)")
            continue
        found, failed = phone
        out.findings.extend(found)
        if failed:
            out.failed_checks.append(failed)
    return out


async def _none() -> list[tuple[list[Finding], str | None]]:
    return []
