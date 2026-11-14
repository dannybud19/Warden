"""Tests for the LLM pass: prompt, user message rendering, parsing and error handling."""

import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest

from app.aggregators.crosschecker import llm_pass
from app.aggregators.crosschecker.llm_pass import LLMPassError, render_user, system_prompt
from app.aggregators.crosschecker.models import ReviewOutput
from app.aggregators.crosschecker.sources import Source
from app.core.agent import AgentContext
from app.core.llm import FakeLLM

KEY = "You are the Cross-checker"

SOURCES = [
    Source(
        "S1",
        "contract_checker",
        "ev_contract",
        "finding",
        "Utilities charged separately. The contract adds a fee.\n"
        "\n"
        'quote: "Utilities: £60 per month"\n'
        "Source: https://example.com/page   ",
    ),
    Source("S2", "upload", "ev_chat1", "message", "[agent] All bills are included in the rent"),
]


def side(source_id: str, quote: str) -> dict[str, str]:
    return {"source_id": source_id, "claim": "a claim", "quote": quote}


def inconsistency(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "topic": "utilities",
        "check_id": "contract_consistency",
        "severity": "medium",
        "a": side("S1", "Utilities: £60 per month"),
        "b": side("S2", "All bills are included in the rent"),
        "why_it_matters": "You may pay more than you expect.",
    }
    return base | overrides


def with_llm(ctx: AgentContext, llm: Any) -> AgentContext:
    return replace(ctx, llm=llm)


def fake(reply: str) -> FakeLLM:
    return FakeLLM({KEY: reply})


class RaisingLLM:
    """An LLM whose `complete_json` raises the given exception."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def complete_json(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        raise self.exc


async def test_valid_reply_parses(ctx: AgentContext) -> None:
    llm = fake(json.dumps({"inconsistencies": [inconsistency()], "recap": "Things differ."}))
    out = await llm_pass.run(SOURCES, with_llm(ctx, llm))
    assert isinstance(out, ReviewOutput)
    assert out.recap == "Things differ."
    [item] = out.inconsistencies
    assert item.topic == "utilities"
    assert item.check_id == "contract_consistency"
    assert item.severity == "medium"
    assert (item.a.source_id, item.b.source_id) == ("S1", "S2")
    assert item.a.quote == "Utilities: £60 per month"
    [call] = llm.calls
    assert call["method"] == "complete_json"
    assert call["system"] == system_prompt()
    assert call["user"] == render_user(SOURCES)


async def test_empty_reply_parses_to_empty(ctx: AgentContext) -> None:
    out = await llm_pass.run(SOURCES, with_llm(ctx, fake('{"inconsistencies": [], "recap": ""}')))
    assert out.inconsistencies == []
    assert out.recap == ""


async def test_invalid_json_raises(ctx: AgentContext) -> None:
    with pytest.raises(LLMPassError) as info:
        await llm_pass.run(SOURCES, with_llm(ctx, fake("not json")))
    assert info.value.reason == "the model's reply could not be read"


async def test_too_many_inconsistencies_raises(ctx: AgentContext) -> None:
    reply = json.dumps({"inconsistencies": [inconsistency() for _ in range(7)], "recap": ""})
    with pytest.raises(LLMPassError) as info:
        await llm_pass.run(SOURCES, with_llm(ctx, fake(reply)))
    assert "could not be read" in info.value.reason


async def test_bad_check_id_raises(ctx: AgentContext) -> None:
    reply = json.dumps({"inconsistencies": [inconsistency(check_id="vibes")], "recap": ""})
    with pytest.raises(LLMPassError):
        await llm_pass.run(SOURCES, with_llm(ctx, fake(reply)))


async def test_client_error_is_wrapped_without_leaking_message(ctx: AgentContext) -> None:
    llm = RaisingLLM(RuntimeError("sk-ant-secret-123"))
    with pytest.raises(LLMPassError) as info:
        await llm_pass.run(SOURCES, with_llm(ctx, llm))
    assert info.value.reason == "the model call failed"
    assert "secret" not in info.value.reason
    assert "secret" not in str(info.value)
    assert isinstance(info.value.__cause__, RuntimeError)


async def test_error_log_has_only_the_type_name(
    ctx: AgentContext, caplog: pytest.LogCaptureFixture
) -> None:
    llm = RaisingLLM(RuntimeError("sk-ant-secret-123"))
    with caplog.at_level("WARNING", logger="rss"), pytest.raises(LLMPassError):
        await llm_pass.run(SOURCES, with_llm(ctx, llm))
    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text


async def test_cancellation_propagates(ctx: AgentContext) -> None:
    with pytest.raises(asyncio.CancelledError):
        await llm_pass.run(SOURCES, with_llm(ctx, RaisingLLM(asyncio.CancelledError())))


def test_render_user_shape() -> None:
    text = render_user(SOURCES)
    assert text.startswith("SOURCES\n")
    assert text.endswith("\n\nReturn the JSON object only.")
    for source in SOURCES:
        assert f"{source.id} [{source.agent} | {source.evidence_id}] {source.kind}: " in text


def test_render_user_exact_output() -> None:
    assert render_user(SOURCES) == (
        "SOURCES\n"
        "S1 [contract_checker | ev_contract] finding: Utilities charged separately. "
        "The contract adds a fee.\n"
        "\n"
        '   quote: "Utilities: £60 per month"\n'
        "   Source: https://example.com/page\n"
        "S2 [upload | ev_chat1] message: [agent] All bills are included in the rent\n"
        "\n"
        "Return the JSON object only."
    )


def test_render_user_indents_continuations_and_keeps_quotes() -> None:
    lines = render_user(SOURCES).split("\n")
    assert '   quote: "Utilities: £60 per month"' in lines
    assert all(line.strip() != "" or line == "" for line in lines)  # no whitespace-only lines


def test_render_user_without_sources() -> None:
    assert render_user([]) == "SOURCES\n\nReturn the JSON object only."


def test_system_prompt_matches_file_and_rules() -> None:
    prompt = system_prompt()
    assert prompt == llm_pass.PROMPT_PATH.read_text(encoding="utf-8")
    assert prompt.startswith(KEY)
    assert prompt.endswith("\n")
    assert "Quote each side EXACTLY" in prompt
    assert 'never say anything is "safe"' in prompt
    assert "At most 6 disagreements" in prompt
