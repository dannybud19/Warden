"""Analysis runs in the background: open_case starts the agency check, requests return at once."""

import _thread
import asyncio
import signal
import threading
from collections.abc import Callable
from typing import Any

import pytest

from app.contracts import (
    AgentStatus,
    Case,
    EvidenceKind,
    Landlord,
    OrchestratorMessage,
    StudentContext,
)
from app.core.agent import AgentContext, BaseAgent, Need
from app.orchestrator import service as service_module
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseService, Upload
from tests.conftest import EmptyAgent

MakeService = Callable[[list | None], CaseService]
AGENCY = Landlord(company_name="Acme Lettings Ltd")


class GateAgent(BaseAgent):
    """Needs a landlord and stays 'running' until `go` is set: a stand-in for a slow check."""

    name = "gate"
    requires = frozenset({Need.LANDLORD})

    def __init__(self) -> None:
        self.go = False
        self.started = False
        self.runs = 0

    async def run(self, case: Case, ctx: AgentContext):  # type: ignore[no-untyped-def]
        self.started = True
        self.runs += 1
        # NOTE: a plain flag, not asyncio.Event: the API test sets it from another thread.
        while not self.go:  # noqa: ASYNC110
            await asyncio.sleep(0.005)
        return self.report(case)


async def _until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not condition():  # noqa: ASYNC110
            await asyncio.sleep(0.005)


async def test_opening_with_an_agency_starts_the_check_in_the_background(
    make_service: MakeService,
) -> None:
    gate = GateAgent()
    service = make_service([gate])
    case = await service.open_case(StudentContext(), None, AGENCY)  # returns while it is running
    await _until(lambda: gate.started)

    assert service.running_agents(case.case_id) == ["gate"]
    assert (await service.get_case(case.case_id)).reports == {}

    gate.go = True
    await service.wait_idle()
    stored = await service.get_case(case.case_id)
    assert stored.reports["gate"].status == AgentStatus.OK
    assert service.running_agents(case.case_id) == []


async def test_opening_without_an_agency_runs_nothing(make_service: MakeService) -> None:
    gate = GateAgent()
    service = make_service([gate])
    case = await service.open_case(StudentContext(), None, Landlord(name="Sam"))
    await service.open_case(StudentContext(), None, None)
    await service.wait_idle()
    assert gate.runs == 0
    assert (await service.get_case(case.case_id)).reports == {}


async def test_upload_during_a_running_check_is_not_blocked_or_lost(
    make_service: MakeService,
) -> None:
    gate = GateAgent()
    service = make_service([gate])
    opened = await service.open_case(StudentContext(), None, AGENCY)
    await _until(lambda: gate.started)

    # The check is still running: the upload and the reply must return at once.
    async with asyncio.timeout(1):
        saved = await service.add_evidence(opened.case_id, Upload(EvidenceKind.EMAIL, b"Hello"))
        await service.add_evidence(opened.case_id, Upload(EvidenceKind.EMAIL, b"Hello again"))
    assert len(saved.evidence) == 1

    gate.go = True
    await service.wait_idle()
    stored = await service.get_case(opened.case_id)
    assert len(stored.evidence) == 2  # the running analysis did not overwrite the uploads
    assert gate.runs == 1  # its input did not change, so the queued analyses skipped it
    # open + the running analysis + ONE queued analysis (the two requests share it)
    assert len(stored.score_history) == 3


async def test_a_failing_analysis_becomes_a_message_not_a_crash(
    make_service: MakeService, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object) -> None:
        raise RuntimeError("crosscheck exploded")

    monkeypatch.setattr(service_module.crosscheck, "compare", boom)
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext(), None, Landlord(name="Sam"))
    queue = bus.subscribe(case.case_id)

    await service.add_evidence(case.case_id, Upload(EvidenceKind.EMAIL, b"Hello"))
    await service.wait_idle()  # does not raise

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    messages = [e for e in events if isinstance(e, OrchestratorMessage)]
    assert len(messages) == 1 and "failed" in messages[0].text
    # the evidence is saved, and a later request can try again
    assert len((await service.get_case(case.case_id)).evidence) == 1


async def test_shutdown_cancels_running_analyses(make_service: MakeService) -> None:
    gate = GateAgent()
    service = make_service([gate])
    await service.open_case(StudentContext(), None, AGENCY)
    await _until(lambda: gate.started)
    await service.shutdown()
    await service.wait_idle()


async def test_wait_idle_does_not_spin_on_a_finished_task_not_yet_removed(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: on Python 3.12 `asyncio.gather` on tasks that are already done returns without
    yielding. Here the analysis scheduled by an upload (awaited as its own task) finishes before
    the done callback that removes it from `_tasks` has run, and `wait_idle` used to loop forever.

    A spinning loop never reaches an `await` timeout. A thread timer schedules an interrupt whose
    handler runs between bytecodes, including on Windows where SIGALRM is unavailable.
    """
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())
    reading, release = asyncio.Event(), asyncio.Event()
    original = service_module.extract

    async def slow_extract(*args: Any) -> Any:
        reading.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(service_module, "extract", slow_extract)

    def timed_out(signum: int, frame: object) -> None:
        raise TimeoutError("wait_idle is spinning")

    previous = signal.signal(signal.SIGINT, timed_out)
    watchdog = threading.Timer(5, _thread.interrupt_main)
    watchdog.daemon = True
    watchdog.start()
    try:
        pending = asyncio.create_task(
            service.add_evidence(case.case_id, Upload(EvidenceKind.EMAIL, b"Hello"))
        )
        await reading.wait()
        await service.reply(case.case_id, "Still looking")
        await service.wait_idle()
        release.set()
        await pending
        await service.wait_idle()
    finally:
        watchdog.cancel()
        watchdog.join()
        signal.signal(signal.SIGINT, previous)
    assert not service._tasks
