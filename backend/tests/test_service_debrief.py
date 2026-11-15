"""`CaseService.debrief`: a finished voice call becomes evidence, messages, chat and answers."""

import asyncio
import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.aggregators.scoring.scoring import load_weights
from app.contracts import (
    Action,
    ActionKind,
    ActionStatus,
    Case,
    CheckId,
    EvidenceKind,
    Listing,
    OrchestratorMessage,
    StudentContext,
)
from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.orchestrator import conversation, debrief
from app.orchestrator import service as service_module
from app.orchestrator.composer import RoundNote
from app.orchestrator.debrief import CallAnswer, CallDebrief, CallLine
from app.orchestrator.events import EventBus
from app.orchestrator.service import CaseClosedError, CaseNotFoundError, CaseService, Upload
from app.storage.memory import InMemoryCaseRepo
from tests.conftest import EmptyAgent, add_evidence_and_settle, settled

MakeService = Callable[[list | None], CaseService]
LISTING = Listing(address="1 Baker Street, London NW1 6XE", rent_pcm=900)
EMAIL = Upload(EvidenceKind.EMAIL, b"Hello, the flat is available.")
T0 = datetime(2026, 11, 15, 3, 30, tzinfo=UTC)


def line(role: str, text: str, minutes: int = 0) -> CallLine:
    return CallLine(role, text, T0 + timedelta(minutes=minutes))  # type: ignore[arg-type]


def call(*lines: CallLine, answers: tuple[CallAnswer, ...] = ()) -> CallDebrief:
    return CallDebrief(lines=lines, answers=answers, started_at=T0)


FOUR_LINES = (
    line("orchestrator", "Tell me what happened.", 0),
    line("student", "They asked for a deposit before the viewing.", 1),
    line("orchestrator", "Did you pay?", 2),
    line("student", "Not yet, they want it today.", 3),
)


async def open_with_three_actions(service: CaseService) -> Case:
    """A case with the three first steps open: viewing, company number, payment method."""
    case = await service.open_case(StudentContext(), LISTING, None)
    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert [a.id for a in case.actions] == [
        "act_viewing",
        "act_company_number",
        "act_payment_method",
    ]
    return case


