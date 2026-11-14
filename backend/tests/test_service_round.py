"""One analysis round end to end: Cross-checker recap, round message, chat history, reply notes."""

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from app.aggregators.scoring.scoring import load_weights
from app.contracts import (
    ActionStatus,
    AgentReport,
    Case,
    CheckState,
    EvidenceKind,
    Fact,
    FactKey,
    Listing,
    OrchestratorMessage,
    StreamEvent,
    StudentContext,
)
from app.core.agent import AgentContext, BaseAgent, Need
from app.core.llm import FakeLLM
from app.orchestrator import conversation
from app.orchestrator import service as service_module
from app.orchestrator.events import EventBus
from app.orchestrator.service import FAILED_ANALYSIS_TEXT, CaseService, Upload
from app.storage.memory import InMemoryCaseRepo
from tests.conftest import EmptyAgent, add_evidence_and_settle, reply_and_settle

MakeService = Callable[[list | None], CaseService]
LISTING = Listing(address="1 Baker Street, London NW1 6XE", rent_pcm=900)
RENT_RECAP = "Two sources disagree on the rent. Check these before you pay."
EMAIL = Upload(EvidenceKind.EMAIL, b"Hello, the flat is available.")


class RentAgent(BaseAgent):
    """Says the rent is 950 a month, against the listing's 900."""

    name = "rent"

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        fact = Fact(key=FactKey.RENT_PCM, value="950", source="ev_chat", agent=self.name)
        return self.report(case, facts=[fact])


class ContractAddressAgent(BaseAgent):
    """Reads the contract's address: a different property from the listing."""

    name = "contract_address"
    requires = frozenset({Need.CONTRACT})

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        contract = next(e for e in case.evidence if e.kind == EvidenceKind.CONTRACT)
        fact = Fact(
            key=FactKey.ADDRESS,
            value="9 Other Road, London E1 6AN",
            source=contract.id,
            agent=self.name,
        )
        return self.report(case, facts=[fact])


