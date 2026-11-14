"""Offline test helpers: a MockTransport Router, a no-op sleep and a fixed clock (plan App. F).

Lives in the package (not in tests/) so test files can import it without a tests package.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx

TODAY = date(2026, 11, 14)  # the fixed "today" every rule test uses
FIXTURES = Path(__file__).parent / "tests" / "fixtures"

# A route reply: (status, body) or (status, body, headers). body: dict/list = JSON, str = text.
Reply = tuple[int, Any] | tuple[int, Any, dict[str, str]]
Handler = Callable[[httpx.Request], httpx.Response]


async def no_sleep(seconds: float) -> None:
    """Drop-in for asyncio.sleep so retries never really wait. Records nothing."""


def fixture_path(*parts: str) -> Path:
    return FIXTURES.joinpath(*parts)


def fixture_text(*parts: str) -> str:
    return fixture_path(*parts).read_text()


def fixture_json(*parts: str) -> Any:
    return json.loads(fixture_text(*parts))


def reply_response(reply: Reply) -> httpx.Response:
    status, body, *rest = reply
    headers = rest[0] if rest else {}
    if isinstance(body, (dict, list)):
        return httpx.Response(status, json=body, headers=headers)
    if isinstance(body, bytes):
        return httpx.Response(status, content=body, headers=headers)
    return httpx.Response(status, text="" if body is None else str(body), headers=headers)


class Router:
    """MockTransport handler routing by (method, path prefix) and logging every request.

    routes: {("GET", "/company/09123456"): (200, {...})}. The longest matching prefix wins, so
    "/company/09123456/officers" beats "/company/09123456". A key starting with "http" matches
    the full URL prefix instead of the path. A value may be a reply, a list of replies (served in
    order, the last one repeats: e.g. [(500, ""), (500, ""), (200, {...})]) or a handler
    callable. Unmatched requests get 404.
    """

    def __init__(self, routes: dict[tuple[str, str], Reply | list[Reply] | Handler] | None = None):
        self.routes = routes or {}
        self.requests: list[httpx.Request] = []
        self._served: dict[tuple[str, str], int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        best: tuple[str, str] | None = None
        for method, prefix in self.routes:
            target = url if prefix.startswith("http") else request.url.path
            if (
                method == request.method
                and target.startswith(prefix)
                and (best is None or len(prefix) > len(best[1]))
            ):
                best = (method, prefix)
        if best is None:
            return httpx.Response(404)
        route = self.routes[best]
        if callable(route):
            return route(request)
        if isinstance(route, list):
            index = min(self._served.get(best, 0), len(route) - 1)
            self._served[best] = self._served.get(best, 0) + 1
            return reply_response(route[index])
        return reply_response(route)

    def calls(self, prefix: str) -> list[httpx.Request]:
        """Requests whose path (or full URL, for 'http...') starts with `prefix`."""
        return [
            r
            for r in self.requests
            if (str(r.url) if prefix.startswith("http") else r.url.path).startswith(prefix)
        ]