def keep_notes(service: CaseService, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stop the background analysis (which consumes the round notes) and record its requests."""
    scheduled: list[str] = []
    monkeypatch.setattr(service, "_schedule", scheduled.append)
    return scheduled


def note_kinds(service: CaseService, case_id: str) -> list[str]:
    return [n.kind for n in service._notes[case_id]]  # noqa: SLF001 - what the next round says


def parsed_actions(llm: FakeLLM) -> list[str]:
    """The ids of the open actions the last LLM call was asked to read."""
    payload = json.loads(llm.calls[-1]["user"])
    return [a["id"] for a in payload["open_actions"]]


def fake_llm(ctx: AgentContext) -> FakeLLM:
    assert isinstance(ctx.llm, FakeLLM)
    return ctx.llm


async def test_a_call_is_saved_as_evidence_messages_and_chat_and_analysed(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    chat_before = len(case.chat)
    scheduled = keep_notes(service, monkeypatch)

    result = await service.debrief(case.case_id, call(*FOUR_LINES))

    (new_evidence,) = [e for e in result.evidence if e.kind == EvidenceKind.CALL_RECORDING]
    assert new_evidence.extracted_text == debrief.transcript_text(FOUR_LINES)
    assert new_evidence.note == debrief.EVIDENCE_NOTE and new_evidence.filename is None
    call_messages = [m for m in result.messages if m.channel == "call"]
    assert [m.text for m in call_messages] == [
        "They asked for a deposit before the viewing.",
        "Not yet, they want it today.",
    ]
    assert {m.sender for m in call_messages} == {"student"}
    assert {m.evidence_id for m in call_messages} == {new_evidence.id}
    new_turns = result.chat[chat_before:]
    assert [(t.role, t.text) for t in new_turns] == [
        *[(ln.role, ln.text) for ln in FOUR_LINES],
        ("orchestrator", debrief.THANKS_TEXT),
    ]
    assert scheduled == [case.case_id]
    stored = await service.get_case(case.case_id)
    assert stored.model_dump() == result.model_dump()


async def test_a_call_moves_the_analysis_on_in_the_background(
    make_service: MakeService,
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    chat_before = len(case.chat)
    scores_before = len(case.score_history)

    await service.debrief(case.case_id, call(*FOUR_LINES))
    after = await settled(service, case.case_id)

    assert len(after.score_history) > scores_before  # an analysis round ran after the call
    texts = [t.text for t in after.chat[chat_before:]]
    assert texts[4] == debrief.THANKS_TEXT and len(texts) > 5  # then the round message


async def test_only_the_thanks_message_is_published_not_the_calls_lines(
    make_service: MakeService, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    queue = bus.subscribe(case.case_id)
    keep_notes(service, monkeypatch)

    await service.debrief(case.case_id, call(*FOUR_LINES))

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert [(type(e), e.text) for e in events] == [(OrchestratorMessage, debrief.THANKS_TEXT)]


async def test_an_explicit_answer_closes_its_action_and_the_transcript_leaves_it_alone(
    make_service: MakeService, ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = fake_llm(ctx)
    llm.responses["no viewing until I pay"] = json.dumps(
        {
            "updates": [
                {
                    "action_id": "act_viewing",
                    "outcome": "flags",
                    "quote": "no viewing until I pay",
                }
            ]
        }
    )
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)

    answer = CallAnswer("act_viewing", "They said no viewing until I pay")
    result = await service.debrief(case.case_id, call(*FOUR_LINES, answers=(answer,)))

    viewing = next(a for a in result.actions if a.id == "act_viewing")
    assert viewing.status == ActionStatus.DONE and viewing.outcome == "flags"
    assert viewing.answer == "no viewing until I pay"
    assert parsed_actions(llm) == ["act_company_number", "act_payment_method"]  # transcript read
    assert next(a for a in result.actions if a.id == "act_company_number").status == (
        ActionStatus.OPEN
    )
    assert "answered" in note_kinds(service, case.case_id)


async def test_a_skipped_explicit_answer_needs_no_reading(
    make_service: MakeService, ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)

    answer = CallAnswer("act_payment_method", "I'd rather not say", "skipped")
    result = await service.debrief(case.case_id, call(*FOUR_LINES, answers=(answer,)))

    payment = next(a for a in result.actions if a.id == "act_payment_method")
    assert payment.status == ActionStatus.SKIPPED and payment.answer == "I'd rather not say"
    assert "act_payment_method" not in parsed_actions(fake_llm(ctx))


async def test_an_answer_for_a_closed_or_unknown_action_is_dropped_with_one_note(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    await service.reply(case.case_id, "skip", action_id="act_viewing", status="skipped")
    await service.wait_idle()
    keep_notes(service, monkeypatch)
    service._notes[case.case_id].clear()  # noqa: SLF001

    answers = (
        CallAnswer("act_viewing", "too late"),  # closed
        CallAnswer("act_nope", "who?"),  # unknown
    )
    result = await service.debrief(case.case_id, call(*FOUR_LINES, answers=answers))

    viewing = next(a for a in result.actions if a.id == "act_viewing")
    assert viewing.status == ActionStatus.SKIPPED and viewing.answer != "too late"
    assert any(e.kind == EvidenceKind.CALL_RECORDING for e in result.evidence)  # call still saved
    assert note_kinds(service, case.case_id).count("dropped") == 1


async def test_a_repeated_answer_for_one_action_keeps_the_first_and_notes_the_drop(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)
    answers = (
        CallAnswer("act_viewing", "first", "skipped"),
        CallAnswer("act_viewing", "second", "skipped"),
    )

    result = await service.debrief(case.case_id, call(*FOUR_LINES, answers=answers))

    assert next(a for a in result.actions if a.id == "act_viewing").answer == "first"
    assert note_kinds(service, case.case_id).count("dropped") == 1


async def test_a_company_number_said_on_the_call_fills_the_landlord_and_stays_unmasked(
    make_service: MakeService, ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm(ctx).responses["01680058"] = json.dumps(
        {
            "updates": [],
            "fields": [
                {
                    "field": "landlord.company_number",
                    "value": "01680058",
                    "quote": "company number is 01680058",
                }
            ],
        }
    )
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)
    lines = (
        line("orchestrator", "Do you have the company number?"),
        line("student", "Yes, the company number is 01680058, it was on their email.", 1),
    )

    result = await service.debrief(case.case_id, call(*lines))

    assert result.landlord is not None and result.landlord.company_number == "01680058"
    call_evidence = next(e for e in result.evidence if e.kind == EvidenceKind.CALL_RECORDING)
    assert "01680058" in (call_evidence.extracted_text or "")
    assert any("01680058" in m.text for m in result.messages if m.channel == "call")
    kinds = note_kinds(service, case.case_id)
    assert "field_changed" in kinds
    assert [n for n in service._notes[case.case_id] if n.kind == "answered"][-1] == (  # noqa: SLF001
        RoundNote(kind="answered", text="call debrief: 0 answers, 1 facts")
    )


async def test_a_call_that_answers_two_open_actions_updates_both(
    make_service: MakeService, ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm(ctx).responses["refused a viewing"] = json.dumps(
        {
            "updates": [
                {
                    "action_id": "act_viewing",
                    "outcome": "flags",
                    "quote": "they refused a viewing",
                },
                {
                    "action_id": "act_company_number",
                    "outcome": "flags",
                    "quote": "won't give me the company number",
                },
            ]
        }
    )
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)
    lines = (
        line("student", "They refused a viewing and they won't give me the company number.", 1),
    )

    result = await service.debrief(case.case_id, call(*lines))

    by_id = {a.id: a for a in result.actions}
    for action_id in ("act_viewing", "act_company_number"):
        assert by_id[action_id].status == ActionStatus.DONE
        assert by_id[action_id].outcome == "flags"
    assert by_id["act_payment_method"].status == ActionStatus.OPEN
    summary = [n for n in service._notes[case.case_id] if n.text.startswith("call debrief")]  # noqa: SLF001
    assert [n.text for n in summary] == ["call debrief: 2 answers, 0 facts"]


class DownLLM(FakeLLM):
    """An LLM that is down: every structured call fails."""

    async def complete_json(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        raise ConnectionError("llm is down: private words here")


async def test_when_the_llm_is_down_the_call_is_saved_and_keywords_answer_the_one_open_step(
    ctx: AgentContext, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    down_ctx = dataclasses.replace(ctx, llm=DownLLM())
    service = CaseService(InMemoryCaseRepo(), bus, [EmptyAgent()], down_ctx, load_weights())
    case = Case(
        case_id="case_one",
        created_at=T0,
        actions=[
            Action(
                id="act_viewing",
                check_id=CheckId.IN_PERSON_VIEWING,
                kind=ActionKind.QUESTION,
                text="Can you view it in person?",
            )
        ],
    )
    await service.repo.create(case)
    keep_notes(service, monkeypatch)

    result = await service.debrief(
        "case_one", call(line("student", "No, they refused to show me."))
    )

    assert any(e.kind == EvidenceKind.CALL_RECORDING for e in result.evidence)
    assert [m.channel for m in result.messages] == ["call"]
    assert result.chat[0].text == "No, they refused to show me."
    viewing = result.actions[0]
    assert viewing.status == ActionStatus.DONE and viewing.outcome == "flags"


async def test_the_same_note_from_two_readings_reaches_the_round_message_once(
    ctx: AgentContext, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    down_ctx = dataclasses.replace(ctx, llm=DownLLM())
    service = CaseService(InMemoryCaseRepo(), bus, [EmptyAgent()], down_ctx, load_weights())
    steps = [
        Action(id=f"act_{check.value}", check_id=check, kind=ActionKind.QUESTION, text="Ask?")
        for check in (CheckId.PAYMENT_SAFETY, CheckId.IN_PERSON_VIEWING)
    ]
    await service.repo.create(Case(case_id="case_two", created_at=T0, actions=steps))
    keep_notes(service, monkeypatch)
    answers = tuple(
        CallAnswer(a.id, "No, they refused: they want the deposit before I pay") for a in steps
    )

    await service.debrief("case_two", call(line("student", "Hello."), answers=answers))

    kinds = note_kinds(service, "case_two")
    assert kinds.count("upload_hint") == 1
    assert kinds.count("answered") == 3  # one per step, plus the call summary


async def test_a_parser_crash_still_saves_the_call_and_never_raises(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)

    async def boom(*_: Any) -> conversation.ParseResult:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(service_module.conversation, "read_reply", boom)
    result = await service.debrief(case.case_id, call(*FOUR_LINES))

    assert any(e.kind == EvidenceKind.CALL_RECORDING for e in result.evidence)
    assert len([m for m in result.messages if m.channel == "call"]) == 2
    assert {a.status for a in result.actions} == {ActionStatus.OPEN}


class GatedLLM(FakeLLM):
    """Holds the debrief's transcript parse (a call containing MARKER) until `gate` is set."""

    MARKER = "gate-me"

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def complete_json(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        if self.MARKER in user:
            self.entered.set()
            await self.gate.wait()
        return await super().complete_json(system, user, schema, **kwargs)


async def test_the_transcript_parse_runs_without_the_state_lock(
    ctx: AgentContext, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = GatedLLM()
    llm.responses[GatedLLM.MARKER] = json.dumps(
        {
            "updates": [
                {"action_id": "act_viewing", "outcome": "flags", "quote": "refused the viewing"},
                {"action_id": "act_payment_method", "outcome": "clears", "quote": "gate-me"},
            ]
        }
    )
    service = CaseService(
        InMemoryCaseRepo(), bus, [EmptyAgent()], dataclasses.replace(ctx, llm=llm), load_weights()
    )
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)
    service._notes[case.case_id].clear()  # noqa: SLF001

    spoken = line("student", "They refused the viewing, gate-me", 1)
    task = asyncio.create_task(service.debrief(case.case_id, call(spoken)))
    async with asyncio.timeout(2):
        await llm.entered.wait()
    assert not service._locks[case.case_id].locked()  # noqa: SLF001 - the property under test
    async with asyncio.timeout(2):  # a reply lands while the debrief's parse is blocked
        await service.reply(
            case.case_id, "skip it", action_id="act_payment_method", status="skipped"
        )
    assert not task.done()

    llm.gate.set()
    result = await asyncio.wait_for(task, 2)

    by_id = {a.id: a for a in result.actions}
    assert by_id["act_viewing"].status == ActionStatus.DONE  # the debrief's reading landed
    assert by_id["act_payment_method"].status == ActionStatus.SKIPPED  # the reply's was kept
    assert by_id["act_payment_method"].answer == "skip it"
    assert "dropped" in note_kinds(service, case.case_id)  # the closed step is reported
    assert any(e.kind == EvidenceKind.CALL_RECORDING for e in result.evidence)


async def test_a_decided_case_refuses_a_debrief_and_saves_nothing(
    make_service: MakeService,
) -> None:
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext(), LISTING, None)
    decided = await service.decide(case.case_id)
    assert decided.status == "decided"

    with pytest.raises(CaseClosedError):
        await service.debrief(case.case_id, call(*FOUR_LINES))
    stored = await service.get_case(case.case_id)
    assert stored.evidence == [] and stored.messages == []


async def test_an_unknown_case_raises_not_found(make_service: MakeService) -> None:
    service = make_service([EmptyAgent()])
    with pytest.raises(CaseNotFoundError):
        await service.debrief("case_nope", call(*FOUR_LINES))


async def test_a_long_call_is_stored_whole_but_the_parser_reads_the_last_8000_characters(
    make_service: MakeService, ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)
    lines = []
    for i in range(50):
        lines.append(line("orchestrator", f"Question {i}?", 2 * i))
        lines.append(line("student", f"answer {i:02d} " + "x" * 290, 2 * i + 1))
    assert len(lines) > 40
    full_student_text = "\n".join(ln.text for ln in lines if ln.role == "student")
    assert len(full_student_text) > 12000
    chat_before = len(case.chat)

    result = await service.debrief(case.case_id, call(*lines))

    sent = json.loads(fake_llm(ctx).calls[-1]["user"])["reply"]
    assert len(sent) == debrief.PARSER_MAX_CHARS
    assert full_student_text.endswith(sent)
    call_evidence = next(e for e in result.evidence if e.kind == EvidenceKind.CALL_RECORDING)
    assert (call_evidence.extracted_text or "").count("\n") == len(lines) - 1
    assert "answer 00 " in (call_evidence.extracted_text or "")
    assert len(result.chat) - chat_before == len(lines) + 1  # every line, then the thanks
    assert len([m for m in result.messages if m.channel == "call"]) == 50


async def test_a_bank_account_said_on_the_call_is_never_stored_or_sent_to_the_llm(
    make_service: MakeService, ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case = await open_with_three_actions(service)
    keep_notes(service, monkeypatch)
    lines = (
        line("student", "They told me to pay into account 12345678 sort code 12-34-56.", 1),
        line("orchestrator", "Noted.", 2),
        line("student", "You can reach the agent on 07700 900123.", 3),
    )
    answers = (CallAnswer("act_payment_method", "I was told account 12345678", "done"),)

    result = await service.debrief(case.case_id, call(*lines, answers=answers))

    call_evidence = next(e for e in result.evidence if e.kind == EvidenceKind.CALL_RECORDING)
    stored = [
        call_evidence.extracted_text or "",
        *[m.text for m in result.messages if m.channel == "call"],
        *[t.text for t in result.chat],
        *[a.answer or "" for a in result.actions],
    ]
    for text in stored:
        assert "12345678" not in text and "12-34-56" not in text
    assert "07700 900123" in (call_evidence.extracted_text or "")
    assert any("07700 900123" in m.text for m in result.messages)
    for sent in fake_llm(ctx).calls:
        assert "12345678" not in sent["user"] and "12-34-56" not in sent["user"]
