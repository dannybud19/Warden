"""Snippet filter: LLM verdicts are re-checked in code; keyword fallback when the LLM fails."""

import json
from typing import Any

import pytest

from app.agents.companies_house.constants import (
    LLM_QUOTE_CHARS,
    MAX_SNIPPETS_TO_FILTER,
    SNIPPETS_PER_LLM_CALL,
    STRONG_SCAM_WORDS,
)
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


async def test_at_most_twenty_snippets_are_sent_in_total(make_ctx) -> None:
    llm = llm_with()
    await run_filter(make_ctx, llm, [SCAM_TEXT] * (MAX_SNIPPETS_TO_FILTER + 5))
    sent = sum(c["user"].count("\n[") + 1 for c in llm.calls)
    assert sent == MAX_SNIPPETS_TO_FILTER


async def test_no_call_carries_more_than_twelve_snippets(make_ctx) -> None:
    llm = llm_with()
    await run_filter(make_ctx, llm, [SCAM_TEXT] * 12)
    assert len(llm.calls) == 1 and llm.calls[0]["user"].count("\n[") + 1 == 12


async def test_thirteen_snippets_make_two_calls_and_the_rest_go_in_the_second(make_ctx) -> None:
    texts = [SCAM_TEXT] * 12 + ["Prime City Lettings Ltd: sadly the deposit was never returned."]
    llm = llm_with(verdict(0, "scam_report", "deposit was never returned"))
    kept = await run_filter(make_ctx, llm, texts)
    assert len(llm.calls) == 2
    assert llm.calls[0]["user"].count("\n[") + 1 == SNIPPETS_PER_LLM_CALL
    assert llm.calls[1]["user"].count("\n[") + 1 == 1
    assert "[0] Title 12 |" in llm.calls[1]["user"]  # indexes restart for each call
    # The FakeLLM answers both calls the same way: index 0 of the first and of the second batch.
    assert sorted(k.snippet.index for k in kept) == [0, 12]
    assert all(k.via_llm for k in kept)


async def test_a_failed_second_call_only_falls_back_for_its_own_batch(make_ctx) -> None:
    class SecondFails(FakeLLM):
        async def complete_json(self, system, user, schema, *, model=None):  # type: ignore[override]
            self.calls.append({"system": system, "user": user, "model": model})
            if len(self.calls) == 2:
                raise RuntimeError("EOF while parsing a list")
            return SnippetBatch.model_validate(
                {"items": [verdict(0, "scam_report", "The deposit was never returned")]}
            )

    texts = [SCAM_TEXT] * 12 + ["Prime City Lettings Ltd is a scam, they took my money."]
    kept = await run_filter(make_ctx, SecondFails(), texts)
    by_index = {k.snippet.index: k for k in kept}
    assert by_index[0].via_llm is True and by_index[0].label == "scam_report"
    assert by_index[12].via_llm is False and by_index[12].label == "negative_review"


async def test_llm_quote_over_120_chars_is_dropped(make_ctx) -> None:
    long_quote = "The deposit was never returned" + "!" * 100
    text = SCAM_TEXT.replace("The deposit was never returned", long_quote)
    assert len(long_quote) > LLM_QUOTE_CHARS and long_quote in text
    assert await run_filter(make_ctx, llm_with(verdict(0, "scam_report", long_quote)), [text]) == []


MSE_TEXT = (
    "Prime City Lettings Ltd said my deposit money had not been returned after 3 months. "
    "I have been chasing them by email since January."
)
LAW_BLOG = (
    "Rental scams are rising across London. Prime City Lettings Ltd is one of many agents "
    "operating in the capital."
)
FOXTONS = FilterContext(
    registered_name="FOXTONS LIMITED", company_number="01836619", supplied_name="Foxtons"
)
FOXTONS_SCAM = "Foxtons is a scam, they took my deposit and vanished."


async def test_llm_error_falls_back_to_keywords_and_labels_hits_negative_review(make_ctx) -> None:
    text = "Avoid Prime City Lettings Ltd, it is a scam and they ignore emails."
    kept = await run_filter(make_ctx, RaisingLLM(), [text, NEUTRAL_TEXT, "Unrelated fraud story."])
    assert [k.snippet.index for k in kept] == [
        0
    ]  # only the snippet naming the company + a scam word
    assert kept[0].via_llm is False
    assert kept[0].label == "negative_review"  # never scam_report: only the LLM may say that
    assert kept[0].quote == "Avoid Prime City Lettings Ltd, it is a scam and they ignore emails."


async def test_fallback_does_not_flag_an_ordinary_deposit_dispute(make_ctx) -> None:
    assert await run_filter(make_ctx, RaisingLLM(), [MSE_TEXT]) == []
    assert await run_filter(make_ctx, RaisingLLM(), [SCAM_TEXT]) == []  # deposit never returned


