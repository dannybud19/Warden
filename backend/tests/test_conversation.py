"""The reply parser: LLM mapping onto open actions, its keyword fallback, and `apply`."""

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from app.contracts import Action, ActionKind, ActionStatus, Case, CheckId
from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.orchestrator import conversation, fields
from app.orchestrator.conversation import (
    ActionUpdate,
    InvalidActionError,
    ParseResult,
    apply,
    confirmation_outcome,
    keyword_outcome,
    looks_like_question,
    parse,
    parse_prompt,
    read_reply,
    validate_target,
)
from app.orchestrator.fields import FieldUpdate
from app.orchestrator.payment_confirmation import PREFIX as PAYMENT_CONFIRMATION_PREFIX

T = TypeVar("T", bound=BaseModel)

TODAY = date(2026, 11, 14)

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


def full_json(
    updates: list[dict[str, Any]] | None = None,
    fields: list[dict[str, Any]] | None = None,
    question: str | None = None,
) -> str:
    return json.dumps({"updates": updates or [], "fields": fields or [], "question": question})


def fld(field: str, value: str, quote: str, correction: bool = False) -> dict[str, Any]:
    return {"field": field, "value": value, "quote": quote, "correction": correction}


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
        await read_reply(one_open(), "yes", [], "nope", None, with_llm(ctx, llm))
    assert llm.calls == 0


# Free text


async def test_free_text_updates_two_of_three_actions(ctx: AgentContext) -> None:
    text = "They gave me company number 01234567 but won't do a viewing before I pay"
    reply = llm_json(
        upd(COMPANY, "clears", "They gave me company number 01234567"),
        upd(VIEWING, "flags", "won't do a viewing before I pay"),
    )
    ctx, llm = fake(ctx, reply)

    result = await read_reply(three_open(), text, [], None, None, ctx)

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
    await read_reply(one_open(), "Deposit is £950", [], None, None, ctx)
    assert "£950" in llm.calls[0]["user"]


async def test_free_text_prompt_lists_only_open_actions(ctx: AgentContext) -> None:
    case = make_case(action(COMPANY, "q1", ActionStatus.DONE), action(VIEWING, "q2"))
    ctx, llm = fake(ctx, llm_json())
    await read_reply(case, "hello", [], None, None, ctx)
    assert [a["id"] for a in json.loads(llm.calls[0]["user"])["open_actions"]] == [VIEWING]


async def test_registered_reply_clears_where_keywords_would_flag(ctx: AgentContext) -> None:
    # Keywords read "No" as a refusal; this is why the LLM reads replies first.
    text = "No problem, they're registered"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", "they're registered")))

    result = await read_reply(one_open(), text, [], None, None, ctx)

    assert outcomes(result) == {COMPANY: "clears"}
    assert keyword_outcome(text) == "flags"


async def test_registered_reply_takes_keyword_flags_when_llm_raises(ctx: AgentContext) -> None:
    # Documented limitation of the fallback.
    text = "No problem, they're registered"
    result = await read_reply(one_open(), text, [], None, None, with_llm(ctx, RaisingLLM()))
    assert outcomes(result) == {COMPANY: "flags"}
    assert result.used_fallback


async def test_refusal_flags(ctx: AgentContext) -> None:
    text = "they refused to give a company number"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "flags", "refused to give a company number")))
    result = await read_reply(one_open(), text, [], None, None, ctx)
    assert outcomes(result) == {COMPANY: "flags"}


async def test_quote_not_in_text_is_dropped(ctx: AgentContext) -> None:
    text = "They gave me the company number"
    reply = llm_json(
        upd(COMPANY, "clears", "gave me the company number"),
        upd(VIEWING, "clears", "we did the viewing yesterday"),
    )
    ctx, _ = fake(ctx, reply)
    result = await read_reply(three_open(), text, [], None, None, ctx)
    assert outcomes(result) == {COMPANY: "clears"}


@pytest.mark.parametrize("quote", ["", "   ", "a" * (fields.MAX_QUOTE_CHARS + 1)])
async def test_empty_or_long_quote_is_dropped(ctx: AgentContext, quote: str) -> None:
    text = "a" * 300
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", quote)))
    result = await read_reply(three_open(), text, [], None, None, ctx)
    assert result == ParseResult(unmatched=True)


async def test_quote_matches_after_normalising_quotes_and_spaces(ctx: AgentContext) -> None:
    text = "They’re   REGISTERED with\nCompanies House"
    quote = "they're registered with companies house"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", quote)))
    result = await read_reply(one_open(), text, [], None, None, ctx)
    assert result.updates == (ActionUpdate(COMPANY, "done", "clears", quote),)