def _drain(queue: Any) -> list[StreamEvent]:
    events: list[StreamEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def _round_events(events: list[StreamEvent]) -> list[str]:
    """Event types without the per-agent progress events."""
    return [e.type for e in events if e.type not in ("agent_started", "agent_finished")]


def _messages(events: list[StreamEvent]) -> list[str]:
    return [e.text for e in events if isinstance(e, OrchestratorMessage)]


async def _open_with_three_actions(service: CaseService, bus: EventBus) -> tuple[Case, Any]:
    case = await service.open_case(StudentContext(), LISTING, None)
    queue = bus.subscribe(case.case_id)
    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert [a.id for a in case.actions] == [
        "act_viewing",
        "act_company_number",
        "act_payment_method",
    ]
    _drain(queue)
    return case, queue


async def test_recap_comes_after_the_score_and_is_sent_once(
    make_service: MakeService, bus: EventBus
) -> None:
    service = make_service([RentAgent()])
    case = await service.open_case(StudentContext(), LISTING, None)
    queue = bus.subscribe(case.case_id)

    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    events = _drain(queue)
    assert _round_events(events) == [
        "score_updated",
        "orchestrator_message",  # the recap
        "actions_proposed",
        "orchestrator_message",  # the round message
    ]
    recap, round_message = _messages(events)
    assert recap == RENT_RECAP
    assert "3 new steps" in round_message and "rent" not in round_message

    report = case.reports["crosscheck"]
    assert report.summary == RENT_RECAP
    assert [f.id for f in report.findings] == ["crosscheck:rent_pcm"]

    # Same disagreement on the next round: no second recap.
    await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert RENT_RECAP not in _messages(_drain(queue))


async def test_address_hard_flag_sends_the_recap_then_decides(
    make_service: MakeService, bus: EventBus
) -> None:
    service = make_service([ContractAddressAgent()])
    case = await service.open_case(StudentContext(), LISTING, None)
    queue = bus.subscribe(case.case_id)

    contract = Upload(EvidenceKind.CONTRACT, b"Tenancy agreement for 9 Other Road, E1 6AN")
    case = await add_evidence_and_settle(service, case.case_id, contract)
    events = _drain(queue)
    assert _round_events(events) == ["score_updated", "orchestrator_message", "decision_made"]
    assert _messages(events) == ["Two sources disagree on the address. Check these before you pay."]
    assert case.status == "decided"


async def test_round_message_when_no_new_steps_but_some_are_open(
    make_service: MakeService, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case, queue = await _open_with_three_actions(service, bus)

    async def nothing_new(*_: object) -> list[object]:
        return []

    monkeypatch.setattr(service_module, "propose_actions", nothing_new)
    await add_evidence_and_settle(service, case.case_id, EMAIL)
    events = _drain(queue)
    assert _round_events(events) == ["score_updated", "orchestrator_message"]
    assert _messages(events) == ["Your risk score is 100/100. 3 steps are still open below."]


async def test_chat_history_is_stored_and_survives_a_reload(
    make_service: MakeService, bus: EventBus
) -> None:
    service = make_service([EmptyAgent()])
    case, _ = await _open_with_three_actions(service, bus)

    await reply_and_settle(service, case.case_id, "yes, they did", action_id="act_viewing")
    stored = await service.repo.get(case.case_id)
    assert stored is not None
    turns = [(t.role, t.action_ids) for t in stored.chat]
    assert turns == [("orchestrator", []), ("student", ["act_viewing"]), ("orchestrator", [])]
    assert stored.chat[1].text == "yes, they did"


async def test_a_reply_that_matches_nothing_changes_nothing_and_says_so(
    make_service: MakeService, bus: EventBus
) -> None:
    service = make_service([EmptyAgent()])
    case, queue = await _open_with_three_actions(service, bus)
    before = [a.model_dump() for a in case.actions]

    # FakeLLM's default "{}" takes the keyword fallback, which cannot pick one of 3 open actions.
    case = await reply_and_settle(service, case.case_id, "ok")
    assert [a.model_dump() for a in case.actions[:3]] == before  # later ones are new proposals
    assert case.chat[-2].action_ids == []
    (message,) = _messages(_drain(queue))
    assert "I couldn't match your message to a step." in message


async def test_a_flagged_payment_answer_asks_for_the_message(
    make_service: MakeService, bus: EventBus, ctx: AgentContext
) -> None:
    assert isinstance(ctx.llm, FakeLLM)
    text = "They asked me to pay the deposit before the viewing"
    ctx.llm.responses["pay the deposit"] = (
        '{"updates": [{"action_id": "act_payment_method", "outcome": "flags", '
        '"quote": "pay the deposit before the viewing", "evidence_ids": []}]}'
    )
    service = make_service([EmptyAgent()])
    case, queue = await _open_with_three_actions(service, bus)

    case = await reply_and_settle(service, case.case_id, text, action_id="act_payment_method")
    payment = next(c for c in case.checks if c.id.value == "payment_safety")
    assert payment.state == CheckState.SUSPICIOUS  # an answer never hard-flags (decision 19)
    (message,) = _messages(_drain(queue))
    assert "Please upload that message so I can check it." in message


async def test_an_action_closed_while_parsing_is_dropped_not_overwritten(
    make_service: MakeService, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([EmptyAgent()])
    case, queue = await _open_with_three_actions(service, bus)
    real_parse = conversation.parse

    async def parse_while_another_reply_lands(*args: Any) -> conversation.ParseResult:
        result = await real_parse(*args)
        stored = await service.repo.get(case.case_id)
        assert stored is not None
        stored.actions[0].status = ActionStatus.SKIPPED  # act_viewing closes meanwhile
        await service.repo.save(stored)
        return result

    monkeypatch.setattr(service_module.conversation, "parse", parse_while_another_reply_lands)
    case = await reply_and_settle(service, case.case_id, "yes", action_id="act_viewing")

    viewing = next(a for a in case.actions if a.id == "act_viewing")
    assert viewing.status == ActionStatus.SKIPPED and viewing.answer is None
    assert case.chat[-2].action_ids == []
    (message,) = _messages(_drain(queue))
    assert "That step was already closed." in message


async def test_a_failed_analysis_is_recorded_in_the_chat(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object) -> None:
        raise RuntimeError("crosscheck exploded")

    monkeypatch.setattr(service_module.crosscheck, "compare", boom)
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext(), None, None)
    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert [(t.role, t.text) for t in case.chat] == [("orchestrator", FAILED_ANALYSIS_TEXT)]


class LockWatchingLLM(FakeLLM):
    """A FakeLLM that records, on every call, whether any case's state lock was held."""

    def __init__(self, service_ref: list[CaseService], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._service_ref = service_ref
        self.locked_during_call: list[bool] = []

    def _record(self) -> None:
        locks = self._service_ref[0]._locks.values()  # noqa: SLF001 - the property under test
        self.locked_during_call.append(any(lock.locked() for lock in locks))

    async def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        self._record()
        return await super().complete(system, user, model=model)

    async def complete_json(self, system: str, user: str, schema: Any, *, model: Any = None) -> Any:
        self._record()
        return await super().complete_json(system, user, schema, model=model)


async def test_no_llm_call_holds_the_state_lock(ctx: AgentContext, bus: EventBus) -> None:
    ref: list[CaseService] = []
    llm = LockWatchingLLM(ref)
    service = CaseService(
        InMemoryCaseRepo(), bus, [EmptyAgent()], dataclasses.replace(ctx, llm=llm), load_weights()
    )
    ref.append(service)
    case, _ = await _open_with_three_actions(service, bus)
    await reply_and_settle(service, case.case_id, "yes", action_id="act_viewing")

    assert len(llm.locked_during_call) >= 3  # parse, consultant reword, composer
    assert not any(llm.locked_during_call)
