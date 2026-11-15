"""CaseService.add_evidence with image reads: no lock during the read, friendly failures."""

import asyncio
from collections.abc import Callable

import pytest

from app.contracts import EvidenceKind, StudentContext
from app.core.ids import new_id
from app.intake.service import Extracted
from app.orchestrator import service as service_module
from app.orchestrator.service import CaseService, Upload
from tests.conftest import EmptyAgent

MakeService = Callable[[list | None], CaseService]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def idle(service: CaseService) -> None:
    """`wait_idle`, after one loop turn.

    NOTE: on Python 3.12 `asyncio.gather` on tasks that are already done returns without
    yielding, so `wait_idle` spins forever if a background analysis finished but its done
    callback (which removes it from `_tasks`) has not run yet. That happens when the upload ran
    in its own task, as here. One `sleep(0)` lets the callback run first.
    """
    await asyncio.sleep(0)
    await service.wait_idle()


async def test_case_lock_is_not_held_while_the_upload_is_read(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow read (stand-in for the vision call) must not block a reply to the same case."""
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())
    reading, release = asyncio.Event(), asyncio.Event()
    lock_held_during_read: list[bool] = []

    async def slow_extract(kind, filename, data, student_name, llm) -> Extracted:  # type: ignore[no-untyped-def]
        lock_held_during_read.append(service._locks[case.case_id].locked())
        reading.set()
        await release.wait()
        return Extracted(new_id("ev"), "[14:02] Agent: hello", [])

    monkeypatch.setattr(service_module, "extract", slow_extract)
    upload = asyncio.create_task(
        service.add_evidence(case.case_id, Upload(EvidenceKind.CHAT_SCREENSHOT, PNG, "chat.png"))
    )
    await asyncio.wait_for(reading.wait(), 1)

    replied = await asyncio.wait_for(service.reply(case.case_id, "I'm still looking"), 1)

    assert not upload.done()  # the reply finished while the read was still pending
    assert replied.chat[-1].text == "I'm still looking"
    release.set()
    stored = await asyncio.wait_for(upload, 1)
    await idle(service)
    assert lock_held_during_read == [False]
    assert stored.evidence[-1].extracted_text == "[14:02] Agent: hello"
    assert any(t.text == "I'm still looking" for t in stored.chat)  # the reply was not lost