async def test_curly_quote_from_llm_matches_straight_text(ctx: AgentContext) -> None:
    text = 'He said "pay now" and won\'t show it'
    quote = "He said “pay now” and won’t show it"
    ctx, _ = fake(ctx, llm_json(upd(VIEWING, "flags", quote)))
    result = await read_reply(three_open(), text, [], None, None, ctx)
    assert outcomes(result) == {VIEWING: "flags"}


async def test_update_for_closed_action_is_discarded(ctx: AgentContext) -> None:
    case = make_case(action(COMPANY, "q1", ActionStatus.DONE), action(VIEWING, "q2"))
    text = "got the number and saw the flat"
    reply = llm_json(
        upd(COMPANY, "clears", "got the number"),
        upd(VIEWING, "clears", "saw the flat"),
    )
    ctx, _ = fake(ctx, reply)
    result = await read_reply(case, text, [], None, None, ctx)
    assert outcomes(result) == {VIEWING: "clears"}


async def test_duplicate_updates_keep_the_first(ctx: AgentContext) -> None:
    text = "saw the flat, all fine"
    reply = llm_json(
        upd(VIEWING, "clears", "saw the flat"),
        upd(VIEWING, "neutral", "all fine"),
    )
    ctx, _ = fake(ctx, reply)
    result = await read_reply(three_open(), text, [], None, None, ctx)
    assert result.updates == (ActionUpdate(VIEWING, "done", "clears", "saw the flat"),)


async def test_empty_updates_on_free_text_is_unmatched(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json())
    result = await read_reply(three_open(), "ok", [], None, None, ctx)
    assert result == ParseResult(unmatched=True)


async def test_all_quotes_dropped_on_free_text_is_unmatched(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "clears", "not in the reply")))
    result = await read_reply(three_open(), "ok", [], None, None, ctx)
    assert result == ParseResult(unmatched=True)


async def test_no_open_actions_is_unmatched_without_llm(ctx: AgentContext) -> None:
    llm = RaisingLLM()
    case = make_case(action(COMPANY, "q", ActionStatus.DONE))
    result = await read_reply(case, "hello", [], None, None, with_llm(ctx, llm))
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

    result = await read_reply(three_open(), text, [], VIEWING, "done", ctx)

    assert outcomes(result) == {VIEWING: "clears"}
    assert [a["id"] for a in json.loads(llm.calls[0]["user"])["open_actions"]] == [VIEWING]


async def test_targeted_reply_with_empty_updates_is_done_neutral(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json())
    result = await read_reply(three_open(), "yes", ["e1"], VIEWING, None, ctx)
    assert result == ParseResult(updates=(ActionUpdate(VIEWING, "done", "neutral", "", ("e1",)),))


async def test_targeted_reply_with_all_quotes_dropped_is_done_neutral(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json(upd(VIEWING, "clears", "made up quote")))
    result = await read_reply(three_open(), "yes", [], VIEWING, "done", ctx)
    assert result == ParseResult(updates=(ActionUpdate(VIEWING, "done", "neutral", ""),))


@pytest.mark.parametrize("status", ["skipped", "impossible"])
async def test_skipped_and_impossible_never_call_the_llm(ctx: AgentContext, status: Any) -> None:
    llm = RaisingLLM()
    result = await read_reply(
        three_open(), "can't", ["e2", "e1"], DEPOSIT, status, with_llm(ctx, llm)
    )
    assert result == ParseResult(
        updates=(ActionUpdate(DEPOSIT, status, "neutral", "", ("e2", "e1")),)
    )
    assert llm.calls == 0


# Fallback


