"""One analysis round end to end: Cross-checker recap, round message, chat history, reply notes."""

import asyncio
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from app.aggregators.consultant.consultant import reword_prompt
from app.aggregators.scoring.scoring import load_weights
from app.contracts import (
    ActionStatus,
    AgentReport,
    AgentStatus,
    Case,
    CheckState,
    EvidenceKind,
    Fact,
    FactKey,
    Landlord,
    Listing,
    OrchestratorMessage,
    StreamEvent,
    StudentContext,
)
from app.core.agent import AgentContext, BaseAgent, Need
from app.core.llm import FakeLLM
from app.core.settings import Settings
from app.orchestrator import conversation
from app.orchestrator import service as service_module
from app.orchestrator.composer import compose_prompt
from app.orchestrator.conversation import parse_prompt
from app.orchestrator.events import EventBus
from app.orchestrator.service import FAILED_ANALYSIS_TEXT, CaseService, Upload
from app.storage.memory import InMemoryCaseRepo
from tests.conftest import EmptyAgent, add_evidence_and_settle, reply_and_settle
from tests.test_service_background import GateAgent, _until

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
    """A FakeLLM that records, for every call, its system prompt and whether any case's state
    lock was held at that moment."""

    def __init__(self, service_ref: list[CaseService]) -> None:
        super().__init__()
        self._service_ref = service_ref
        self.seen: list[tuple[str, bool]] = []

    def _record(self, system: str) -> None:
        locks = self._service_ref[0]._locks.values()  # noqa: SLF001 - the property under test
        self.seen.append((system, any(lock.locked() for lock in locks)))

    async def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        self._record(system)
        return await super().complete(system, user, model=model)

    async def complete_json(self, system: str, user: str, schema: Any, *, model: Any = None) -> Any:
        self._record(system)
        return await super().complete_json(system, user, schema, model=model)


async def test_no_llm_call_holds_the_state_lock(ctx: AgentContext, bus: EventBus) -> None:
    ref: list[CaseService] = []
    llm = LockWatchingLLM(ref)
    # Real mode so the consultant rewords its actions with the LLM too (the agent list is fixed).
    real = Settings(_env_file=None, default_agent_mode="real", storage="memory")  # type: ignore[call-arg]
    live_ctx = dataclasses.replace(ctx, llm=llm, settings=real)
    service = CaseService(InMemoryCaseRepo(), bus, [EmptyAgent()], live_ctx, load_weights())
    ref.append(service)
    case = await service.open_case(StudentContext(), LISTING, None)
    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    await reply_and_settle(service, case.case_id, "yes", action_id=case.actions[0].id)

    prompts = {system for system, _ in llm.seen}
    assert {parse_prompt(), compose_prompt()} <= prompts
    assert any(system.startswith(reword_prompt()) for system in prompts)  # the consultant
    assert not any(locked for _, locked in llm.seen)


