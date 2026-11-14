"""Snippet filter: LLM verdicts are re-checked in code; keyword fallback when the LLM fails."""

import json
from typing import Any

import pytest

from app.agents.companies_house.constants import FALLBACK_KEYWORDS, MAX_SNIPPETS_TO_FILTER
from app.agents.companies_house.models import FilterContext, Snippet
from app.agents.companies_house.snippet_filter import (
    SnippetBatch,
    build_system_prompt,
    build_user_message,
    filter_snippets,
)
from app.core.agent import AgentContext
from app.core.llm import FakeLLM

CONTEXT = FilterContext(
    registered_name="PRIME CITY LETTINGS LTD",
    company_number="10452757",
    registered_office="1 Test Street, London, E1 1AA",
    supplied_name="Prime City Lettings",
)
SCAM_TEXT = (
    "I paid a holding deposit to Prime City Lettings Ltd and never got a viewing. "
    "The deposit was never returned. Avoid."
)
OTHER_TEXT = "Prime City Lettings Ltd in Birmingham advertised a fake listing last year."
NEUTRAL_TEXT = "Prime City Lettings Ltd offers flats across London. Contact us for viewings."


def snippets(*texts: str) -> list[Snippet]:
    return [
        Snippet(i, f"Title {i}", f"https://example.org/{i}", text, "scam")
        for i, text in enumerate(texts)
    ]


def verdict(index: int, label: str, quote: str, *, keep: bool = True, about: bool = True) -> dict:
    return {
        "index": index,
        "keep": keep,
        "label": label,
        "about_this_company": about,
        "quote": quote,
    }


def llm_with(*items: dict[str, Any]) -> FakeLLM:
    return FakeLLM(default=json.dumps({"items": list(items)}))


class RaisingLLM(FakeLLM):
    async def complete_json(self, system, user, schema, *, model=None):  # type: ignore[override]
        self.calls.append({"method": "complete_json", "system": system, "user": user})
        raise RuntimeError("model unavailable")


async def run_filter(make_ctx, llm: FakeLLM, texts: list[str], context=CONTEXT):
    ctx: AgentContext = await make_ctx(llm=llm)
    return await filter_snippets(ctx, snippets(*texts), context)


async def test_llm_verdict_is_parsed_and_kept(make_ctx) -> None:
    llm = llm_with(verdict(0, "scam_report", "The deposit was never returned"))
    kept = await run_filter(make_ctx, llm, [SCAM_TEXT], CONTEXT)
    assert len(kept) == 1
    assert kept[0].label == "scam_report"
    assert kept[0].quote == "The deposit was never returned"
    assert kept[0].via_llm is True
    assert kept[0].snippet.url == "https://example.org/0"
    assert len(llm.calls) == 1 and llm.calls[0]["model"] is None


async def test_negative_review_label_is_kept(make_ctx) -> None:
    llm = llm_with(verdict(0, "negative_review", "never got a viewing"))
    kept = await run_filter(make_ctx, llm, [SCAM_TEXT])
    assert [k.label for k in kept] == ["negative_review"]


async def test_one_batched_call_for_many_snippets(make_ctx) -> None:
    llm = llm_with(verdict(1, "scam_report", "never got a viewing"))
    kept = await run_filter(make_ctx, llm, [NEUTRAL_TEXT, SCAM_TEXT, OTHER_TEXT])
    assert len(llm.calls) == 1
    assert [k.snippet.index for k in kept] == [1]
    user = llm.calls[0]["user"]
    assert "[0] Title 0 | https://example.org/0" in user and "[2] Title 2" in user


async def test_quote_not_in_snippet_is_dropped(make_ctx) -> None:
    llm = llm_with(verdict(0, "scam_report", "they stole my deposit and vanished"))
    assert await run_filter(make_ctx, llm, [SCAM_TEXT]) == []


async def test_quote_is_checked_against_the_full_snippet_not_the_truncated_one(make_ctx) -> None:
    tail = "Prime City Lettings Ltd kept the whole deposit and never answered again."
    text = "Intro. " * 150 + tail  # the tail is far beyond the 600 chars the model sees
    llm = llm_with(verdict(0, "scam_report", "kept the whole deposit and never answered"))
    kept = await run_filter(make_ctx, llm, [text])
    assert len(kept) == 1
    assert "kept the whole deposit" not in llm.calls[0]["user"]


async def test_overlong_quote_is_dropped(make_ctx) -> None:
    text = "Prime City Lettings Ltd deposit problem. " * 10
    llm = llm_with(verdict(0, "scam_report", text.strip()))
    assert len(text.strip()) > 200
    assert await run_filter(make_ctx, llm, [text]) == []


async def test_about_this_company_false_is_dropped(make_ctx) -> None:
    llm = llm_with(verdict(0, "scam_report", "never got a viewing", about=False))
    assert await run_filter(make_ctx, llm, [SCAM_TEXT]) == []


async def test_keep_false_is_dropped(make_ctx) -> None:
    llm = llm_with(verdict(0, "scam_report", "never got a viewing", keep=False))
    assert await run_filter(make_ctx, llm, [SCAM_TEXT]) == []


@pytest.mark.parametrize("label", ["different_company", "irrelevant"])
async def test_other_labels_are_dropped_even_if_keep_is_true(make_ctx, label: str) -> None:
    llm = llm_with(verdict(0, label, "never got a viewing"))
    assert await run_filter(make_ctx, llm, [SCAM_TEXT]) == []


async def test_unknown_index_is_ignored(make_ctx) -> None:
    llm = llm_with(
        verdict(7, "scam_report", "never got a viewing"),
        verdict(-1, "scam_report", "never got a viewing"),
        verdict(0, "scam_report", "never got a viewing"),
    )
    kept = await run_filter(make_ctx, llm, [SCAM_TEXT])
    assert [k.snippet.index for k in kept] == [0]