async def test_llm_error_falls_back_on_one_open_action(
    ctx: AgentContext, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = await read_reply(
            one_open(), "yes, confirmed", ["e1"], None, None, with_llm(ctx, RaisingLLM())
        )
    assert result == ParseResult(
        updates=(ActionUpdate(COMPANY, "done", "clears", "", ("e1",)),), used_fallback=True
    )
    assert "parse fallback: RuntimeError" in caplog.text


async def test_llm_error_with_two_open_actions_is_unmatched(ctx: AgentContext) -> None:
    result = await read_reply(three_open(), "yes", [], None, None, with_llm(ctx, RaisingLLM()))
    assert result == ParseResult(used_fallback=True, unmatched=True)


async def test_llm_error_on_targeted_reply_uses_keywords(ctx: AgentContext) -> None:
    result = await read_reply(
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
    result = await read_reply(one_open(), "yes", [], None, None, ctx)
    assert result.used_fallback
    assert outcomes(result) == {COMPANY: "clears"}


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        # A bare `{}` (FakeLLM's default when no API key is set) is malformed: keywords decide.
        ("{}", ParseResult(updates=(ActionUpdate(COMPANY, "done", "clears"),), used_fallback=True)),
        # A real "matched nothing" is an answer, not a failure: no fallback, nothing changes.
        ('{"updates": []}', ParseResult(unmatched=True)),
    ],
)
async def test_bare_braces_fall_back_but_empty_updates_mean_matched_nothing(
    ctx: AgentContext, reply: str, expected: ParseResult
) -> None:
    """Same case, same reply: only the LLM output differs. One open action is the deciding
    setup, because there the keyword fallback would assign the reply to it."""
    ctx, _ = fake(ctx, reply)
    assert await read_reply(one_open(), "yes", [], None, None, ctx) == expected


async def test_ctx_fake_llm_default_takes_the_fallback(ctx: AgentContext) -> None:
    result = await read_reply(one_open(), "yes", [], None, None, ctx)
    assert result.used_fallback


async def test_all_unknown_ids_fall_back(
    ctx: AgentContext, caplog: pytest.LogCaptureFixture
) -> None:
    ctx, _ = fake(ctx, llm_json(upd("invented", "clears", "yes")))
    with caplog.at_level(logging.WARNING):
        result = await read_reply(one_open(), "yes", [], None, None, ctx)
    assert result.used_fallback
    assert outcomes(result) == {COMPANY: "clears"}
    assert "parse fallback: unknown action ids" in caplog.text


async def test_some_unknown_ids_are_discarded_without_fallback(ctx: AgentContext) -> None:
    reply = llm_json(upd("invented", "clears", "yes"), upd(COMPANY, "clears", "yes"))
    ctx, _ = fake(ctx, reply)
    result = await read_reply(three_open(), "yes", [], None, None, ctx)
    assert not result.used_fallback
    assert outcomes(result) == {COMPANY: "clears"}


async def test_a_free_text_hedge_does_not_close_a_step(ctx: AgentContext) -> None:
    text = "I'll ask them for the number tomorrow"
    ctx, _ = fake(ctx, llm_json(upd(COMPANY, "neutral", "I'll ask them for the number")))
    result = await read_reply(three_open(), text, [], None, None, ctx)
    assert result.updates == () and result.unmatched
    # The same reading on the step's own card does answer it.
    targeted = await read_reply(three_open(), text, [], COMPANY, None, ctx)
    assert outcomes(targeted) == {COMPANY: "neutral"}


async def test_llm_timeout_falls_back(ctx: AgentContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation, "PARSE_TIMEOUT_S", 0.01)
    result = await read_reply(one_open(), "yes", [], None, None, with_llm(ctx, SlowLLM()))
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
    result = await read_reply(three_open(), text, ["e1", "e2"], None, None, ctx)
    assert {u.action_id: u.evidence_ids for u in result.updates} == {COMPANY: ("e1",), VIEWING: ()}


async def test_no_listed_evidence_ids_go_to_every_done_update(ctx: AgentContext) -> None:
    text = "here is the number and the viewing booking"
    reply = llm_json(
        upd(COMPANY, "clears", "here is the number"),
        upd(VIEWING, "clears", "the viewing booking", ["invented"]),
    )
    ctx, _ = fake(ctx, reply)
    result = await read_reply(three_open(), text, ["e1", "e2"], None, None, ctx)
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


# Fields and question (plan 4.7, 4.8)


async def test_fields_and_question_come_back_with_action_updates(ctx: AgentContext) -> None:
    text = "Company number is 01234567. Actually rent is £950 pcm. Is a holding deposit normal?"
    reply = full_json(
        [upd(COMPANY, "clears", "Company number is 01234567")],
        [
            fld("landlord.company_number", "01234567", "Company number is 01234567"),
            fld("listing.rent_pcm", "£950 pcm", "Actually rent is £950 pcm", correction=True),
        ],
        "  Is a holding deposit normal?  ",
    )
    ctx, _ = fake(ctx, reply)

    result = await read_reply(three_open(), text, [], None, None, ctx, today=TODAY)

    assert outcomes(result) == {COMPANY: "clears"}
    assert result.field_updates == (
        FieldUpdate("landlord.company_number", "01234567"),
        FieldUpdate("listing.rent_pcm", 950, correction=True),
    )
    assert result.invalid_fields == ()
    assert result.question == "Is a holding deposit normal?"
    assert not result.unmatched and not result.used_fallback


