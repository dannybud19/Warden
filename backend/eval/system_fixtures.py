"""Adapt declared synthetic sources to live-agent requests without adding verification facts."""

import copy
import re
from typing import Any, Literal

import httpx

from app.contracts import Case
from app.core.search import SearchResult
from eval.synthetic.external import FixtureUnavailableError, validate_external_bundle

CH_HOST = "api.company-information.service.gov.uk"
PROFILE_FIELDS = frozenset(
    {
        "company_name",
        "company_number",
        "company_status",
        "company_status_detail",
        "date_of_creation",
        "type",
        "has_insolvency_history",
        "sic_codes",
        "registered_office_address",
        "accounts",
        "confirmation_statement",
    }
)


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _matches(record: dict[str, Any], query: str) -> bool:
    normalised = _normalise(query)
    return any(
        all(_normalise(term) in normalised for term in group)
        for group in [record["query_terms"], *record.get("query_alternatives", [])]
    )


def _register_record(record: dict[str, Any]) -> bool:
    key = record["key"].casefold()
    return bool(record.get("company_status") or "register" in key or "registry" in key)


def _provenance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {field: record[field] for field in ("id", "key", "url", "snippet", "outcome")}
        for record in records
    ]


def _record_event(
    audit: dict[str, Any],
    transport: str,
    request: str,
    classification: str,
    records: list[dict[str, Any]],
    *,
    status: int | None = None,
    method: str | None = None,
    reason: str | None = None,
    fixture_route: str | None = None,
) -> None:
    audit["requests"].append(
        {
            "sequence": len(audit["requests"]) + 1,
            "transport": transport,
            "request": request,
            "classification": classification,
            "status": status,
            "method": method,
            "reason": reason,
            "fixture_ids": [record["id"] for record in records],
            "provenance": _provenance(records),
            "fixture_route": fixture_route,
        }
    )


class EvaluationSearch:
    """Return declared snippets or explicit unavailability, recording every query attempt."""

    def __init__(self, records: list[dict[str, Any]], audit: dict[str, Any]) -> None:
        self.records = records
        self.audit = audit
        self.queries: list[str] = []

    async def search(
        self, query: str, *, depth: Literal["standard", "deep"] = "standard"
    ) -> list[SearchResult]:
        """Keep a missing fixture distinct from a scenario's declared negative result."""
        self.queries.append(query)
        matches = [record for record in self.records if _matches(record, query)]
        if not matches:
            _record_event(
                self.audit,
                "search",
                query,
                "missing_fixture",
                [],
                reason="No declared query term group matches this request.",
            )
            raise FixtureUnavailableError("missing_fixture: no declared search evidence")
        if any(record["outcome"] == "unavailable" for record in matches):
            _record_event(self.audit, "search", query, "scenario_unavailable", matches)
            raise FixtureUnavailableError(
                "scenario_unavailable: declared search source unavailable"
            )
        found = [record for record in matches if record["outcome"] == "found"]
        _record_event(
            self.audit, "search", query, "fixture_found" if found else "scenario_not_found", matches
        )
        return [
            SearchResult(title=record["title"], url=record["url"], snippet=record["snippet"])
            for record in found
        ]


def _supports_identity(record: dict[str, Any], value: str) -> bool:
    if not value:
        return False
    source = " ".join(
        [
            record["snippet"],
            *record["query_terms"],
            *(term for group in record.get("query_alternatives", []) for term in group),
        ]
    )
    return _normalise(value) in _normalise(source)


