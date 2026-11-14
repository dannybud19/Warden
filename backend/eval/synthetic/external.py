"""Evaluation-only clients for controlled evidence; an unknown request never goes online."""

import json
from pathlib import Path
from typing import Any, Literal

import httpx

from app.core.search import SearchResult


class MissingFixtureError(ValueError):
    """A request was not specified by this case; it is not a negative search result."""


class FixtureUnavailableError(RuntimeError):
    """The scenario deliberately models an unavailable external service."""


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"External fixture {field} must be a nonempty string.")
    return value


def _url(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    try:
        parsed = httpx.URL(text)
    except (httpx.InvalidURL, ValueError) as exc:
        raise ValueError(f"External fixture {field} must be an absolute HTTP(S) URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.host
        or parsed.userinfo
        or parsed.fragment
        or any(character.isspace() for character in text)
    ):
        raise ValueError(f"External fixture {field} must be an absolute HTTP(S) URL.")
    return str(parsed)


def _terms(value: Any, field: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"External fixture {field} must contain query terms.")
    for term in value:
        _nonempty_string(term, field)


def _json_body(value: Any) -> None:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("External HTTP JSON body keys must be strings.")
        for item in value.values():
            _json_body(item)
    elif isinstance(value, list):
        for item in value:
            _json_body(item)
    elif value is not None and not isinstance(value, str | bool | int | float):
        raise ValueError("External HTTP body must contain JSON values only.")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("External HTTP body must contain finite JSON values only.") from exc


def validate_external_bundle(bundle: dict[str, Any]) -> None:
    """Reject malformed or ambiguous controlled evidence before a client can consume it."""
    required = {
        "schema_version",
        "records",
        "http_routes",
        "unmatched_request",
        "live_network_allowed",
    }
    if not isinstance(bundle, dict) or set(bundle) != required:
        raise ValueError("External fixture bundle has missing or unexpected fields.")
    if bundle["schema_version"] != "1.0":
        raise ValueError("Unsupported external fixture schema version.")
    if bundle["live_network_allowed"] is not False or bundle["unmatched_request"] != "error":
        raise ValueError("External fixtures must explicitly disable live network fallback.")
    if not isinstance(bundle["records"], list) or not isinstance(bundle["http_routes"], list):
        raise ValueError("External records and HTTP routes must be lists.")
    record_fields = {"id", "key", "query_terms", "outcome", "title", "url", "snippet"}
    record_ids: set[str] = set()
    record_keys: set[str] = set()
    for record in bundle["records"]:
        if (
            not isinstance(record, dict)
            or not record_fields.issubset(record)
            or set(record) - record_fields - {"company_status", "query_alternatives"}
        ):
            raise ValueError("External record has missing or unexpected fields.")
        record_id = _nonempty_string(record["id"], "record id")
        key = _nonempty_string(record["key"], "record key")
        if record_id in record_ids or key in record_keys:
            raise ValueError("External records contain duplicate IDs or keys.")
        record_ids.add(record_id)
        record_keys.add(key)
        _terms(record["query_terms"], "query_terms")
        if "query_alternatives" in record:
            alternatives = record["query_alternatives"]
            if not isinstance(alternatives, list):
                raise ValueError("External query_alternatives must be a list of term lists.")
            for alternative in alternatives:
                _terms(alternative, "query_alternatives")
        if not isinstance(record["outcome"], str) or record["outcome"] not in {
            "found",
            "not_found",
            "unavailable",
        }:
            raise ValueError("External record has an invalid outcome.")
        _nonempty_string(record["title"], "record title")
        if not isinstance(record["snippet"], str):
            raise ValueError("External record snippet must be a string.")
        if record["outcome"] == "found" and not record["snippet"].strip():
            raise ValueError("Found external records must contain source text.")
        _url(record["url"], "record URL")
        company_status = record.get("company_status")
        if company_status is not None and (
            not isinstance(company_status, str) or company_status not in {"active", "dissolved"}
        ):
            raise ValueError("External record has an invalid company status.")
        if company_status is not None and record["outcome"] != "found":
            raise ValueError("An absent or unavailable record cannot verify company status.")
    route_keys: set[tuple[str, str]] = set()
    for route in bundle["http_routes"]:
        if not isinstance(route, dict) or set(route) != {"method", "url", "status", "json"}:
            raise ValueError("External HTTP route has missing or unexpected fields.")
        method = route["method"]
        if not isinstance(method, str) or method not in {
            "GET",
            "HEAD",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
            "TRACE",
        }:
            raise ValueError("External HTTP route has an invalid method.")
        route_key = (method, _url(route["url"], "route URL"))
        if route_key in route_keys:
            raise ValueError("External HTTP fixtures contain duplicate routes.")
        route_keys.add(route_key)
        if type(route["status"]) is not int or not 200 <= route["status"] <= 599:
            raise ValueError("External HTTP route status must be an integer from 200 to 599.")
        _json_body(route["json"])


class FixtureSearch:
    """Read case-specific search evidence while recording which fixtures were exercised."""

    def __init__(self, bundle: dict[str, Any]) -> None:
        validate_external_bundle(bundle)
        self.records = bundle["records"]
        self.queries: list[str] = []

    async def search(
        self, query: str, *, depth: Literal["standard", "deep"] = "standard"
    ) -> list[SearchResult]:
        """Match complete term groups; distinguish unavailable, absent and unspecified."""
        self.queries.append(query)
        normalised = " ".join(query.casefold().split())
        matches = [
            record
            for record in self.records
            if any(
                all(" ".join(term.casefold().split()) in normalised for term in terms)
                for terms in [record["query_terms"], *record.get("query_alternatives", [])]
            )
        ]
        if not matches:
            raise MissingFixtureError("No search fixture matches this request.")
        if any(record["outcome"] == "unavailable" for record in matches):
            raise FixtureUnavailableError("The scenario's search source is unavailable.")
        return [
            SearchResult(title=record["title"], url=record["url"], snippet=record["snippet"])
            for record in matches
            if record["outcome"] == "found"
        ]


def mock_transport(bundle: dict[str, Any]) -> httpx.MockTransport:
    """Build an HTTP transport with explicit responses and no real network capability."""
    validate_external_bundle(bundle)
    routes = {
        (route["method"], str(httpx.URL(route["url"]))): route for route in bundle["http_routes"]
    }

    def handle(request: httpx.Request) -> httpx.Response:
        route = routes.get((request.method, str(request.url)))
        if route is None:
            raise MissingFixtureError("No HTTP fixture matches this request.")
        return httpx.Response(route["status"], json=route["json"])

    return httpx.MockTransport(handle)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"External fixture JSON contains a duplicate field: {key}")
        result[key] = value
    return result


def load_external(path: Path) -> tuple[FixtureSearch, httpx.MockTransport]:
    """Load only controlled response data, never evaluator labels or hidden scenario truth."""
    bundle = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    validate_external_bundle(bundle)
    return FixtureSearch(bundle), mock_transport(bundle)
