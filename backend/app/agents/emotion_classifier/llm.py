"""The LLM pass: facts vs feelings for every message, each influence tied to an exact quote."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.agents.emotion_classifier.models import EmotionOutput
from app.agents.emotion_classifier.rules import (
    MAX_QUOTE,
    NOTES_ID,
    NOTES_SOURCE,
    STUDENT_KINDS,
    Hit,
    mask_numbers,
    side_of,
)
from app.contracts import Case
from app.core.agent import AgentContext

# Set to a faster model (e.g. "claude-haiku-5-5") once the team agrees; None uses the default.
MODEL: str | None = None
MAX_FACTS = 10


@dataclass
class LLMResult:
    hits: list[Hit] = field(default_factory=list)
    reassurance: list[Hit] = field(default_factory=list)
    # (masked statement, evidence id, exact quote)
    facts: list[tuple[str, str, str]] = field(default_factory=list)


@lru_cache
def system_prompt() -> str:
    path = Path(__file__).parent / "prompts" / "facts_vs_feelings.md"
    return path.read_text(encoding="utf-8")


def build_user_prompt(case: Case) -> str:
    lines = "\n".join(f"[{m.id}] {m.sender}: {m.text}" for m in case.messages)
    notes = case.student.notes or ""
    return (
        f"<conversation>\n{lines}\n</conversation>\n\n"
        f"<student_notes>\n[{NOTES_ID}] {notes}\n</student_notes>"
    )


def convert(output: EmotionOutput, case: Case) -> LLMResult:
    """Keep only influence whose kind fits the sender and whose quote is really in the message."""
    by_id = {m.id: m for m in case.messages}
    result = LLMResult()
    for entry in output.entries:
        if entry.message_id == NOTES_ID:
            text, source, allowed = case.student.notes or "", NOTES_SOURCE, STUDENT_KINDS
        elif message := by_id.get(entry.message_id):
            text, source, allowed = message.text, message.evidence_id, side_of(message.sender)
        else:
            continue
        for item in entry.influence:
            quote = item.quote.strip()
            if item.kind in allowed and quote and quote in text:
                result.hits.append(
                    Hit(
                        item.kind, source, quote[:MAX_QUOTE], mask_numbers(item.explanation.strip())
                    )
                )
        if entry.message_id != NOTES_ID and by_id[entry.message_id].sender == "agent":
            for quote in (q.strip() for q in entry.reassurance):
                if quote and quote in text:
                    result.reassurance.append(Hit("reassurance", source, quote[:MAX_QUOTE]))
        if entry.message_id == NOTES_ID:
            continue
        for fact in entry.facts:
            statement, quote = fact.statement.strip(), fact.quote.strip()
            # golden rule 6: a statement with no exact quote behind it is dropped
            if statement and quote and quote in text and len(result.facts) < MAX_FACTS:
                result.facts.append((mask_numbers(statement), source, quote[:MAX_QUOTE]))
    return result


async def facts_vs_feelings(case: Case, ctx: AgentContext) -> LLMResult:
    """One model call over the whole conversation. Raises on LLM or parsing failure."""
    output = await ctx.llm.complete_json(
        system_prompt(), build_user_prompt(case), EmotionOutput, model=MODEL
    )
    return convert(output, case)