async def test_a_failing_cross_checker_keeps_the_rules_and_the_previous_recap(
    make_service: MakeService, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service([RentAgent()])
    case = await service.open_case(StudentContext(), LISTING, None)
    queue = bus.subscribe(case.case_id)
    await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert RENT_RECAP in _messages(_drain(queue))

    async def broken(*_: object) -> AgentReport:
        raise RuntimeError("cross-checker down")

    monkeypatch.setattr(service_module.crosschecker, "review", broken)
    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    report = case.reports["crosscheck"]
    assert [f.id for f in report.findings] == ["crosscheck:rent_pcm"]  # rule findings kept
    assert report.summary == RENT_RECAP  # so the recap is not re-sent once it recovers

    monkeypatch.undo()
    await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert RENT_RECAP not in _messages(_drain(queue))


async def test_a_failing_cross_checker_still_lets_the_address_hard_flag_decide(
    make_service: MakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: object) -> AgentReport:
        raise RuntimeError("cross-checker down")

    monkeypatch.setattr(service_module.crosschecker, "review", broken)
    service = make_service([ContractAddressAgent()])
    case = await service.open_case(StudentContext(), LISTING, None)
    contract = Upload(EvidenceKind.CONTRACT, b"Tenancy agreement for 9 Other Road, E1 6AN")
    case = await add_evidence_and_settle(service, case.case_id, contract)
    assert case.status == "decided"


async def test_a_recap_that_breaks_the_rules_is_not_relayed(
    make_service: MakeService, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def loud(case: Case, rule_findings: list[Any], ctx: AgentContext) -> AgentReport:
        return AgentReport(
            agent="crosscheck",
            version="x",
            status=AgentStatus.OK,
            input_hash="",
            findings=rule_findings,
            summary="This listing is a scam.",
        )

    monkeypatch.setattr(service_module.crosschecker, "review", loud)
    service = make_service([RentAgent()])
    case = await service.open_case(StudentContext(), LISTING, None)
    queue = bus.subscribe(case.case_id)
    await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert all("scam" not in m for m in _messages(_drain(queue)))


async def test_a_slow_consultant_neither_blocks_nor_decides(
    make_service: MakeService, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hangs(*_: object) -> list[Any]:
        await asyncio.sleep(10)
        return []

    monkeypatch.setattr(service_module, "propose_actions", hangs)
    monkeypatch.setattr(service_module, "CONSULTANT_TIMEOUT_S", 0.01)
    service = make_service([EmptyAgent()])
    case = await service.open_case(StudentContext(), None, None)
    queue = bus.subscribe(case.case_id)
    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    # No actions are open, but a failed consultant is not "nothing left to check".
    assert case.status == "open"
    assert _messages(_drain(queue)) == ["Your risk score is 100/100."]


# Structured updates, questions and the decide route (P2)


class LandlordAgent(BaseAgent):
    """Reads the landlord: reruns whenever the landlord changes (its input hash differs)."""

    name = "landlord_reader"
    requires = frozenset({Need.LANDLORD})

    def __init__(self) -> None:
        self.runs = 0

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        self.runs += 1
        return self.report(case)


async def test_a_company_number_in_a_reply_fills_the_landlord_and_reruns_its_check(
    make_service: MakeService, bus: EventBus, ctx: AgentContext
) -> None:
    assert isinstance(ctx.llm, FakeLLM)
    text = "Their company number is 01234567"
    ctx.llm.responses["company number is"] = (
        '{"updates": [], "fields": [{"field": "landlord.company_number", "value": "01234567", '
        '"quote": "company number is 01234567"}]}'
    )
    agent = LandlordAgent()
    service = make_service([agent])
    case = await service.open_case(StudentContext(), LISTING, Landlord(name="Sam Smith"))
    queue = bus.subscribe(case.case_id)
    case = await add_evidence_and_settle(service, case.case_id, EMAIL)
    assert agent.runs == 1
    _drain(queue)

    case = await reply_and_settle(service, case.case_id, text)
    assert case.landlord is not None and case.landlord.company_number == "01234567"
    assert agent.runs == 2  # the landlord changed, so its check ran again
    (message,) = _messages(_drain(queue))
    assert "I updated: company number." in message
    assert "01234567" not in message


async def test_a_question_is_answered_from_the_case_only(
    make_service: MakeService, bus: EventBus, ctx: AgentContext
) -> None:
    assert isinstance(ctx.llm, FakeLLM)
    ctx.llm.responses["holding deposit normal"] = (
        '{"updates": [], "question": "Is a holding deposit normal?"}'
    )
    service = make_service([EmptyAgent()])
    case, queue = await _open_with_three_actions(service, bus)

    case = await reply_and_settle(service, case.case_id, "Is a holding deposit normal?")
    (message,) = _messages(_drain(queue))
    # FakeLLM writes no prose, so the template answers honestly.
    assert "I can't answer that from your case yet." in message
    assert "I couldn't match" not in message  # a question is not an unmatched reply
    compose_calls = [c for c in ctx.llm.calls if c["system"] == compose_prompt()]
    payload = compose_calls[-1]["user"]
    assert "in person viewing: unverified" in payload  # the case's checks are its grounding


async def test_decide_waits_for_the_running_analysis(make_service: MakeService) -> None:
    gate = GateAgent()
    service = make_service([gate])
    case = await service.open_case(StudentContext(), None, Landlord(company_name="Acme Ltd"))
    await _until(lambda: gate.started)

    decision = asyncio.create_task(service.decide(case.case_id))
    await asyncio.sleep(0.02)
    assert not decision.done()  # the agency check is still running
    gate.go = True
    decided = await decision
    assert decided.status == "decided"
    assert "gate" in decided.reports  # the decision saw the finished analysis
    await service.wait_idle()
