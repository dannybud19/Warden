"""The reply parser: LLM mapping onto open actions, its keyword fallback, and `apply`."""

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from app.contracts import Action, ActionKind, ActionStatus, Case, CheckId
from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.orchestrator import conversation
from app.orchestrator.conversation import (
    ActionUpdate,
    InvalidActionError,
    ParseResult,
    apply,
    keyword_outcome,
    parse,
    parse_prompt,
    validate_target,
)

T = TypeVar("T", bound=BaseModel)

COMPANY = "ask_company_number"
VIEWING = "book_viewing"
DEPOSIT = "deposit_scheme"


class RaisingLLM:
    """An LLM that fails on every call, and counts the calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        self.calls += 1
        raise RuntimeError("llm down")

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        self.calls += 1
        raise RuntimeError("llm down")

    async def describe_image(self, image: bytes, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("llm down")


class SlowLLM(RaisingLLM):
    """An LLM that never answers in time."""

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        await asyncio.sleep(1)
        raise AssertionError("the timeout should have fired")


def action(action_id: str, text: str, status: ActionStatus = ActionStatus.OPEN) -> Action:
    return Action(
        id=action_id,
        check_id=CheckId.LANDLORD_IDENTITY,
        kind=ActionKind.QUESTION,
        text=text,
        status=status,
    )


def make_case(*actions: Action) -> Case:
    return Case(case_id="c1", created_at=datetime(2026, 11, 14, tzinfo=UTC), actions=list(actions))


def three_open() -> Case:
    return make_case(
        action(COMPANY, "Ask the agent for their company number."),
        action(VIEWING, "Book an in-person viewing before paying anything."),
        action(DEPOSIT, "Ask which deposit scheme they use."),
    )


def one_open() -> Case:
    return make_case(action(COMPANY, "Is the agency on the Companies House register?"))


def llm_json(*updates: dict[str, Any]) -> str:
    return json.dumps({"updates": list(updates), "question": None})


def upd(action_id: str, outcome: str, quote: str, evidence_ids: list[str] | None = None) -> dict:
    return {
        "action_id": action_id,
        "outcome": outcome,
        "quote": quote,
        "evidence_ids": evidence_ids or [],
    }


def with_llm(ctx: AgentContext, llm: Any) -> AgentContext:
    return replace(ctx, llm=llm)


def fake(ctx: AgentContext, default: str) -> tuple[AgentContext, FakeLLM]:
    llm = FakeLLM(default=default)
    return with_llm(ctx, llm), llm


def outcomes(result: ParseResult) -> dict[str, str]:
    return {u.action_id: u.outcome for u in result.updates}


# validate_target


def test_validate_target_accepts_none_and_open_ids() -> None:
    case = one_open()
    validate_target(case, None)
    validate_target(case, COMPANY)


def test_validate_target_rejects_unknown_and_closed_ids() -> None:
    case = make_case(action(COMPANY, "q", ActionStatus.DONE))
    with pytest.raises(InvalidActionError, match="unknown action: nope"):
        validate_target(case, "nope")
    with pytest.raises(InvalidActionError, match=f"action is not open: {COMPANY}"):
        validate_target(case, COMPANY)


async def test_parse_raises_for_unknown_target_before_the_llm(ctx: AgentContext) -> None:
    llm = RaisingLLM()
    with pytest.raises(InvalidActionError):
        await parse(one_open(), "yes", [], "nope", None, with_llm(ctx, llm))
    assert llm.calls == 0


# Free text


async def test_free_text_updates_two_of_three_actions(ctx: AgentContext) -> None:
    text = "They gave me company number 01234567 but won't do a viewing before I pay"
    reply = llm_json(
        upd(COMPANY, "clears", "They gave me company number 01234567"),
        upd(VIEWING, "flags", "won't do a viewing before I pay"),
    )
    ctx, llm = fake(ctx, reply)

    result = await parse(three_open(), text, [], None, None, ctx)

    assert outcomes(result) == {COMPANY: "clears", VIEWING: "flags"}
    assert all(u.status == "done" for u in result.updates)
    assert not result.used_fallback and not result.unmatched
    (call,) = llm.calls
    assert call["system"] == parse_prompt()
    payload = json.loads(call["user"])
    assert payload["reply"] == text
    assert payload["evidence_ids"] == []
    assert [a["id"] for a in payload["open_actions"]] == [COMPANY, VIEWING, DEPOSIT]


async def test_payload_keeps_non_ascii_text(ctx: AgentContext) -> None:
    ctx, llm = fake(ctx, llm_json())
    await parse(one_open(), "Deposit is £950", [], None, None, ctx)
    assert "£950" in llm.calls[0]["user"]


async def test_free_text_prompt_lists_only_open_actions(ctx: AgentContext) -> None:
    case = make_case(action(COMPANY, "q1", ActionStatus.DONE), action(VIEWING, "q2"))
    ctx, llm = fake(ctx, llm_json())
    await parse(case, "hello", [], None, None, ctx)
    assert [a["id"] for a in json.loads(llm.calls[0]["user"])["open_actions"]] == [VIEWING]


async def test_registered_reply_clears_where_keywords_would_flag(ctx: AgentContext) -> None:
    # Keywords read "No" as a refusal; this is why the LLM reads replies first.
    text = "No problem, they're registered"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", "they're registered")))

    result = await parse(one_open(), text, [], None, None, ctx)

    assert outcomes(result) == {COMPANY: "clears"}
    assert keyword_outcome(text) == "flags"


async def test_registered_reply_takes_keyword_flags_when_llm_raises(ctx: AgentContext) -> None:
    # Documented limitation of the fallback.
    text = "No problem, they're registered"
    result = await parse(one_open(), text, [], None, None, with_llm(ctx, RaisingLLM()))
    assert outcomes(result) == {COMPANY: "flags"}
    assert result.used_fallback


async def test_refusal_flags(ctx: AgentContext) -> None:
    text = "they refused to give a company number"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "flags", "refused to give a company number")))
    result = await parse(one_open(), text, [], None, None, ctx)
    assert outcomes(result) == {COMPANY: "flags"}


async def test_quote_not_in_text_is_dropped(ctx: AgentContext) -> None:
    text = "They gave me the company number"
    reply = llm_json(
        upd(COMPANY, "clears", "gave me the company number"),
        upd(VIEWING, "clears", "we did the viewing yesterday"),
    )
    ctx, _ = fake(ctx, reply)
    result = await parse(three_open(), text, [], None, None, ctx)
    assert outcomes(result) == {COMPANY: "clears"}


@pytest.mark.parametrize("quote", ["", "   ", "a" * (conversation.MAX_QUOTE_CHARS + 1)])
async def test_empty_or_long_quote_is_dropped(ctx: AgentContext, quote: str) -> None:
    text = "a" * 300
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", quote)))
    result = await parse(three_open(), text, [], None, None, ctx)
    assert result == ParseResult(unmatched=True)


async def test_quote_matches_after_normalising_quotes_and_spaces(ctx: AgentContext) -> None:
    text = "They’re   REGISTERED with\nCompanies House"
    quote = "they're registered with companies house"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", quote)))
    result = await parse(one_open(), text, [], None, None, ctx)
    assert result.updates == (ActionUpdate(COMPANY, "done", "clears", quote),)


async def test_curly_quote_from_llm_matches_straight_text(ctx: AgentContext) -> None:
    text = 'He said "pay now" and won\'t show it'
    quote = "He said “pay now” and won’t show it"
    ctx, _ = fake(ctx, llm_json(upd(VIEWING, "flags", quote)))
    result = await parse(three_open(), text, [], None, None, ctx)
    assert outcomes(result) == {VIEWING: "flags"}


async def test_update_for_closed_action_is_discarded(ctx: AgentContext) -> None:
    case = make_case(action(COMPANY, "q1", ActionStatus.DONE), action(VIEWING, "q2"))
    text = "got the number and saw the flat"
    reply = llm_json(
        upd(COMPANY, "clears", "got the number"),
        upd(VIEWING, "clears", "saw the flat"),
    )
    ctx, _ = fake(ctx, reply)
    result = await parse(case, text, [], None, None, ctx)
    assert outcomes(result) == {VIEWING: "clears"}


async def test_duplicate_updates_keep_the_first(ctx: AgentContext) -> None:
    text = "saw the flat, all fine"
    reply = llm_json(
        upd(VIEWING, "clears", "saw the flat"),
        upd(VIEWING, "neutral", "all fine"),
    )
    ctx, _ = fake(ctx, reply)
    result = await parse(three_open(), text, [], None, None, ctx)
    assert result.updates == (ActionUpdate(VIEWING, "done", "clears", "saw the flat"),)


async def test_empty_updates_on_free_text_is_unmatched(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json())
    result = await parse(three_open(), "ok", [], None, None, ctx)
    assert result == ParseResult(unmatched=True)


async def test_all_quotes_dropped_on_free_text_is_unmatched(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", "not in the reply")))
    result = await parse(three_open(), "ok", [], None, None, ctx)
    assert result == ParseResult(unmatched=True)


async def test_no_open_actions_is_unmatched_without_llm(ctx: AgentContext) -> None:
    llm = RaisingLLM()
    case = make_case(action(COMPANY, "q", ActionStatus.DONE))
    result = await parse(case, "hello", [], None, None, with_llm(ctx, llm))
    assert result == ParseResult(unmatched=True)
    assert llm.calls == 0


# Targeted replies


async def test_targeted_reply_discards_updates_for_other_ids(ctx: AgentContext) -> None:
    text = "saw the flat and they gave the number"
    reply = llm_json(
        upd(COMPANY, "clears", "they gave the number"),
        upd(VIEWING, "clears", "saw the flat"),
    )
    ctx, llm = fake(ctx, reply)

    result = await parse(three_open(), text, [], VIEWING, "done", ctx)

    assert outcomes(result) == {VIEWING: "clears"}
    assert [a["id"] for a in json.loads(llm.calls[0]["user"])["open_actions"]] == [VIEWING]


async def test_targeted_reply_with_empty_updates_is_done_neutral(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json())
    result = await parse(three_open(), "yes", ["e1"], VIEWING, None, ctx)
    assert result == ParseResult(updates=(ActionUpdate(VIEWING, "done", "neutral", "", ("e1",)),))


async def test_targeted_reply_with_all_quotes_dropped_is_done_neutral(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json(upd(VIEWING, "clears", "made up quote")))
    result = await parse(three_open(), "yes", [], VIEWING, "done", ctx)
    assert result == ParseResult(updates=(ActionUpdate(VIEWING, "done", "neutral", ""),))


@pytest.mark.parametrize("status", ["skipped", "impossible"])
async def test_skipped_and_impossible_never_call_the_llm(ctx: AgentContext, status: Any) -> None:
    llm = RaisingLLM()
    result = await parse(three_open(), "can't", ["e2", "e1"], DEPOSIT, status, with_llm(ctx, llm))
    assert result == ParseResult(
        updates=(ActionUpdate(DEPOSIT, status, "neutral", "", ("e2", "e1")),)
    )
    assert llm.calls == 0


# Fallback


async def test_llm_error_falls_back_on_one_open_action(
    ctx: AgentContext, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = await parse(
            one_open(), "yes, confirmed", ["e1"], None, None, with_llm(ctx, RaisingLLM())
        )
    assert result == ParseResult(
        updates=(ActionUpdate(COMPANY, "done", "clears", "", ("e1",)),), used_fallback=True
    )
    assert "parse fallback: RuntimeError" in caplog.text


async def test_llm_error_with_two_open_actions_is_unmatched(ctx: AgentContext) -> None:
    result = await parse(three_open(), "yes", [], None, None, with_llm(ctx, RaisingLLM()))
    assert result == ParseResult(used_fallback=True, unmatched=True)


async def test_llm_error_on_targeted_reply_uses_keywords(ctx: AgentContext) -> None:
    result = await parse(
        three_open(), "they refused", [], VIEWING, "done", with_llm(ctx, RaisingLLM())
    )
    assert result == ParseResult(
        updates=(ActionUpdate(VIEWING, "done", "flags", ""),), used_fallback=True
    )


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        "{}",  # FakeLLM's default: `updates` is required, so this is a schema error
        '{"updates": [{"action_id": "ask_company_number", "outcome": "maybe", "quote": "yes"}]}',
    ],
)
async def test_bad_llm_output_falls_back(ctx: AgentContext, reply: str) -> None:
    ctx, _ = fake(ctx, reply)
    result = await parse(one_open(), "yes", [], None, None, ctx)
    assert result.used_fallback
    assert outcomes(result) == {COMPANY: "clears"}


async def test_ctx_fake_llm_default_takes_the_fallback(ctx: AgentContext) -> None:
    result = await parse(one_open(), "yes", [], None, None, ctx)
    assert result.used_fallback


async def test_all_unknown_ids_fall_back(
    ctx: AgentContext, caplog: pytest.LogCaptureFixture
) -> None:
    ctx, _ = fake(ctx, llm_json(upd("invented", "clears", "yes")))
    with caplog.at_level(logging.WARNING):
        result = await parse(one_open(), "yes", [], None, None, ctx)
    assert result.used_fallback
    assert outcomes(result) == {COMPANY: "clears"}
    assert "parse fallback: unknown action ids" in caplog.text


async def test_some_unknown_ids_are_discarded_without_fallback(ctx: AgentContext) -> None:
    reply = llm_json(upd("invented", "clears", "yes"), upd(COMPANY, "clears", "yes"))
    ctx, _ = fake(ctx, reply)
    result = await parse(three_open(), "yes", [], None, None, ctx)
    assert not result.used_fallback
    assert outcomes(result) == {COMPANY: "clears"}


async def test_a_free_text_hedge_does_not_close_a_step(ctx: AgentContext) -> None:
    text = "I'll ask them for the number tomorrow"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "neutral", "I'll ask them for the number")))
    result = await parse(three_open(), text, [], None, None, ctx)
    assert result.updates == () and result.unmatched
    # The same reading on the step's own card does answer it.
    targeted = await parse(three_open(), text, [], COMPANY, None, ctx)
    assert outcomes(targeted) == {COMPANY: "neutral"}


async def test_llm_timeout_falls_back(ctx: AgentContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation, "PARSE_TIMEOUT_S", 0.01)
    result = await parse(one_open(), "yes", [], None, None, with_llm(ctx, SlowLLM()))
    assert result.used_fallback
    assert outcomes(result) == {COMPANY: "clears"}


# Evidence ids


async def test_listed_evidence_ids_keep_only_the_replys(ctx: AgentContext) -> None:
    text = "here is the number and the viewing booking"
    reply = llm_json(
        upd(COMPANY, "clears", "here is the number", ["e1", "invented", "e1"]),
        upd(VIEWING, "clears", "the viewing booking"),
    )
    ctx, _ = fake(ctx, reply)
    result = await parse(three_open(), text, ["e1", "e2"], None, None, ctx)
    assert {u.action_id: u.evidence_ids for u in result.updates} == {COMPANY: ("e1",), VIEWING: ()}


async def test_no_listed_evidence_ids_go_to_every_done_update(ctx: AgentContext) -> None:
    text = "here is the number and the viewing booking"
    reply = llm_json(
        upd(COMPANY, "clears", "here is the number"),
        upd(VIEWING, "clears", "the viewing booking", ["invented"]),
    )
    ctx, _ = fake(ctx, reply)
    result = await parse(three_open(), text, ["e1", "e2"], None, None, ctx)
    assert [u.evidence_ids for u in result.updates] == [("e1", "e2"), ("e1", "e2")]


# apply


def test_apply_updates_open_actions_and_drops_closed_ones() -> None:
    actions = [
        action(COMPANY, "q1"),
        action(VIEWING, "q2", ActionStatus.SKIPPED),
        action(DEPOSIT, "q3"),
    ]
    before = [a.model_copy(deep=True) for a in actions]
    result = ParseResult(
        updates=(
            ActionUpdate(VIEWING, "done", "clears", "saw it"),
            ActionUpdate("gone", "done", "clears", "x"),
            ActionUpdate(COMPANY, "done", "flags", "refused", ("e1",)),
            ActionUpdate(DEPOSIT, "impossible", "neutral"),
        )
    )

    new, dropped = apply(actions, result, "the reply")

    assert actions == before
    assert dropped == [VIEWING, "gone"]
    company, viewing, deposit = new
    assert (company.status, company.outcome, company.answer) == (
        ActionStatus.DONE,
        "flags",
        "the reply",
    )
    assert company.answer_evidence_ids == ["e1"]
    assert viewing == before[1]
    assert (deposit.status, deposit.outcome) == (ActionStatus.IMPOSSIBLE, "neutral")
    assert all(n is not a for n, a in zip(new, actions, strict=True))


def test_apply_with_no_updates_returns_equal_copies() -> None:
    actions = [action(COMPANY, "q1")]
    new, dropped = apply(actions, ParseResult(unmatched=True), "ok")
    assert new == actions and new[0] is not actions[0]
    assert dropped == []
