"""The one LLM pass: scam signals the rules missed, each tied to an exact quote.

The model only names flags from `catalog.SPECS`; check, category and severity come from there.
It can never set a hard flag, and anything it cannot quote exactly is dropped.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.agents.message_checker.catalog import (
    AGENT,
    LLM_MAX_CONFIDENCE,
    LLM_MIN_CONFIDENCE,
    OTHER_CATEGORY,
    SPECS,
)
from app.agents.message_checker.models import LLMOutput
from app.agents.message_checker.rules import MAX_QUOTE, Hit, finding, parse_money
from app.contracts import (
    Case,
    CheckId,
    EvidenceRef,
    Fact,
    FactKey,
    Finding,
    Message,
    Severity,
)
from app.core.agent import AgentContext

MAX_QUESTIONS = 2
_LLM_FACT_KEYS = {
    FactKey.LANDLORD_NAME,
    FactKey.ADDRESS,
    FactKey.RENT_PCM,
    FactKey.DEPOSIT,
    FactKey.MOVE_IN_DATE,
}


@dataclass
class LLMResult:
    findings: list[Finding] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


@lru_cache
def system_prompt() -> str:
    return (Path(__file__).parent / "prompts" / "extra_findings.md").read_text(encoding="utf-8")


def build_user_prompt(case: Case, fired: set[str]) -> str:
    """The conversation, what the student told us, and the flags the rules already raised."""
    lines = "\n".join(f"[{m.id}] {m.sender}: {m.text}" for m in case.messages)
    known = {
        "listing": case.listing.model_dump(mode="json", exclude_none=True) if case.listing else {},
        "landlord": case.landlord.model_dump(mode="json", exclude_none=True)
        if case.landlord
        else {},
    }
    return (
        f"<conversation>\n{lines}\n</conversation>\n\n"
        f"<case>\n{json.dumps(known, ensure_ascii=False)}\n</case>\n\n"
        f"<already_flagged>\n{', '.join(sorted(fired)) or 'none'}\n</already_flagged>"
    )


def _locate(message_id: str, quote: str, messages: list[Message]) -> Hit | None:
    """The message that really contains `quote`: the named one first, then any other."""
    quote = quote.strip()
    if not quote:
        return None
    named = [m for m in messages if m.id == message_id]
    for m in named + [m for m in messages if m.id != message_id]:
        if quote in m.text:
            return Hit(m, quote[:MAX_QUOTE])
    return None


def _confidence(raw: float) -> float | None:
    return None if raw < LLM_MIN_CONFIDENCE else min(raw, LLM_MAX_CONFIDENCE)


def _other(check_raw: str | None, hit: Hit, explanation: str, confidence: float) -> Finding | None:
    try:
        check = CheckId(check_raw or "")
    except ValueError:
        return None
    if check not in OTHER_CATEGORY or not explanation.strip():
        return None
    return Finding(
        id=f"{AGENT}:other_{check.value}",
        agent=AGENT,
        check_id=check,
        title="Other warning sign in the messages",
        detail=explanation.strip(),
        category=OTHER_CATEGORY[check],
        severity=Severity.MEDIUM,
        confidence=confidence,
        evidence=[EvidenceRef(evidence_id=hit.message.evidence_id, quote=hit.quote)],
    )


def _move_in_date(value: str, message: Message) -> str | None:
    """An ISO date the message supports, or None.

    Messages often say "1 December" with no year, and the model then guesses one. When the year is
    not written in the message, it is taken from when the message was sent (the next such date).
    """
    try:
        stated = date.fromisoformat(value)
    except ValueError:
        return None
    if str(stated.year) in message.text:
        return stated.isoformat()
    if message.sent_at is None:
        return None
    sent = message.sent_at.date()
    try:
        moved = stated.replace(year=sent.year)
        if moved < sent:
            moved = stated.replace(year=sent.year + 1)
    except ValueError:  # 29 February in a year without one
        return None
    return moved.isoformat()


def _fact(key_raw: str, value: str, message: Message) -> Fact | None:
    """A model-reported fact, kept only in a form the crosscheck can compare safely."""
    try:
        key = FactKey(key_raw)
    except ValueError:
        return None
    value = value.strip()
    if key not in _LLM_FACT_KEYS or not value:
        return None
    if key in (FactKey.RENT_PCM, FactKey.DEPOSIT):
        amount = parse_money(value.lstrip("£ "))
        if not amount:
            return None
        value = str(amount)
    # NOTE: a first name or a street without a postcode would look like a mismatch against the
    # listing in the crosscheck, so only full names are passed on, and addresses are left to rules.
    if key == FactKey.LANDLORD_NAME and len(value.split()) < 2:
        return None
    if key == FactKey.ADDRESS:
        return None
    if key == FactKey.MOVE_IN_DATE:
        value = _move_in_date(value, message) or ""
        if not value:
            return None
    return Fact(key=key, value=value, source=message.evidence_id, agent=AGENT)


def convert(output: LLMOutput, case: Case, fired: set[str]) -> LLMResult:
    """Turn the model's reply into Findings and Facts, dropping anything unsupported."""
    messages = case.messages
    result = LLMResult()
    seen = set(fired)

    items = [
        (f.flag, f.message_id, f.quote, f.explanation, f.confidence, f.check_id, False)
        for f in output.flags
    ]
    items += [
        (c.clear, c.message_id, c.quote, c.explanation, c.confidence, None, True)
        for c in output.clears
    ]
    for name, message_id, quote, explanation, raw_conf, check_raw, as_clear in items:
        hit = _locate(message_id, quote, messages)
        confidence = _confidence(raw_conf)
        if hit is None or confidence is None:
            continue
        if name == "other" and not as_clear:
            extra = _other(check_raw, hit, explanation, confidence)
            if extra and extra.id not in {f.id for f in result.findings}:
                result.findings.append(extra)
            continue
        spec = SPECS.get(name)
        if spec is None or spec.clears != as_clear or name in seen:
            continue
        seen.add(name)
        if as_clear:
            confidence = min(confidence, spec.confidence)
        detail = f"{spec.detail} {explanation.strip()}".strip() if not as_clear else None
        result.findings.append(finding(spec, [hit], confidence=confidence, detail=detail))

    by_id = {m.id: m for m in messages}
    for f in output.facts:
        source = by_id.get(f.message_id)
        fact = _fact(f.key, f.value, source) if source else None
        if fact and fact not in result.facts:
            result.facts.append(fact)

    result.questions = [q.strip() for q in output.questions if q.strip()][:MAX_QUESTIONS]
    return result


async def extra_findings(case: Case, fired: set[str], ctx: AgentContext) -> LLMResult:
    """One model call over the whole conversation. Raises on LLM or parsing failure."""
    output = await ctx.llm.complete_json(system_prompt(), build_user_prompt(case, fired), LLMOutput)
    return convert(output, case, fired)
