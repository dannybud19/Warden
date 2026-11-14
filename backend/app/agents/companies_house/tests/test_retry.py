import httpx
import pytest

from app.agents.companies_house.models import Outcome
from app.agents.companies_house.retry import with_retries


class Script:
    """An async callable that replays responses or raises, and counts calls."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self.steps = list(steps)
        self.calls = 0

    async def __call__(self) -> httpx.Response:
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


async def test_success_first_try() -> None:
    call, sleeps = Script(httpx.Response(200, json={"a": 1})), Sleeps()
    result = await with_retries(call, sleep=sleeps, url="u")
    assert result.outcome == Outcome.OK and result.url == "u"
    assert result.value is not None and result.value.json() == {"a": 1}
    assert call.calls == 1 and sleeps.delays == []


async def test_404_is_not_retried() -> None:
    call, sleeps = Script(httpx.Response(404)), Sleeps()
    result = await with_retries(call, sleep=sleeps)
    assert result.outcome == Outcome.NOT_FOUND
    assert call.calls == 1 and sleeps.delays == []


async def test_500_500_200_gives_ok_after_three_calls() -> None:
    call, sleeps = Script(httpx.Response(500), httpx.Response(500), httpx.Response(200)), Sleeps()
    result = await with_retries(call, sleep=sleeps)
    assert result.outcome == Outcome.OK
    assert call.calls == 3
    assert sleeps.delays == [1.0, 3.0]  # backoff, recorded not slept


async def test_three_failures_give_failed_never_not_found() -> None:
    call, sleeps = Script(httpx.Response(503)), Sleeps()
    result = await with_retries(call, sleep=sleeps)
    assert result.outcome == Outcome.FAILED
    assert result.error is not None and "503" in result.error and "3 attempts" in result.error
    assert call.calls == 3 and sleeps.delays == [1.0, 3.0]


async def test_429_honours_retry_after_capped_at_ten() -> None:
    call = Script(
        httpx.Response(429, headers={"Retry-After": "5"}),
        httpx.Response(429, headers={"Retry-After": "60"}),
        httpx.Response(200),
    )
    sleeps = Sleeps()
    result = await with_retries(call, sleep=sleeps)
    assert result.outcome == Outcome.OK
    assert sleeps.delays == [5.0, 10.0]  # max(backoff, Retry-After) with the 10s cap


async def test_429_without_header_uses_backoff() -> None:
    call, sleeps = Script(httpx.Response(429), httpx.Response(200)), Sleeps()
    await with_retries(call, sleep=sleeps)
    assert sleeps.delays == [1.0]


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_other_4xx_is_not_retried(status: int) -> None:
    call, sleeps = Script(httpx.Response(status)), Sleeps()
    result = await with_retries(call, sleep=sleeps)
    assert result.outcome == Outcome.FAILED
    assert result.error is not None and result.error.startswith(str(status))
    assert result.status_code == status
    assert call.calls == 1 and sleeps.delays == []


async def test_timeout_and_network_errors_retry() -> None:
    call = Script(httpx.ReadTimeout("slow"), httpx.ConnectError("down"), httpx.Response(200))
    result = await with_retries(call, sleep=Sleeps())
    assert result.outcome == Outcome.OK and call.calls == 3

    call = Script(httpx.ConnectError("down"))
    result = await with_retries(call, sleep=Sleeps())
    assert result.outcome == Outcome.FAILED
    assert result.error is not None and "network" in result.error


async def test_status_error_exception_is_classified() -> None:
    req = httpx.Request("GET", "https://x.test")
    exc = httpx.HTTPStatusError("nope", request=req, response=httpx.Response(404, request=req))
    result = await with_retries(Script(exc), sleep=Sleeps())
    assert result.outcome == Outcome.NOT_FOUND


async def test_non_response_value_is_success() -> None:
    async def call() -> list[int]:
        return [1, 2]

    result = await with_retries(call, sleep=Sleeps())
    assert result.outcome == Outcome.OK and result.value == [1, 2]


async def test_per_try_timeout_counts_as_timeout() -> None:
    import asyncio

    async def slow() -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200)

    result = await with_retries(slow, per_try_timeout=0.01, attempts=2, sleep=Sleeps())
    assert result.outcome == Outcome.FAILED
    assert result.error is not None and "timeout" in result.error