def _profiles(
    case: Case,
    records: list[dict[str, Any]],
    routes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    registry = [record for record in records if _register_record(record)]
    for route in routes:
        url = httpx.URL(route["url"])
        matched = re.fullmatch(r"/company/([A-Za-z0-9]+)", url.path)
        if route["method"] != "GET" or url.host != CH_HOST or matched is None:
            continue
        number = matched[1]
        supporting = [record for record in registry if _supports_identity(record, number)]
        body = route["json"]
        profile = (
            {key: copy.deepcopy(value) for key, value in body.items() if key in PROFILE_FIELDS}
            if isinstance(body, dict)
            else {}
        )
        profiles.append(
            {
                "number": number,
                "profile": profile,
                "records": supporting,
                "status": route["status"],
                "url": route["url"],
            }
        )
    # Current fixtures declare status in source records. An official route is not required
    # when its subject number and name are independently present in that declared source.
    for record in registry:
        landlord = case.landlord
        number = (landlord.company_number or "") if landlord else ""
        if not number or not _supports_identity(record, number):
            match = re.search(
                r"\bcompany(?:\s+number)?\s*[:#]?\s*([0-9]{8})\b", record["snippet"], re.IGNORECASE
            )
            number = match[1] if match else ""
        if not number or any(item["number"] == number for item in profiles):
            continue
        profile: dict[str, Any] = {"company_number": number}
        name = (landlord.company_name or "") if landlord else ""
        if name and _supports_identity(record, name):
            profile["company_name"] = name
        if record.get("company_status"):
            profile["company_status"] = record["company_status"]
        profiles.append(
            {
                "number": number,
                "profile": profile,
                "records": [record],
                "status": {"found": 200, "not_found": 404, "unavailable": 503}[record["outcome"]],
                "url": record["url"],
            }
        )
    # Only an explicitly dated source can supply incorporation age. Missing officer,
    # filing, RDAP and postcode facts remain absent rather than favourable defaults.
    for item in profiles:
        dates = {
            match[1]
            for record in item["records"]
            if (
                match := re.search(
                    r"Incorporation date:\s*(\d{4}-\d{2}-\d{2})", record["snippet"], re.IGNORECASE
                )
            )
        }
        if len(dates) == 1 and "date_of_creation" not in item["profile"]:
            item["profile"]["date_of_creation"] = dates.pop()
    return profiles


def build_external(
    case: Case,
    bundle: dict[str, Any],
) -> tuple[EvaluationSearch, httpx.MockTransport, dict[str, Any]]:
    """Build controlled clients plus a live audit dictionary; never construct a network client."""
    validate_external_bundle(bundle)
    controlled = copy.deepcopy(bundle)
    records = controlled["records"]
    routes = controlled["http_routes"]
    profiles = _profiles(case, records, routes)
    audit: dict[str, Any] = {
        "case_id": case.case_id,
        "policy": "Declared evidence only; missing requests are unavailable, never negative.",
        "live_network_allowed": False,
        "requests": [],
    }
    exact_routes = {(route["method"], str(httpx.URL(route["url"]))): route for route in routes}

    def respond(
        request: httpx.Request,
        classification: str,
        supporting: list[dict[str, Any]],
        status: int,
        body: Any,
        *,
        reason: str | None = None,
        fixture_route: str | None = None,
    ) -> httpx.Response:
        _record_event(
            audit,
            "http",
            str(request.url),
            classification,
            supporting,
            status=status,
            method=request.method,
            reason=reason,
            fixture_route=fixture_route,
        )
        audit["requests"][-1]["response_body"] = copy.deepcopy(body)
        return httpx.Response(status, json=body)

    def handle(request: httpx.Request) -> httpx.Response:
        url = request.url
        if request.method == "GET" and url.scheme == "https" and url.host == CH_HOST:
            search_params_supported = (
                set(url.params).issubset({"q", "items_per_page"})
                and len(url.params.multi_items()) == len(set(url.params))
                and (
                    "items_per_page" not in url.params
                    or (
                        url.params["items_per_page"].isdigit()
                        and 0 < int(url.params["items_per_page"]) <= 100
                    )
                )
            )
            if url.path == "/search/companies" and search_params_supported:
                query = url.params.get("q", "")
                matched_profiles = [
                    item
                    for item in profiles
                    if query.strip()
                    and (
                        _normalise(query) == _normalise(item["profile"].get("company_name", ""))
                        or _normalise(query) == _normalise(item["number"])
                        or any(_matches(record, query) for record in item["records"])
                    )
                ]
                if matched_profiles:
                    supporting = list(
                        {
                            record["id"]: record
                            for item in matched_profiles
                            for record in item["records"]
                        }.values()
                    )
                    if any(item["status"] >= 500 for item in matched_profiles):
                        return respond(
                            request,
                            "scenario_unavailable",
                            supporting,
                            503,
                            {"error": "Declared register source unavailable"},
                        )
                    if any(item["status"] != 200 for item in matched_profiles):
                        return respond(
                            request,
                            "incomplete_fixture",
                            supporting,
                            503,
                            {"error": "No declared company-name search result"},
                        )
                    if any(not item["profile"].get("company_name") for item in matched_profiles):
                        return respond(
                            request,
                            "incomplete_fixture",
                            supporting,
                            503,
                            {"error": "Source does not identify company search titles"},
                        )
                    hits = [
                        {
                            "title": item["profile"]["company_name"],
                            "company_number": item["number"],
                            **{
                                key: value
                                for key, value in item["profile"].items()
                                if key in {"company_status", "date_of_creation"}
                            },
                        }
                        for item in matched_profiles
                    ]
                    return respond(
                        request,
                        "fixture_found",
                        supporting,
                        200,
                        {"items": hits},
                        reason="Search items adapted from declared company profiles.",
                    )
            match = re.fullmatch(r"/company/([A-Za-z0-9]+)", url.path)
            if match and not url.params:
                matching = [item for item in profiles if item["number"].upper() == match[1].upper()]
                if len(matching) == 1:
                    item = matching[0]
                    status = item["status"]
                    classification = (
                        "fixture_found"
                        if status == 200
                        else "scenario_not_found"
                        if status == 404
                        else "scenario_unavailable"
                    )
                    return respond(
                        request,
                        classification,
                        item["records"],
                        status,
                        item["profile"] if status == 200 else {"error": classification},
                        fixture_route=item["url"],
                    )
        route = exact_routes.get((request.method, str(url)))
        if route:
            supporting = [record for record in records if str(httpx.URL(record["url"])) == str(url)]
            status = route["status"]
            classification = (
                "fixture_found"
                if 200 <= status < 300
                else "scenario_not_found"
                if status == 404
                else "scenario_unavailable"
            )
            return respond(
                request,
                classification,
                supporting,
                status,
                route["json"],
                fixture_route=route["url"],
            )
        return respond(
            request,
            "missing_fixture",
            [],
            503,
            {"error": "No declared evidence for this request"},
            reason="Endpoint or request parameters are outside the fixture coverage.",
        )

    return EvaluationSearch(records, audit), httpx.MockTransport(handle), audit