async def test_free_text_that_only_gives_a_rent_is_not_unmatched(ctx: AgentContext) -> None:
    text = "the rent is 950 a month"
    ctx, _ = fake(ctx, full_json(fields=[fld("listing.rent_pcm", "950", "the rent is 950")]))
    result = await read_reply(three_open(), text, [], None, None, ctx, today=TODAY)
    assert result == ParseResult(field_updates=(FieldUpdate("listing.rent_pcm", 950),))


async def test_a_question_alone_is_not_unmatched(ctx: AgentContext) -> None:
    text = "is a holding deposit normal?"
    ctx, _ = fake(ctx, full_json(question=text))
    result = await read_reply(three_open(), text, [], None, None, ctx, today=TODAY)
    assert result == ParseResult(question=text)


async def test_an_unusable_field_alone_is_not_unmatched(ctx: AgentContext) -> None:
    text = "rent is about 900 or so"
    ctx, _ = fake(ctx, full_json(fields=[fld("listing.rent_pcm", "about 900", "about 900")]))
    result = await read_reply(three_open(), text, [], None, None, ctx, today=TODAY)
    assert result == ParseResult(invalid_fields=("rent",))


async def test_made_up_field_quote_leaves_the_reply_unmatched(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, full_json(fields=[fld("listing.rent_pcm", "950", "rent is 950")]))
    result = await read_reply(three_open(), "ok thanks", [], None, None, ctx, today=TODAY)
    assert result == ParseResult(unmatched=True)


@pytest.mark.parametrize(("raw", "expected"), [("   ", None), ("", None), ("q" * 250, "q" * 200)])
async def test_question_is_blank_or_truncated(
    ctx: AgentContext, raw: str, expected: str | None
) -> None:
    ctx, _ = fake(ctx, full_json(question=raw))
    result = await read_reply(three_open(), "hm", [], None, None, ctx, today=TODAY)
    assert result.question == expected
    assert result.unmatched is (expected is None)


async def test_targeted_reply_also_reads_fields(ctx: AgentContext) -> None:
    text = "deposit is £1,200"
    reply = full_json(fields=[fld("listing.deposit", "£1,200", "deposit is £1,200")])
    ctx, _ = fake(ctx, reply)
    result = await read_reply(three_open(), text, [], DEPOSIT, "done", ctx, today=TODAY)
    assert result == ParseResult(
        updates=(ActionUpdate(DEPOSIT, "done", "neutral", ""),),
        field_updates=(FieldUpdate("listing.deposit", 1200),),
    )


async def test_today_bounds_the_move_in_date(ctx: AgentContext) -> None:
    text = "I move in on 1 March 2027"
    ctx, _ = fake(ctx, full_json(fields=[fld("student.move_in_date", "1 March 2027", text)]))
    inside = await read_reply(three_open(), text, [], None, None, ctx, today=TODAY)
    outside = await read_reply(three_open(), text, [], None, None, ctx, today=date(2028, 6, 1))
    assert inside.field_updates == (FieldUpdate("student.move_in_date", date(2027, 3, 1)),)
    assert outside.field_updates == () and outside.invalid_fields == ("move-in date",)


async def test_fallback_path_reads_no_fields_or_question(ctx: AgentContext) -> None:
    text = "yes, the rent is 950. Is that normal?"
    reply = full_json(
        [upd("invented", "clears", "yes")],
        [fld("listing.rent_pcm", "950", "the rent is 950")],
        "Is that normal?",
    )
    ctx, _ = fake(ctx, reply)
    result = await read_reply(one_open(), text, [], None, None, ctx, today=TODAY)
    assert result.used_fallback
    assert result.field_updates == () and result.invalid_fields == () and result.question is None


async def test_llm_error_reads_no_fields(ctx: AgentContext) -> None:
    result = await read_reply(
        three_open(), "rent is 950", [], None, None, with_llm(ctx, RaisingLLM()), today=TODAY
    )
    assert result == ParseResult(used_fallback=True, unmatched=True)


async def test_skipped_reply_still_never_calls_the_llm(ctx: AgentContext) -> None:
    llm = RaisingLLM()
    result = await read_reply(
        three_open(), "rent is 950", [], DEPOSIT, "skipped", with_llm(ctx, llm), today=TODAY
    )
    assert result == ParseResult(updates=(ActionUpdate(DEPOSIT, "skipped", "neutral", ""),))
    assert llm.calls == 0


