"""CaseService.add_evidence with image reads: no lock during the read, friendly failures."""

import asyncio
import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.contracts import (
    AgentStarted,
    EvidenceKind,
    OrchestratorMessage,
    ScoreUpdated,
    StudentContext,
)
from app.core.agent import AgentContext
from app.core.ids import new_id
from app.core.llm import FakeLLM
from app.intake import service as intake_service
from app.intake.service import Extracted
from app.orchestrator import service as service_module
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseClosedError, CaseService, Upload, failure_message
from tests.conftest import EmptyAgent, settled

MakeService = Callable[[list | None], CaseService]


@pytest.fixture(autouse=True)
def _uploads_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploads go to a temporary folder, not backend/.uploads."""
    monkeypatch.setattr(intake_service, "UPLOADS_DIR", tmp_path / ".uploads")


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


CHAT_JSON = json.dumps(
    {
        "is_chat": True,
        "app": "whatsapp",
        "other_party": "Mark Evans",
        "lines": [
            {"side": "left", "time": "14:02", "text": "Send the deposit today."},
            {"side": "right", "time": "14:03", "text": "Can I view first?"},
        ],
    }
)
NOT_A_CHAT_TEXT = (
    "That image doesn't look like a chat. If it's a document, upload it as a document instead."
)
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32


def _drain(queue: "asyncio.Queue") -> list:  # type: ignore[type-arg]
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


async def test_not_a_chat_is_stored_without_text_and_the_student_is_told(
    make_service: MakeService, ctx: AgentContext, bus: EventBus
) -> None:  # O4
    assert isinstance(ctx.llm, FakeLLM)
    ctx.llm.responses["chat conversation"] = json.dumps({"is_chat": False})
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())
    queue = bus.subscribe(case.case_id)
    _drain(queue)

    stored = await service.add_evidence(
        case.case_id, Upload(EvidenceKind.CHAT_SCREENSHOT, PNG, "cat.png")
    )

    assert not service._tasks  # no analysis scheduled
    assert stored.evidence[-1].extracted_text is None
    assert stored.messages == []
    assert stored.chat[-1].role == "orchestrator"
    assert stored.chat[-1].text == NOT_A_CHAT_TEXT
    events = _drain(queue)
    assert [e.text for e in events if isinstance(e, OrchestratorMessage)] == [NOT_A_CHAT_TEXT]
    await service.wait_idle()
    events += _drain(queue)
    assert not any(isinstance(e, (AgentStarted, ScoreUpdated)) for e in events)


async def test_a_readable_screenshot_saves_messages_and_runs_the_analysis(
    make_service: MakeService, ctx: AgentContext, bus: EventBus
) -> None:
    assert isinstance(ctx.llm, FakeLLM)
    ctx.llm.responses["chat conversation"] = CHAT_JSON
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())
    queue = bus.subscribe(case.case_id)

    stored = await service.add_evidence(
        case.case_id, Upload(EvidenceKind.CHAT_SCREENSHOT, PNG, "chat.png", student_name="Sam")
    )
    final = await settled(service, case.case_id)

    assert [(m.sender, m.text) for m in stored.messages] == [
        ("agent", "Send the deposit today."),
        ("student", "Can I view first?"),
    ]
    assert "Send the deposit today." in (stored.evidence[-1].extracted_text or "")
    assert len(final.score_history) >= 2 or any(isinstance(e, ScoreUpdated) for e in _drain(queue))


@pytest.mark.parametrize(
    ("data", "text"),
    [
        (HEIC, "I can't open that image type. Please upload a PNG or JPG screenshot."),
        (
            PNG + b"\x00" * (5 * 1024 * 1024),
            "That image is too large. Please upload a smaller screenshot (under 5 MB).",
        ),
    ],
)
async def test_unsupported_and_too_big_images_get_a_friendly_message(
    make_service: MakeService, ctx: AgentContext, data: bytes, text: str
) -> None:
    assert isinstance(ctx.llm, FakeLLM)
    ctx.llm.responses["chat conversation"] = CHAT_JSON
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())

    stored = await service.add_evidence(
        case.case_id, Upload(EvidenceKind.CHAT_SCREENSHOT, data, "big.png")
    )

    assert stored.chat[-1].text == text
    assert stored.evidence[-1].extracted_text is None
    assert not service._tasks
    assert [c for c in ctx.llm.calls if c["method"] == "describe_image"] == []


class GatedLLM(FakeLLM):
    """`describe_image` waits until released: a stand-in for a slow vision call."""

    def __init__(self, response: str) -> None:
        super().__init__({"chat conversation": response})
        self.reading = asyncio.Event()
        self.release = asyncio.Event()

    async def describe_image(self, image: bytes, prompt: str) -> str:
        self.reading.set()
        await self.release.wait()
        return await super().describe_image(image, prompt)


def _gated_service(make_service: MakeService, ctx: AgentContext) -> tuple[CaseService, GatedLLM]:
    llm = GatedLLM(CHAT_JSON)
    service = make_service([EmptyAgent()])
    service.ctx = dataclasses.replace(ctx, llm=llm)
    return service, llm


async def test_lock_is_not_held_during_the_real_read_path(
    make_service: MakeService, ctx: AgentContext
) -> None:  # O13
    service, llm = _gated_service(make_service, ctx)
    case = await service.open_case(StudentContext())
    upload = asyncio.create_task(
        service.add_evidence(case.case_id, Upload(EvidenceKind.CHAT_SCREENSHOT, PNG, "c.png"))
    )
    await asyncio.wait_for(llm.reading.wait(), 1)

    replied = await asyncio.wait_for(service.reply(case.case_id, "Still looking"), 1)

    assert not upload.done()
    assert replied.chat[-1].text == "Still looking"
    llm.release.set()
    stored = await asyncio.wait_for(upload, 1)
    await idle(service)
    assert len(stored.messages) == 2
    assert any(t.text == "Still looking" for t in stored.chat)


async def test_case_decided_while_the_image_is_read_rejects_the_upload(
    make_service: MakeService, ctx: AgentContext
) -> None:  # O14
    service, llm = _gated_service(make_service, ctx)
    case = await service.open_case(StudentContext())
    upload = asyncio.create_task(
        service.add_evidence(case.case_id, Upload(EvidenceKind.CHAT_SCREENSHOT, PNG, "c.png"))
    )
    await asyncio.wait_for(llm.reading.wait(), 1)

    await asyncio.wait_for(service.decide(case.case_id), 1)
    llm.release.set()

    with pytest.raises(CaseClosedError):
        await asyncio.wait_for(upload, 1)
    await idle(service)
    stored = await service.get_case(case.case_id)
    assert stored.evidence == []
    assert stored.messages == []


def test_failure_messages_follow_appendix_c() -> None:
    chat = EvidenceKind.CHAT_SCREENSHOT
    expected = {
        "not a chat": NOT_A_CHAT_TEXT,
        "not a document": (
            "I couldn't find any text in that image. If it's a chat, upload it as messages."
        ),
        "unreadable": (
            "I couldn't read that screenshot clearly. Try a sharper screenshot, or export the "
            "chat as text."
        ),
        "unsupported": "I can't open that image type. Please upload a PNG or JPG screenshot.",
        "too_big": "That image is too large. Please upload a smaller screenshot (under 5 MB).",
        "empty": "That file looks empty. Please try uploading it again.",
        "timeout": "Reading that image took too long. Please try again in a moment.",
        "zip": 'Couldn\'t find the chat text in that zip. Export the chat again "Without media".',
    }
    for reason, text in expected.items():
        assert failure_message(chat, reason) == text
    assert failure_message(chat, "llm_error") == expected["timeout"]
    document = failure_message(EvidenceKind.CONTRACT, "unreadable")
    assert document != expected["unreadable"]
    assert "photo" in document


async def test_an_empty_or_corrupt_file_gets_a_message_and_no_analysis(
    make_service: MakeService,
) -> None:
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext())
    uploads = [
        (Upload(EvidenceKind.CHAT_SCREENSHOT, b"", "empty.png"), "That file looks empty."),
        (Upload(EvidenceKind.CONTRACT, b"%PDF-1.7\n garbage", "c.pdf"), "upload the PDF or Word"),
    ]
    for upload, expected in uploads:
        stored = await service.add_evidence(case.case_id, upload)
        assert not service._tasks  # nothing new to read: no analysis
        assert stored.evidence[-1].extracted_text is None
        assert expected in stored.chat[-1].text
    assert (await service.get_case(case.case_id)).messages == []
