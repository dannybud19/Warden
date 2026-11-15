"""Round message composer: validator rules, the deterministic template and the LLM fallback."""

import asyncio
import json
import logging
from dataclasses import replace

import pytest

from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.orchestrator import composer
from app.orchestrator.composer import (
    CheckMove,
    RoundInput,
    RoundNote,
    compose_round,
    template,
    validate,
)

BASE = RoundInput(score_before=100, score_after=82, new_actions=2, open_actions=3)
GOOD = (
    "Your risk score dropped from 100 to 82. The landlord identity check is now cleared. "
    "I've added 2 new steps below."
)


class RaisingLLM(FakeLLM):
    """An LLM whose every completion fails."""

    async def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        raise RuntimeError("provider down")


class SlowLLM(FakeLLM):
    """An LLM that answers well, but too late."""

    async def complete(self, system: str, user: str, *, model: str | None = None) -> str:
        await asyncio.sleep(1)
        return GOOD


def with_llm(ctx: AgentContext, llm: FakeLLM) -> AgentContext:
    return replace(ctx, llm=llm)


# validate: one test per rule


def test_validate_accepts_good_message() -> None:
    assert validate(GOOD, BASE) == []


def test_validate_rejects_new_steps_when_none_were_added() -> None:
    """The model counted an open step as new (seen live on Gemini Flash-Lite)."""
    quiet = RoundInput(score_before=100, score_after=100, new_actions=0, open_actions=1)
    assert validate("I can't tell from the case yet. I've added 1 new step below.", quiet) == [
        "false_new_steps"
    ]
    assert validate("I can't tell from the case yet. 1 step is still open below.", quiet) == []
    assert validate("I've added 2 new steps below.", BASE) == []


def test_validate_too_long() -> None:
    assert validate(" ".join(["word"] * 61), BASE) == ["too_long"]
    assert validate(" ".join(["word"] * 60), BASE) == []


@pytest.mark.parametrize("word", ["safe", "Legit", "SCAM", "genuine", "fraudulent", "safely"])
def test_validate_banned_word(word: str) -> None:
    assert validate(f"This flat looks {word} to me.", BASE) == ["banned_word"]


def test_validate_banned_word_needs_whole_word() -> None:
    assert validate("Keep your documents in a safety folder.", BASE) == []


def test_validate_long_digits_ignores_spaces_between_digits() -> None:
    inp = replace(BASE, notes=(RoundNote("field_changed", "account 12 34 56"),))
    assert validate("Your account is 12 34 56.", inp) == ["long_digits"]


def test_validate_unknown_number() -> None:
    assert validate("Your risk score is now 75/100.", BASE) == ["unknown_number"]


def test_validate_allows_difference_denominator_and_note_numbers() -> None:
    inp = replace(
        BASE,
        notes=(RoundNote("field_changed", "rent set to 950"),),
        grounding=("deposit protection: 5 weeks",),
    )
    text = "Your score is 82/100, down 18. Rent is 950 and 5 weeks. 3 steps are open."
    assert validate(text, inp) == []


def test_validate_unknown_number_without_previous_score() -> None:
    inp = replace(BASE, score_before=None)
    assert validate("Your risk score is 82/100, down 18.", inp) == ["unknown_number"]


@pytest.mark.parametrize("text", ["", "   \n"])
def test_validate_empty(text: str) -> None:
    assert validate(text, BASE) == ["empty"]


def test_validate_em_dash() -> None:
    assert validate(f"Your risk score is 82/100 {composer.EM_DASH} lower.", BASE) == ["em_dash"]


@pytest.mark.parametrize("text", ["{}", '  ["a"]', "Here it is:\n```\nhello\n```"])
def test_validate_not_prose(text: str) -> None:
    assert validate(text, BASE) == ["not_prose"]


def test_validate_reports_rules_in_stable_order() -> None:
    text = f"{{ safe 1234567 {composer.EM_DASH} " + " ".join(["word"] * 60)
    assert validate(text, BASE) == [
        "too_long",
        "banned_word",
        "long_digits",
        "unknown_number",
        "em_dash",
        "not_prose",
    ]