# Payment confirmation (Bill's rule, on both paths)

CONFIRM = f"{PAYMENT_CONFIRMATION_PREFIX}abc_1"


def with_confirmation() -> Case:
    """Three ordinary open actions, then an open payment confirmation (asked last)."""
    case = three_open()
    case.actions.append(action(CONFIRM, "Are they asking you to pay before a viewing? Reply yes."))
    return case


@pytest.mark.parametrize(
    ("text", "expected"),
    [("yes", "flags"), ("Yes!", "flags"), ("no", "neutral"), ("unsure", "neutral")],
)
def test_confirmation_outcome_is_a_plain_yes_rule(text: str, expected: str) -> None:
    assert confirmation_outcome(text) == expected


async def test_free_text_answers_an_open_confirmation_first(ctx: AgentContext) -> None:
    ctx, llm = fake(ctx, llm_json(upd(CONFIRM, "neutral", "yes")))
    result = await read_reply(with_confirmation(), "yes", [], None, None, ctx)
    assert outcomes(result) == {CONFIRM: "flags"}
    # The LLM saw only the confirmation, not the three older actions.
    assert [a["id"] for a in json.loads(llm.calls[0]["user"])["open_actions"]] == [CONFIRM]


async def test_the_llm_cannot_clear_a_confirmation(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json(upd(CONFIRM, "clears", "no, they did not")))
    result = await read_reply(with_confirmation(), "no, they did not", [], CONFIRM, None, ctx)
    assert outcomes(result) == {CONFIRM: "neutral"}


async def test_a_yes_the_llm_did_not_map_still_confirms(ctx: AgentContext) -> None:
    ctx, _ = fake(ctx, llm_json())
    result = await read_reply(with_confirmation(), "yes", [], CONFIRM, None, ctx)
    assert outcomes(result) == {CONFIRM: "flags"}


@pytest.mark.parametrize(("text", "expected"), [("yes", "flags"), ("they refused", "neutral")])
async def test_the_keyword_fallback_uses_the_confirmation_rule(
    ctx: AgentContext, text: str, expected: str
) -> None:
    result = await read_reply(
        with_confirmation(), text, [], None, None, with_llm(ctx, RaisingLLM())
    )
    assert result.used_fallback
    assert outcomes(result) == {CONFIRM: expected}


def test_sync_parse_is_the_keyword_reading() -> None:
    """`parse` returns the actions `read_reply` would produce with no LLM."""
    actions = parse(with_confirmation(), "yes", [])
    by_id = {a.id: a for a in actions}
    assert by_id[CONFIRM].outcome == "flags" and by_id[CONFIRM].status == ActionStatus.DONE
    assert all(by_id[i].status == ActionStatus.OPEN for i in (COMPANY, VIEWING, DEPOSIT))
    # Free text with several ordinary open actions is not guessed (decision 11).
    assert [a.model_dump() for a in parse(three_open(), "yes", [])] == [
        a.model_dump() for a in three_open().actions
    ]


# Questions to us are never recorded as answers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("so what are the issues with this property", True),
        ("Is it normal to pay a deposit before a viewing?", True),
        ("why", True),
        ("they refused?", True),
        ("yes", False),
        ("no, they did not", False),
        ("I saw it on Saturday", False),
        ("Island Gardens is the station", False),
        ("yes, the rent is 950. Is that normal?", False),
    ],
)
def test_looks_like_question(text: str, expected: bool) -> None:
    assert looks_like_question(text) is expected


async def test_a_question_does_not_answer_an_open_confirmation(ctx: AgentContext) -> None:
    question = "so what are the issues with this property"
    ctx, llm = fake(ctx, json.dumps({"updates": [], "question": question}))
    result = await read_reply(with_confirmation(), question, [], None, None, ctx)
    assert outcomes(result) == {} and result.question == question
    # The reader saw every open action, not only the confirmation.
    seen = [a["id"] for a in json.loads(llm.calls[0]["user"])["open_actions"]]
    assert seen == [COMPANY, VIEWING, DEPOSIT, CONFIRM]


async def test_the_keyword_fallback_keeps_a_question_and_answers_nothing(
    ctx: AgentContext,
) -> None:
    text = "Is it normal to pay before a viewing?"
    result = await read_reply(
        with_confirmation(), text, [], None, None, with_llm(ctx, RaisingLLM())
    )
    assert result.used_fallback and outcomes(result) == {} and result.question == text
    assert [a.model_dump() for a in parse(with_confirmation(), text, [])] == [
        a.model_dump() for a in with_confirmation().actions
    ]