async def test_fallback_does_not_flag_a_generic_law_blog_sentence(make_ctx) -> None:
    # The company is named in the snippet, but not in the sentence that holds the scam word.
    assert await run_filter(make_ctx, RaisingLLM(), [LAW_BLOG]) == []


async def test_fallback_keeps_foxtons_is_a_scam_they_took_my_deposit_and_vanished(make_ctx) -> None:
    kept = await run_filter(make_ctx, RaisingLLM(), [FOXTONS_SCAM], FOXTONS)
    assert len(kept) == 1 and kept[0].quote == FOXTONS_SCAM
    assert kept[0].label == "negative_review" and kept[0].via_llm is False


@pytest.mark.parametrize("word", STRONG_SCAM_WORDS)
async def test_every_strong_scam_word_qualifies_in_the_fallback(make_ctx, word: str) -> None:
    text = f"Prime City Lettings Ltd: {word} says one reader."
    assert len(await run_filter(make_ctx, RaisingLLM(), [text])) == 1


@pytest.mark.parametrize("weak", ["deposit", "wire", "fake", "bank transfer", "never returned"])
async def test_deposit_wire_and_fake_alone_do_not_qualify(make_ctx, weak: str) -> None:
    text = f"Prime City Lettings Ltd and the {weak} for my flat."
    assert await run_filter(make_ctx, RaisingLLM(), [text]) == []


async def test_fallback_matches_on_company_number_in_the_same_sentence(make_ctx) -> None:
    text = "Company 10452757 was reported for a fake listing."
    kept = await run_filter(make_ctx, RaisingLLM(), [text])
    assert len(kept) == 1 and kept[0].quote == text


async def test_fallback_clips_a_long_sentence_to_200_chars_keeping_the_company_name(
    make_ctx,
) -> None:
    text = "Prime City Lettings Ltd is a scam " + "and it went on and on " * 30
    kept = await run_filter(make_ctx, RaisingLLM(), [text])
    assert len(kept) == 1
    assert len(kept[0].quote) <= 200 and kept[0].quote in text and "Prime City" in kept[0].quote


async def test_fallback_drops_a_clipped_quote_that_lost_the_company_name(make_ctx) -> None:
    text = "Prime City Lettings Ltd " + "went on and on " * 30 + "and then the scam happened"
    assert await run_filter(make_ctx, RaisingLLM(), [text]) == []


async def test_invalid_json_falls_back_to_keywords(make_ctx) -> None:
    llm = FakeLLM(default="this is not json")
    kept = await run_filter(make_ctx, llm, [FOXTONS_SCAM], FOXTONS)
    assert len(kept) == 1 and kept[0].via_llm is False


async def test_json_of_the_wrong_shape_falls_back_to_keywords(make_ctx) -> None:
    llm = FakeLLM(default='{"results": []}')
    kept = await run_filter(make_ctx, llm, [FOXTONS_SCAM], FOXTONS)
    assert len(kept) == 1 and kept[0].via_llm is False


async def test_truncated_json_falls_back_to_keywords(make_ctx) -> None:
    llm = FakeLLM(default='{"items": [{"index": 0, "keep": true, "label": "scam_rep')
    kept = await run_filter(make_ctx, llm, [FOXTONS_SCAM], FOXTONS)
    assert len(kept) == 1 and kept[0].via_llm is False


# --- prompt ----------------------------------------------------------------------------------


def test_company_prompt_fills_placeholders_and_keeps_json_braces() -> None:
    prompt = build_system_prompt(CONTEXT)
    assert "PRIME CITY LETTINGS LTD (Companies House number 10452757)" in prompt
    assert "1 Test Street, London, E1 1AA" in prompt
    assert 'told the name "Prime City Lettings"' in prompt
    assert '{"items": [{"index": 0, "keep": true' in prompt
    assert "{registered_name}" not in prompt and "{supplied_name}" not in prompt


def test_prompt_asks_for_only_kept_items_and_120_char_quotes() -> None:
    prompt = build_system_prompt(CONTEXT)
    assert "Return ONLY the snippets you keep" in prompt
    assert "Leave out every irrelevant and different_company snippet" in prompt
    assert "at most 120 characters" in prompt and "at most 200" not in prompt


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


async def test_phone_fallback_needs_the_digits_and_a_strong_word_in_the_same_sentence(
    make_ctx,
) -> None:
    texts = [
        PHONE_SCAM,
        "Call 07911 123456 to book a viewing.",  # number, no strong word
        "A scam call from 07700 900123 stole my deposit.",  # strong word, other number
        "Reported from +44 7911 123456: fraud attempt.",  # international form
        "Fraud is common. The number 07911 123456 is on a list.",  # words in different sentences
    ]
    kept = await run_filter(make_ctx, RaisingLLM(), texts, PHONE_CONTEXT)
    assert [k.snippet.index for k in kept] == [0, 3]
    assert all(k.via_llm is False and k.quote in texts[k.snippet.index] for k in kept)