# template: exact strings from plan Appendix B


def test_template_score_down_with_move_and_new_steps() -> None:
    inp = RoundInput(
        score_before=100,
        score_after=82,
        moved=(CheckMove("landlord identity", "unverified", "cleared"),),
        new_actions=2,
    )
    assert template(inp) == (
        "Your risk score is now 82/100 (down 18). Landlord identity is now cleared. "
        "I've added 2 new steps below."
    )


def test_template_unchanged_with_unmatched_note() -> None:
    inp = RoundInput(
        score_before=82, score_after=82, open_actions=3, notes=(RoundNote("unmatched"),)
    )
    assert template(inp) == (
        "Your risk score is 82/100. I couldn't match your message to a step. "
        "3 steps are still open below."
    )


def test_template_score_up_with_upload_hint() -> None:
    inp = RoundInput(
        score_before=82,
        score_after=90,
        moved=(CheckMove("payment safety", "unverified", "suspicious"),),
        open_actions=1,
        notes=(RoundNote("upload_hint"),),
    )
    assert template(inp) == (
        "Your risk score is now 90/100 (up 8). Payment safety is now suspicious. "
        "Please upload that message so I can check it. 1 step is still open below."
    )


def test_template_limits_moves_and_notes() -> None:
    inp = RoundInput(
        score_before=None,
        score_after=100,
        moved=(
            CheckMove("landlord identity", "unverified", "suspicious"),
            CheckMove("payment safety", "unverified", "suspicious"),
            CheckMove("fair price", "unverified", "cleared"),
        ),
        not_run=("companies_house",),
        new_actions=1,
        notes=(
            RoundNote("dropped"),
            RoundNote("field_changed", "rent set to 950."),
            RoundNote("question"),
        ),
    )
    assert template(inp) == (
        "Your risk score is 100/100. Landlord identity is now suspicious. "
        "Payment safety is now suspicious. I couldn't run every check this time. "
        "That step was already closed. I updated: rent set to 950. I've added 1 new step below."
    )


def test_template_hides_a_fact_that_would_break_the_rules() -> None:
    inp = RoundInput(
        score_before=90,
        score_after=90,
        notes=(RoundNote("field_changed", "company number set to 01234567"),),
    )
    assert template(inp) == "Your risk score is 90/100. I updated one detail."


TEMPLATE_INPUTS = [
    BASE,
    RoundInput(score_before=None, score_after=100),
    RoundInput(score_before=100, score_after=100, open_actions=1),
    RoundInput(score_before=60, score_after=75, new_actions=3, open_actions=5),
    RoundInput(
        score_before=100,
        score_after=41,
        moved=(
            CheckMove("contract consistency", "unverified", "cleared"),
            CheckMove("in-person viewing", "unverified", "cleared"),
            CheckMove("deposit protection", "unverified", "cleared"),
        ),
        not_run=("contract_checker", "companies_house"),
    ),
    RoundInput(
        score_before=82,
        score_after=82,
        notes=(
            RoundNote("field_changed", "rent set to 950"),
            RoundNote("field_invalid", "deposit of 12000"),
        ),
        open_actions=2,
    ),
    RoundInput(
        score_before=82,
        score_after=82,
        notes=(RoundNote("field_changed", "sort code 12 34 56 and account 1234"),),
    ),
    RoundInput(
        score_before=70,
        score_after=88,
        notes=(RoundNote("field_invalid", "a genuine safe deposit scheme"),),
        new_actions=1,
    ),
    RoundInput(
        score_before=55,
        score_after=55,
        notes=(RoundNote("field_changed", " ".join(["word"] * 30)),),
    ),
    RoundInput(
        score_before=90,
        score_after=80,
        notes=(RoundNote("question", "is it 2 bedrooms?"),),
        grounding=("fair price: cleared",),
        recap_sent=True,
        open_actions=4,
    ),
    RoundInput(
        score_before=100,
        score_after=95,
        moved=(
            CheckMove("right to let", "unverified", "suspicious"),
            CheckMove("no pressure", "unverified", "suspicious"),
        ),
        not_run=("video_analysis",),
        notes=(
            RoundNote("upload_hint"),
            RoundNote("field_changed", "move-in date set to 1 Sep 2027"),
            RoundNote("dropped"),
        ),
        new_actions=3,
        open_actions=6,
    ),
    RoundInput(score_before=0, score_after=0, notes=(RoundNote("field_invalid", "```{}```"),)),
]


