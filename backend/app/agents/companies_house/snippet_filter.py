"""Batched LLM snippet filter with keyword fallback (plan 6.2, App. G).

The LLM only classifies snippets; it never scores and never gives a verdict. Every kept quote is
re-checked in code against the full snippet text (golden rule 6).
"""

import re
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agents.companies_house.constants import (
    FALLBACK_KEYWORDS,
    MAX_QUOTE_CHARS,
    MAX_SNIPPETS_TO_FILTER,
    SNIPPET_PROMPT_CHARS,
)
from app.agents.companies_house.evidence import clip_around
from app.agents.companies_house.models import FilterContext, KeptSnippet, Snippet
from app.agents.companies_house.normalise import normalise_name
from app.core.agent import AgentContext

PROMPT_PATH = Path(__file__).parent / "prompts" / "snippet_filter.md"
KEPT_LABELS = ("scam_report", "negative_review")

_SUBJECT_PARAGRAPH_RE = re.compile(r"THIS company:.*?(?=\n\n)", re.DOTALL)
_ABOUT_RULE_RE = re.compile(r"- about_this_company is true only if.*?(?=\n- quote)", re.DOTALL)
_SENTENCE_BREAKS = ".!?\n"


class SnippetVerdict(BaseModel):
    index: int
    keep: bool
    label: Literal["scam_report", "negative_review", "irrelevant", "different_company"]
    about_this_company: bool
    quote: str


class SnippetBatch(BaseModel):
    items: list[SnippetVerdict]


@cache
def _prompt_template() -> str:
    return PROMPT_PATH.read_text()


def build_system_prompt(context: FilterContext) -> str:
    """The prompt with its placeholders filled. Plain replace, because the JSON has braces."""
    text = _prompt_template()
    if context.subject == "phone":
        phone = context.phone or ""
        text = _SUBJECT_PARAGRAPH_RE.sub(
            lambda _: (
                f"THIS phone number: {phone}. The student was given it by the person they are "
                "dealing with."
            ),
            text,
            count=1,
        )
        text = _ABOUT_RULE_RE.sub(
            lambda _: (
                f"- about_this_company is true only if the snippet links this exact phone number "
                f"({phone}) to a scam or fraud report, and nothing in it points to a different "
                "number."
            ),
            text,
            count=1,
        )
    if context.subject == "phone":
        text = text.replace("THIS company", "THIS phone number")
    values = {
        "{registered_name}": context.registered_name,
        "{company_number}": context.company_number,
        "{registered_office}": context.registered_office or "unknown",
        "{supplied_name}": context.supplied_name or context.registered_name,
    }
    for key, value in values.items():
        text = text.replace(key, value)
    return text


def build_user_message(snippets: list[Snippet]) -> str:
    """Numbered `[i] <title> | <url>` blocks, each snippet cut to the prompt length."""
    blocks = [
        f"[{i}] {s.title} | {s.url}\n{s.content[:SNIPPET_PROMPT_CHARS]}"
        for i, s in enumerate(snippets)
    ]
    return "\n\n".join(blocks)


def _keep_from_verdicts(snippets: list[Snippet], batch: SnippetBatch) -> list[KeptSnippet]:
    kept: list[KeptSnippet] = []
    done: set[int] = set()
    for verdict in batch.items:
        if verdict.index in done or not 0 <= verdict.index < len(snippets):
            continue
        if not verdict.keep or not verdict.about_this_company:
            continue
        if verdict.label not in KEPT_LABELS:
            continue
        snippet = snippets[verdict.index]
        quote = verdict.quote
        if not quote.strip() or len(quote) > MAX_QUOTE_CHARS or quote not in snippet.content:
            continue
        done.add(verdict.index)
        kept.append(KeptSnippet(snippet=snippet, label=verdict.label, quote=quote, via_llm=True))
    return kept


# --- keyword fallback ------------------------------------------------------------------------


def _phone_in(content: str, phone: str) -> bool:
    compact = re.sub(r"[\s().-]", "", content)
    national = re.sub(r"\D", "", phone)
    variants = {national, "+44" + national[1:], "44" + national[1:]} if national else set()
    return any(v and v in compact for v in variants)


def _names_subject(content: str, context: FilterContext) -> bool:
    if context.subject == "phone":
        return bool(context.phone) and _phone_in(content, context.phone or "")
    name = normalise_name(context.registered_name)
    if name and f" {name} " in f" {normalise_name(content)} ":
        return True
    number = context.company_number.strip()
    return bool(number) and number.lower() in content.lower()


def _sentence_with(content: str, keyword: str) -> str | None:
    """The sentence of `content` holding `keyword`, verbatim and clipped to the quote limit."""
    index = content.lower().find(keyword)
    if index == -1:
        return None
    start = max(content.rfind(c, 0, index) for c in _SENTENCE_BREAKS) + 1
    ends = [e for e in (content.find(c, index) for c in _SENTENCE_BREAKS) if e != -1]
    end = min(ends) + 1 if ends else len(content)
    sentence = content[start:end].strip()
    if len(sentence) > MAX_QUOTE_CHARS:
        return clip_around(sentence, keyword)
    return sentence or None


def keyword_fallback(snippets: list[Snippet], context: FilterContext) -> list[KeptSnippet]:
    """Keep a snippet only if it names the subject AND holds a scam keyword (plan 6.2)."""
    kept: list[KeptSnippet] = []
    for snippet in snippets:
        if not _names_subject(snippet.content, context):
            continue
        lowered = snippet.content.lower()
        keyword = next((k for k in FALLBACK_KEYWORDS if k in lowered), None)
        if keyword is None:
            continue
        quote = _sentence_with(snippet.content, keyword)
        if quote and quote in snippet.content:
            kept.append(
                KeptSnippet(snippet=snippet, label="scam_report", quote=quote, via_llm=False)
            )
    return kept


async def filter_snippets(
    ctx: AgentContext, snippets: list[Snippet], context: FilterContext
) -> list[KeptSnippet]:
    """Keep only scam reports and negative reviews that are about this subject."""
    batch_in = snippets[:MAX_SNIPPETS_TO_FILTER]
    if not batch_in:
        return []
    try:
        batch = await ctx.llm.complete_json(
            build_system_prompt(context), build_user_message(batch_in), SnippetBatch
        )
    except Exception as exc:  # noqa: BLE001 - any LLM failure falls back to keywords
        ctx.log.warning("companies_house: snippet filter LLM failed (%r), using keywords", exc)
        return keyword_fallback(batch_in, context)
    return _keep_from_verdicts(batch_in, batch)
