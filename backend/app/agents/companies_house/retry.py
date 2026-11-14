"""Retries with backoff. A failure is never reported as 'not found' (plan section 9, D8)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.agents.companies_house.constants import RETRY_AFTER_CAP_S, RETRY_ATTEMPTS, RETRY_BACKOFF
from app.agents.companies_house.models import Fetch, Outcome

Sleep = Callable[[float], Awaitable[None]]


def retry_after_seconds(response: httpx.Response | None) -> float | None:
    """Seconds from a numeric Retry-After header, else None (HTTP-dates are ignored)."""
    if response is None:
        return None
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _classify(status: int, response: httpx.Response | None) -> tuple[bool, str]:
    """(retry?, error text) for a non-2xx status."""
    if status == 429:
        return True, "429"
    if status >= 500:
        return True, str(status)
    return False, f"{status} {response.reason_phrase if response is not None else ''}".strip()


async def with_retries(
    call: Callable[[], Awaitable[Any]],
    *,
    attempts: int = RETRY_ATTEMPTS,
    backoff: tuple[float, ...] = RETRY_BACKOFF,
    per_try_timeout: float | None = None,
    sleep: Sleep = asyncio.sleep,
    url: str | None = None,
) -> Fetch[Any]:
    """Run `call` up to `attempts` times.

    `call` returns an `httpx.Response` (classified by status) or any other value (success).
    An `httpx.HTTPStatusError` is classified by its response. 2xx gives OK; 404 gives NOT_FOUND
    with no retry; 429 waits max(backoff, Retry-After capped at 10s); 5xx, timeouts and network
    errors retry; any other 4xx fails at once; exhausted attempts give FAILED. Pass a no-op
    `sleep` in tests so nothing really sleeps.
    """
    error = "unknown"
    for attempt in range(attempts):
        response: httpx.Response | None = None
        value: Any = None
        try:
            coro = call()
            value = await (asyncio.wait_for(coro, per_try_timeout) if per_try_timeout else coro)
            if isinstance(value, httpx.Response):
                response = value
        except httpx.HTTPStatusError as exc:
            response = exc.response
        except (TimeoutError, httpx.TimeoutException):
            error = "timeout"
        except httpx.TransportError as exc:
            error = f"network: {exc.__class__.__name__}"
        except Exception as exc:  # noqa: BLE001 - any client failure is a failed attempt
            error = f"error: {exc.__class__.__name__}: {exc}"
        else:
            if response is None:
                return Fetch(Outcome.OK, value, url=url)
            if response.is_success:
                return Fetch(Outcome.OK, response, url=url, status_code=response.status_code)

        if response is not None:
            status = response.status_code
            if status == 404:
                return Fetch(Outcome.NOT_FOUND, url=url, status_code=404)
            retry, error = _classify(status, response)
            if not retry:
                return Fetch(Outcome.FAILED, error=error, url=url, status_code=status)

        if attempt < attempts - 1:
            delay = backoff[min(attempt, len(backoff) - 1)] if backoff else 0.0
            wait = retry_after_seconds(response)
            if wait is not None:
                delay = max(delay, min(wait, RETRY_AFTER_CAP_S))
            await sleep(delay)
    return Fetch(Outcome.FAILED, error=f"{error} after {attempts} attempts", url=url)