@pytest.mark.parametrize("inp", TEMPLATE_INPUTS)
def test_template_always_passes_validate(inp: RoundInput) -> None:
    assert validate(template(inp), inp) == []


# compose_round


async def test_compose_returns_good_llm_output_as_is(ctx: AgentContext) -> None:
    llm = FakeLLM(default=f"  {GOOD}\n")
    assert await compose_round(BASE, with_llm(ctx, llm)) == GOOD


async def test_compose_sends_prompt_and_payload(ctx: AgentContext) -> None:
    llm = FakeLLM(default=GOOD)
    inp = replace(
        BASE,
        moved=(CheckMove("landlord identity", "unverified", "cleared"),),
        notes=(RoundNote("unmatched"),),
    )
    await compose_round(inp, with_llm(ctx, llm))
    call = llm.calls[0]
    assert call["system"] == composer.compose_prompt()
    assert json.loads(call["user"]) == {
        "score_before": 100,
        "score_after": 82,
        "moved": [{"check": "landlord identity", "before": "unverified", "after": "cleared"}],
        "not_run": [],
        "checked": [],
        "new_actions": 2,
        "open_actions": 3,
        "recap_sent": False,
        "notes": [{"kind": "unmatched", "text": ""}],
        "grounding": [],
        "history": [],
        "deciding": False,
    }


async def test_compose_banned_word_uses_template(
    ctx: AgentContext, caplog: pytest.LogCaptureFixture
) -> None:
    llm = FakeLLM(default="Good news: this flat looks safe. I've added 2 new steps below.")
    with caplog.at_level(logging.WARNING):
        assert await compose_round(BASE, with_llm(ctx, llm)) == template(BASE)
    assert "compose fallback: banned_word" in caplog.text


async def test_compose_61_words_uses_template(ctx: AgentContext) -> None:
    llm = FakeLLM(default=" ".join(["word"] * 61))
    assert await compose_round(BASE, with_llm(ctx, llm)) == template(BASE)


async def test_compose_llm_error_uses_template(
    ctx: AgentContext, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert await compose_round(BASE, with_llm(ctx, RaisingLLM())) == template(BASE)
    assert "compose fallback: RuntimeError" in caplog.text


async def test_compose_timeout_uses_template(
    ctx: AgentContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composer, "COMPOSE_TIMEOUT_S", 0.01)
    assert await compose_round(BASE, with_llm(ctx, SlowLLM())) == template(BASE)


async def test_compose_fake_llm_default_json_uses_template(ctx: AgentContext) -> None:
    assert await compose_round(BASE, ctx) == template(BASE)


def test_drop_repeats_removes_only_sentences_we_already_said() -> None:
    history = (
        "student: how is my deposit protected?",
        "you: I cannot tell from the case yet how your deposit is protected.",
        "student: they never gave me the company number",
    )
    text = "Thanks for telling me. I cannot tell from the case yet how your deposit is protected!"
    assert composer.drop_repeats(text, history) == "Thanks for telling me."
    assert composer.drop_repeats("They never gave me the company number.", history) != ""
    assert composer.drop_repeats(text, ()) == text


async def test_a_message_that_only_repeats_falls_back_to_the_template(ctx: AgentContext) -> None:
    said = "Two steps are still open below."
    inp = replace(BASE, history=(f"you: {said}",))
    assert await compose_round(inp, with_llm(ctx, FakeLLM(default=said))) == template(inp)
