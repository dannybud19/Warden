"""Reputation module: scam reports, reviews, redress/CMP, Rogue Checker (plan section 6).

Absence is never evidence (D11): no redress hit, no CMP hit and no Rogue Checker entry produce no
finding. A check that could not run is reported in `failed_checks`, never as "nothing found".
Nothing here sets a hard flag, emits facts, scores or gives a verdict.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Literal

from app.agents.companies_house.constants import (
    CMP_DOMAINS,
    CONF,
    EV_ROGUE,
    EV_WEB,
    MAX_FINDINGS_PER_KIND,
    MAX_QUOTE_CHARS,
    QUERY_CMP,
    QUERY_REDRESS,
    QUERY_REVIEWS,
    QUERY_ROGUE_FALLBACK,
    QUERY_SCAM,
    REDRESS_DOMAINS,
    ROGUE_CHECKER_URL,
    ROGUE_MAX_REQUESTS,
    ROGUE_NAME_MATCH_MIN,
    ROGUE_NO_RESULTS_TEXT,
    ROGUE_PAGE_SIZE,
    ROGUE_TIMEOUT_S,
    ROGUE_USER_AGENT,
)
from app.agents.companies_house.evidence import clip_around, make_finding
from app.agents.companies_house.models import (
    Fetch,
    FilterContext,
    KeptSnippet,
    ModuleResult,
    QueryBudget,
    ResolvedCompany,
    RogueRecord,
    Snippet,
)
from app.agents.companies_house.normalise import (
    domain_of,
    host_matches,
    name_score,
    normalise_name,
    normalise_number,
    url_hash8,
)
from app.agents.companies_house.retry import Sleep
from app.agents.companies_house.snippet_filter import filter_snippets
from app.agents.companies_house.web import http_get, web_search
from app.contracts import Case, EvidenceRef, Finding, Severity
from app.core.agent import AgentContext
from app.core.search import SearchResult

ROGUE_CHECK_NAME = "London Rogue Landlord and Agent Checker"
_CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required", "cf-browser-verification")
_REDRESS_SCHEMES = {
    "theprs.co.uk": "Property Redress Scheme",
    "tpos.co.uk": "The Property Ombudsman",
}
_CMP_SCHEMES = {
    "propertymark.co.uk": "Propertymark",
    "safeagent.co.uk": "safeagent",
    "ukala.org.uk": "UKALA",
}
_NAME_SUFFIX_WORDS = r"(?:limited|ltd|llp|plc|lp|uk|company|co)"


# --- Rogue Checker page parsing --------------------------------------------------------------


@dataclass
class _Entry:
    heading: str
    fields: dict[str, str]


class _RogueParser(HTMLParser):
    """Collects `<h3 data-search-highlight>` entries and their `<li><strong>` label/value items."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[_Entry] = []
        self._current: _Entry | None = None
        self._in_heading = False
        self._heading_parts: list[str] = []
        self._in_li = False
        self._in_strong = False
        self._label_parts: list[str] = []
        self._value_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h3":
            self._finish_li()
            if any(key == "data-search-highlight" for key, _ in attrs):
                self._current = _Entry("", {})
                self.entries.append(self._current)
                self._in_heading = True
                self._heading_parts = []
            else:
                self._current = None
        elif tag == "li" and self._current is not None:
            self._finish_li()
            self._in_li = True
            self._label_parts, self._value_parts = [], []
        elif tag == "strong" and self._in_li:
            self._in_strong = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_heading and self._current is not None:
            self._current.heading = " ".join("".join(self._heading_parts).split())
            self._in_heading = False
        elif tag == "strong":
            self._in_strong = False
        elif tag == "li":
            self._finish_li()

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._heading_parts.append(data)
        elif self._in_li:
            (self._label_parts if self._in_strong else self._value_parts).append(data)

    def _finish_li(self) -> None:
        if self._in_li and self._current is not None:
            label = " ".join("".join(self._label_parts).split()).rstrip(":").strip()
            value = " ".join("".join(self._value_parts).split())
            if label:
                self._current.fields.setdefault(label.lower(), value)
        self._in_li = False
        self._in_strong = False

    def close(self) -> None:
        super().close()
        self._finish_li()


_DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y")
_WEEKDAY_RE = re.compile(r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+", re.IGNORECASE)
_ORDINAL_RE = re.compile(r"(\d)(?:st|nd|rd|th)\b", re.IGNORECASE)


def parse_rogue_date(text: str | None) -> date | None:
    """'Monday 23 March 2026' (weekday optional) or ISO / dd/mm/yyyy gives a date, else None."""
    if not text:
        return None
    cleaned = _ORDINAL_RE.sub(r"\1", " ".join(text.split()))
    cleaned = _WEEKDAY_RE.sub("", cleaned).replace("Sept ", "Sep ").strip(" .,")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


_HEADING_RE = re.compile(r"^(?P<name>.*?)\s*\(\s*(?P<number>[A-Za-z0-9]{6,8})\s*\)\s*$")


def _record_from_entry(entry: _Entry) -> RogueRecord | None:
    heading = entry.heading
    if not heading:
        return None
    match = _HEADING_RE.match(heading)
    name = match.group("name").strip() if match else heading
    number = normalise_number(match.group("number")) if match else None
    fields = entry.fields
    action = fields.get("enforcement action type") or None
    date_text = fields.get("enforcement date") or None
    quote_parts = [heading]
    if action:
        quote_parts.append(f"Enforcement action type: {action}")
    if date_text:
        quote_parts.append(f"Enforcement date: {date_text}")
    return RogueRecord(
        name=name,
        number=number,
        action_type=action,
        authority=fields.get("enforcement authority") or None,
        action_date=parse_rogue_date(date_text),
        expires=parse_rogue_date(fields.get("record expires")),
        address=fields.get("rental property address") or None,
        offence=fields.get("offence") or None,
        quote=" | ".join(quote_parts)[:MAX_QUOTE_CHARS],
    )


def parse_rogue_page(html: str) -> list[RogueRecord]:
    """Entries on one Rogue Checker results page. Tolerant of whitespace and extra tags."""
    parser = _RogueParser()
    parser.feed(html)
    parser.close()
    records = (_record_from_entry(e) for e in parser.entries)
    return [r for r in records if r is not None]


def _is_challenge(body: str) -> bool:
    lowered = body.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _is_live(record: RogueRecord, today: date) -> bool:
    """A record whose 'Record expires' date has passed is ignored; no date means still live."""
    return record.expires is None or record.expires >= today


def rogue_match(record: RogueRecord, company: ResolvedCompany) -> str | None:
    """'number' when the entry's company number is ours; 'name' only for an entry with no number.

    A different company number means a different company by definition, so it never matches.
    """
    if record.number:
        return "number" if normalise_number(record.number) == company.number else None
    if name_score(record.name, company.registered_name) >= ROGUE_NAME_MATCH_MIN:
        return "name"
    return None


def _format_date(value: date | None) -> str | None:
    return f"{value.day} {value.strftime('%B %Y')}" if value else None


def rogue_finding(
    record: RogueRecord, kind: str, company: ResolvedCompany, source_url: str, evidence_id: str
) -> Finding:
    """The `rogue-checker` (number match) or `rogue-checker-name` finding for one record."""
    action = record.action_type or "an enforcement action"
    wording = f"The Mayor of London's checker records: {action}"
    if record.authority:
        wording += f" by {record.authority}"
    when = _format_date(record.action_date)
    if when:
        wording += f" on {when}"
    detail = f"{wording}."
    if record.offence:
        detail += f" Offence listed: {record.offence}."
    if kind == "name":
        detail += " The entry matches by name only, so check it is the same company."
    return make_finding(
        "rogue-checker" if kind == "number" else "rogue-checker-name",
        title=f"{company.registered_name} is on the London Rogue Landlord and Agent Checker",
        detail=detail,
        severity=Severity.HIGH if kind == "number" else Severity.MEDIUM,
        confidence=CONF["rogue-checker" if kind == "number" else "rogue-checker-name"],
        evidence=[EvidenceRef(evidence_id=evidence_id, quote=record.quote)],
        sources=[source_url],
    )


def _findings_from_records(
    records: list[tuple[RogueRecord, str, str]], company: ResolvedCompany, today: date
) -> list[Finding]:
    """One finding per match kind (number first). `records` are (record, source url, evidence)."""
    best: dict[str, tuple[RogueRecord, str, str]] = {}
    for record, url, evidence_id in records:
        if not _is_live(record, today):
            continue
        kind = rogue_match(record, company)
        if kind and kind not in best:
            best[kind] = (record, url, evidence_id)
    return [
        rogue_finding(rec, kind, company, url, ev)
        for kind in ("number", "name")
        if kind in best
        for rec, url, ev in [best[kind]]
    ]


# --- Rogue Checker: direct fetch -------------------------------------------------------------


@dataclass
class _RogueFetch:
    ok: bool
    records: list[tuple[RogueRecord, str, str]]
    error: str | None = None
    truncated: bool = False  # every page we may fetch was full and none matched: more may exist


async def _fetch_rogue_direct(
    ctx: AgentContext, company: ResolvedCompany, today: date, sleep: Sleep
) -> _RogueFetch:
    """At most ROGUE_MAX_REQUESTS single-try fetches. Any failure means 'use the fallback'."""
    collected: list[tuple[RogueRecord, str, str]] = []
    for page in range(ROGUE_MAX_REQUESTS):
        fetch = await http_get(
            ctx,
            ROGUE_CHECKER_URL,
            per_try_timeout=ROGUE_TIMEOUT_S,
            headers={"User-Agent": ROGUE_USER_AGENT},
            params={"name": company.registered_name, "page": page},
            follow_redirects=True,
            attempts=1,
            sleep=sleep,
        )
        if not fetch.ok or fetch.value is None:
            return _RogueFetch(False, [], fetch.error or "not found")
        body = fetch.value.text
        url = fetch.url or ROGUE_CHECKER_URL
        if _is_challenge(body):
            return _RogueFetch(False, [], "blocked by a challenge page")
        if ROGUE_NO_RESULTS_TEXT.lower() in body.lower():
            return _RogueFetch(True, collected)
        records = parse_rogue_page(body)
        if not records:
            return _RogueFetch(False, [], "page could not be read")
        collected.extend((r, url, EV_ROGUE) for r in records)
        matched = any(_is_live(r, today) and rogue_match(r, company) for r in records)
        if matched or len(records) < ROGUE_PAGE_SIZE:
            break
        if page == ROGUE_MAX_REQUESTS - 1:
            return _RogueFetch(True, collected, truncated=True)
    return _RogueFetch(True, collected)


# --- Rogue Checker: Linkup fallback ----------------------------------------------------------

_ROGUE_LABELS = (
    "Enforcement action type",
    "Enforcement authority",
    "Enforcement date",
    "Record expires",
    "Rental property address",
    "Offence",
)
_NEGATIVE_MEMBERSHIP_RE = re.compile(
    r"\b(expel|expelled|removed|suspend|suspended|sanction|sanctioned|banned|struck off|"
    r"terminated|no longer a member|ceased|disciplin)\w*",
    re.IGNORECASE,
)
_PAREN_NUMBER_RE = re.compile(r"\(\s*([A-Za-z0-9]{6,8})\s*\)")


def _labelled(content: str, label: str) -> str | None:
    stops = "|".join(re.escape(x) for x in _ROGUE_LABELS)
    found = re.search(rf"{re.escape(label)}\s*:\s*(.*?)\s*(?=(?:{stops})\s*:|\n|$)", content)
    return found.group(1).strip() or None if found else None


def _entry_window(content: str, start: int) -> str:
    """The part of `content` from `start` up to where the NEXT entry's labels begin.

    A snippet may hold several entries; labels must come from the matched one only.
    """
    first = content.find(_ROGUE_LABELS[0], start)
    if first == -1:
        return content[start:]
    second = content.find(_ROGUE_LABELS[0], first + 1)
    if second == -1:
        return content[start:]
    newline = content.rfind("\n", first, second)
    return content[start : newline if newline != -1 else second]


def _number_after(content: str, end: int) -> str | None:
    """A company number in parentheses straight after position `end` (an entry's own number)."""
    found = re.match(
        rf"\s*(?:(?:{_NAME_SUFFIX_WORDS})\b\.?\s*)*\(\s*([A-Za-z0-9]{{6,8}})\s*\)",
        content[end:],
        re.IGNORECASE,
    )
    return normalise_number(found.group(1)) if found else None


def _name_span(content: str, name: str) -> str | None:
    """The verbatim span of `content` naming `name` (case, punctuation and suffix tolerant)."""
    words = normalise_name(name).split()
    if not words:
        return None
    parts = [r"(?:and|&)" if w == "and" else re.escape(w) for w in words]
    sep = rf"[^a-z0-9]*(?:{_NAME_SUFFIX_WORDS}\b[^a-z0-9]*)*"
    found = re.search(r"\b" + sep.join(parts) + r"\b", content, re.IGNORECASE)
    return found.group(0) if found else None


def _records_from_snippet(result: SearchResult, company: ResolvedCompany) -> list[RogueRecord]:
    """A record when the snippet carries our number in parentheses or names our company."""
    content = result.snippet
    if not host_matches(domain_of(result.url), frozenset({"london.gov.uk"})):
        return []
    number_hit = next(
        (
            m
            for m in _PAREN_NUMBER_RE.finditer(content)
            if normalise_number(m.group(1)) == company.number
        ),
        None,
    )
    start = -1
    if number_hit:
        needle: str | None = number_hit.group(0)
        start = number_hit.start()
    else:
        needle = _name_span(content, company.registered_name)
        if needle:
            start = content.lower().find(needle.lower())
            own_number = _number_after(content, start + len(needle))
            if own_number and own_number != company.number:
                return []  # same name, different company number: a different company
    if not needle:
        return []
    window = _entry_window(content, start)
    action = _labelled(window, "Enforcement action type")
    date_text = _labelled(window, "Enforcement date")
    quote = clip_around(content, needle) or needle
    return [
        RogueRecord(
            name=company.registered_name,
            number=company.number if number_hit else None,
            action_type=action,
            authority=_labelled(window, "Enforcement authority"),
            action_date=parse_rogue_date(date_text),
            expires=parse_rogue_date(_labelled(window, "Record expires")),
            address=_labelled(window, "Rental property address"),
            offence=_labelled(window, "Offence"),
            quote=quote,
        )
    ]


# --- snippets, redress and CMP ---------------------------------------------------------------


def _dedupe_by_url(results: list[SearchResult], seen: set[str], key: str) -> list[Snippet]:
    snippets: list[Snippet] = []
    for result in results:
        if not result.url or result.url in seen:
            continue
        seen.add(result.url)
        snippets.append(Snippet(0, result.title, result.url, result.snippet, key))
    return snippets


def _membership_finding(
    results: list[SearchResult],
    company: ResolvedCompany,
    domains: frozenset[str],
    schemes: dict[str, str],
    slug: str,
) -> Finding | None:
    """A cleared finding for the first result on a scheme's own domain that names the company."""
    for result in results:
        host = domain_of(result.url)
        if not host_matches(host, domains):
            continue
        needle = _name_span(result.snippet, company.registered_name)
        if needle is None and company.number and company.number in result.snippet:
            needle = company.number
        quote = clip_around(result.snippet, needle) if needle else None
        if not quote or _NEGATIVE_MEMBERSHIP_RE.search(result.snippet):
            continue  # not named, or the page reads like a sanction rather than a membership
        scheme = next((label for d, label in schemes.items() if host_matches(host, {d})), host)
        if slug == "redress-member":
            title = f"{company.registered_name} appears on the {scheme} site"
            detail = "Letting agents must belong to a redress scheme; this source lists them."
        else:
            title = f"{company.registered_name} appears on a client money protection list"
            detail = f"This {scheme} page names the company, so check it lists them as a member."
        return make_finding(
            slug,
            title=title,
            detail=detail,
            severity=Severity.LOW,
            confidence=CONF[slug],
            evidence=[EvidenceRef(evidence_id=EV_WEB, quote=quote)],
            sources=[result.url],
            supports="cleared",
        )
    return None


def _snippet_findings(kept: list[KeptSnippet], name: str) -> list[Finding]:
    findings: list[Finding] = []
    counts = {"scam_report": 0, "negative_review": 0}
    for item in kept:
        if counts[item.label] >= MAX_FINDINGS_PER_KIND:
            continue
        counts[item.label] += 1
        evidence = [EvidenceRef(evidence_id=EV_WEB, quote=item.quote)]
        slug_hash = url_hash8(item.snippet.url)
        if item.label == "scam_report":
            findings.append(
                make_finding(
                    f"scam-report-{slug_hash}",
                    title=f"A public post reports a problem with {name}",
                    detail=(
                        f'Someone online reports: "{item.quote}". This is an unverified public '
                        "post, so compare it with what you were told."
                    ),
                    severity=Severity.HIGH,
                    confidence=CONF["scam-report"],
                    evidence=evidence,
                    sources=[item.snippet.url],
                )
            )
        elif item.via_llm:
            findings.append(
                make_finding(
                    f"negative-review-{slug_hash}",
                    title="A review mentions a deposit or money problem",
                    detail=(
                        f'A review of {name} says: "{item.quote}". Reviews are one person\'s '
                        "account, so treat this as a prompt to ask questions."
                    ),
                    severity=Severity.MEDIUM,
                    confidence=CONF["negative-review"],
                    evidence=evidence,
                    sources=[item.snippet.url],
                )
            )
        else:  # keyword fallback (LLM down): shown, but below the 0.6 flip threshold
            findings.append(
                make_finding(
                    f"negative-review-{slug_hash}",
                    title=f"A public post mentions a problem with {name}",
                    detail=(
                        f'A public post says: "{item.quote}". It was picked out by a keyword '
                        "match, so check it is about the same company before relying on it."
                    ),
                    severity=Severity.MEDIUM,
                    confidence=CONF["negative-review-fallback"],
                    evidence=evidence,
                    sources=[item.snippet.url],
                )
            )
    return findings


def _failure_text(check: str, fetch: Fetch) -> str:
    if fetch.error == "query budget":
        return f"{check} (query budget)"
    return f"{check} (Linkup: {fetch.error})"


# --- entry point -----------------------------------------------------------------------------


async def run(
    ctx: AgentContext,
    case: Case,
    company: ResolvedCompany,
    budget: QueryBudget,
    *,
    today: date | None = None,
    sleep: Sleep = asyncio.sleep,
) -> ModuleResult:
    """Public-web reputation of a resolved company. Never raises."""
    result = ModuleResult(name="reputation")
    try:
        await _run(ctx, case, company, budget, today or date.today(), sleep, result)
    except Exception as exc:  # noqa: BLE001 - a module must not take the agent down
        ctx.log.error("companies_house: reputation crashed: %r", exc)
        result.failed_checks.append("reputation checks (unexpected error)")
    return result


async def _run(
    ctx: AgentContext,
    case: Case,
    company: ResolvedCompany,
    budget: QueryBudget,
    today: date,
    sleep: Sleep,
    result: ModuleResult,
) -> None:
    name = company.registered_name
    if not name:
        return
    queries: dict[str, tuple[str, Literal["standard", "deep"], str]] = {
        "scam": (QUERY_SCAM, "deep", "scam reports"),
        "reviews": (QUERY_REVIEWS, "deep", "reviews"),
        "redress": (QUERY_REDRESS, "standard", "redress scheme membership"),
        "cmp": (QUERY_CMP, "standard", "client money protection membership"),
    }
    searches = [
        web_search(ctx, budget, template.format(name=name), depth=depth, sleep=sleep)
        for template, depth, _ in queries.values()
    ]
    search_results, rogue = await asyncio.gather(
        asyncio.gather(*searches), _fetch_rogue_direct(ctx, company, today, sleep)
    )
    fetched = dict(zip(queries, search_results, strict=True))
    for key, (_, _, check) in queries.items():
        if not fetched[key].ok:
            result.failed_checks.append(_failure_text(check, fetched[key]))

    # Scam reports and reviews: dedupe by URL, one batched filter call, cap per kind.
    seen: set[str] = set()
    snippets: list[Snippet] = []
    for key in ("scam", "reviews"):
        if fetched[key].ok and fetched[key].value:
            snippets.extend(_dedupe_by_url(fetched[key].value or [], seen, key))
    for i, snippet in enumerate(snippets):
        snippet.index = i
    if snippets:
        supplied = company.supplied_name or (case.landlord.company_name if case.landlord else "")
        context = FilterContext(
            registered_name=name,
            company_number=company.number,
            registered_office=company.registered_office,
            supplied_name=supplied or "",
        )
        kept = await filter_snippets(ctx, snippets, context)
        result.findings.extend(_snippet_findings(kept, name))

    for key, domains, schemes, slug in (
        ("redress", REDRESS_DOMAINS, _REDRESS_SCHEMES, "redress-member"),
        ("cmp", CMP_DOMAINS, _CMP_SCHEMES, "cmp-member"),
    ):
        if fetched[key].ok and fetched[key].value:
            finding = _membership_finding(fetched[key].value or [], company, domains, schemes, slug)
            if finding:
                result.findings.append(finding)

    # Rogue Checker: direct fetch first, Linkup only when the direct fetch failed.
    records = rogue.records
    if not rogue.ok:
        ctx.log.warning("companies_house: rogue checker direct fetch failed: %s", rogue.error)
        fallback = await web_search(
            ctx, budget, QUERY_ROGUE_FALLBACK.format(name=name), depth="standard", sleep=sleep
        )
        if fallback.ok:
            records = [
                (record, hit.url, EV_WEB)
                for hit in fallback.value or []
                for record in _records_from_snippet(hit, company)
            ]
            if not _findings_from_records(records, company, today):
                # The checker itself was never read, so say so: absence via Linkup is weak.
                result.failed_checks.append(
                    f"{ROGUE_CHECK_NAME} (direct fetch: {rogue.error}; searched through Linkup "
                    "only, which can miss entries)"
                )
        elif fallback.error == "query budget":
            result.failed_checks.append(f"{ROGUE_CHECK_NAME} (query budget)")
            records = []
        else:
            result.failed_checks.append(
                f"{ROGUE_CHECK_NAME} (direct fetch: {rogue.error}; Linkup: {fallback.error})"
            )
            records = []
    rogue_findings = _findings_from_records(records, company, today)
    result.findings.extend(rogue_findings)
    if rogue.ok and rogue.truncated and not rogue_findings:
        result.failed_checks.append(
            f"{ROGUE_CHECK_NAME} (only the first {ROGUE_MAX_REQUESTS * ROGUE_PAGE_SIZE} entries "
            "for this name were checked)"
        )