async def test_empty_input_makes_no_llm_call(make_ctx) -> None:
    llm = llm_with()
    assert await run_filter(make_ctx, llm, []) == []
    assert llm.calls == []


async def test_at_most_max_snippets_are_sent(make_ctx) -> None:
    llm = llm_with()
    await run_filter(make_ctx, llm, [SCAM_TEXT] * (MAX_SNIPPETS_TO_FILTER + 5))
    assert llm.calls[0]["user"].count("\n[") + 1 == MAX_SNIPPETS_TO_FILTER


async def test_llm_error_falls_back_to_keywords(make_ctx) -> None:
    kept = await run_filter(
        make_ctx, RaisingLLM(), [SCAM_TEXT, NEUTRAL_TEXT, "Unrelated fraud story."]
    )
    # Only the snippet naming the company AND a keyword survives.
    assert [k.snippet.index for k in kept] == [0]
    assert kept[0].via_llm is False
    assert kept[0].label == "scam_report"
    assert kept[0].quote in SCAM_TEXT
    assert "deposit" in kept[0].quote.lower()
    assert len(kept[0].quote) <= 200


async def test_fallback_quote_is_the_sentence_with_the_keyword(make_ctx) -> None:
    text = "Great location. Prime City Lettings Ltd took my money by bank transfer. Nice flat."
    kept = await run_filter(make_ctx, RaisingLLM(), [text])
    assert kept[0].quote == "Prime City Lettings Ltd took my money by bank transfer."


async def test_fallback_matches_on_company_number(make_ctx) -> None:
    text = "Company 10452757 was reported for a fake listing."
    kept = await run_filter(make_ctx, RaisingLLM(), [text])
    assert len(kept) == 1 and kept[0].quote == text


async def test_fallback_needs_a_keyword(make_ctx) -> None:
    assert await run_filter(make_ctx, RaisingLLM(), [NEUTRAL_TEXT]) == []
    assert "scam" in FALLBACK_KEYWORDS


async def test_fallback_clips_a_long_sentence_to_200_chars(make_ctx) -> None:
    text = "Prime City Lettings Ltd " + "went on and on " * 30 + "and then the scam happened"
    kept = await run_filter(make_ctx, RaisingLLM(), [text])
    assert len(kept) == 1
    assert len(kept[0].quote) <= 200 and kept[0].quote in text


async def test_invalid_json_falls_back_to_keywords(make_ctx) -> None:
    llm = FakeLLM(default="this is not json")
    kept = await run_filter(make_ctx, llm, [SCAM_TEXT])
    assert len(kept) == 1 and kept[0].via_llm is False


async def test_json_of_the_wrong_shape_falls_back_to_keywords(make_ctx) -> None:
    llm = FakeLLM(default='{"results": []}')
    kept = await run_filter(make_ctx, llm, [SCAM_TEXT])
    assert len(kept) == 1 and kept[0].via_llm is False


# --- prompt ----------------------------------------------------------------------------------


def test_company_prompt_fills_placeholders_and_keeps_json_braces() -> None:
    prompt = build_system_prompt(CONTEXT)
    assert "PRIME CITY LETTINGS LTD (Companies House number 10452757)" in prompt
    assert "1 Test Street, London, E1 1AA" in prompt
    assert 'told the name "Prime City Lettings"' in prompt
    assert '{"items": [{"index": 0, "keep": true' in prompt
    assert "{registered_name}" not in prompt and "{supplied_name}" not in prompt


def test_user_message_truncates_content_to_600_chars() -> None:
    message = build_user_message(snippets("x" * 900))
    assert message == "[0] Title 0 | https://example.org/0\n" + "x" * 600


def test_schema_accepts_the_prompts_example() -> None:
    batch = SnippetBatch.model_validate_json(
        '{"items": [{"index": 0, "keep": true, "label": "scam_report",'
        ' "about_this_company": true, "quote": "q"}]}'
    )
    assert batch.items[0].label == "scam_report"


# --- phone subject ---------------------------------------------------------------------------

PHONE_CONTEXT = FilterContext(subject="phone", phone="07911123456")
PHONE_SCAM = (
    "Victims say 07911 123456 is a scam number used for fake viewings and bank transfer requests."
)


def test_phone_prompt_names_the_number_not_a_company() -> None:
    prompt = build_system_prompt(PHONE_CONTEXT)
    assert "THIS phone number: 07911123456" in prompt
    assert "THIS company" not in prompt
    assert "links this exact phone number (07911123456) to a scam or fraud report" in prompt
    assert "- scam_report:" in prompt and "- different_company:" in prompt
    assert '{"items": [' in prompt


async def test_phone_subject_uses_the_phone_prompt(make_ctx) -> None:
    llm = llm_with(verdict(0, "scam_report", "07911 123456 is a scam number"))
    kept = await run_filter(make_ctx, llm, [PHONE_SCAM], PHONE_CONTEXT)
    assert len(kept) == 1
    assert "THIS phone number: 07911123456" in llm.calls[0]["system"]


async def test_phone_fallback_needs_the_digits_and_a_keyword(make_ctx) -> None:
    texts = [
        PHONE_SCAM,
        "Call 07911 123456 to book a viewing.",  # number, no keyword
        "A scam call from 07700 900123 stole my deposit.",  # keyword, other number
        "Reported from +44 7911 123456: fraud attempt.",  # international form
    ]
    kept = await run_filter(make_ctx, RaisingLLM(), texts, PHONE_CONTEXT)
    assert [k.snippet.index for k in kept] == [0, 3]
    assert all(k.via_llm is False and k.quote in texts[k.snippet.index] for k in kept)
