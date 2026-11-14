"""EmotionClassifier: separates facts from pressure language, and compares rent with the area."""

from typing import Any

from app.agents.emotion_classifier.llm import LLMResult, facts_vs_feelings
from app.agents.emotion_classifier.pricing import AGENT, price_finding
from app.agents.emotion_classifier.rules import (
    AGENT_KINDS,
    PRESSURE_KINDS,
    STUDENT_KINDS,
    TITLES,
    Hit,
    reassurance_hits,
    rule_hits,
)
from app.contracts import AgentReport, Case, Category, CheckId, EvidenceRef, Finding, Severity
from app.core.agent import AgentContext, BaseAgent, Need

MAX_REFS = 3
MANY_KINDS = 3  # this many distinct pressure kinds raises them all to high


def _refs(hits: list[Hit]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for hit in hits:
        ref = EvidenceRef(evidence_id=hit.source, quote=hit.quote)
        if ref not in refs:
            refs.append(ref)
    return refs[:MAX_REFS]


def _finding(
    slug: str,
    title: str,
    detail: str,
    severity: Severity,
    hits: list[Hit],
    *,
    cleared: bool = False,
) -> Finding:
    return Finding(
        id=f"{AGENT}:{slug}",
        agent=AGENT,
        check_id=CheckId.NO_PRESSURE,
        title=title,
        detail=detail,
        category=Category.PRESSURE,
        severity=severity,
        confidence=0.6 if cleared else 0.75,
        evidence=_refs(hits),
        supports="cleared" if cleared else "suspicious",
    )


def _explain(hits: list[Hit]) -> str:
    """The explanations for one kind, model wording first, without repeats."""
    seen: list[str] = []
    for hit in sorted(hits, key=lambda h: not h.explanation):
        if hit.explanation and hit.explanation not in seen:
            seen.append(hit.explanation)
    return " ".join(seen[:2]) or "This wording works on feelings rather than stating a fact."


def pressure_findings(hits: list[Hit], reassurance: list[Hit]) -> list[Finding]:
    """One finding per influence kind, and a clear when the agent only takes pressure off."""
    by_kind: dict[str, list[Hit]] = {}
    for hit in hits:
        by_kind.setdefault(hit.kind, []).append(hit)
    agent_kinds = [k for k in AGENT_KINDS if k in by_kind]
    many = len(agent_kinds) >= MANY_KINDS

    findings: list[Finding] = []
    for kind in agent_kinds:
        if kind in PRESSURE_KINDS:
            severity = Severity.HIGH if many else Severity.MEDIUM
        else:
            severity = Severity.LOW
        findings.append(
            _finding(
                f"pressure_{kind}", TITLES[kind], _explain(by_kind[kind]), severity, by_kind[kind]
            )
        )
    for kind in (k for k in STUDENT_KINDS if k in by_kind):
        findings.append(
            _finding(
                f"student_{kind}",
                TITLES[kind],
                _explain(by_kind[kind]),
                Severity.INFO,
                by_kind[kind],
            )
        )
    if reassurance and not any(k in PRESSURE_KINDS for k in agent_kinds):
        findings.append(
            _finding(
                "no_pressure_stated",
                "The agent gives you time to decide",
                "The agent explicitly takes time pressure off, and no pressure language was found.",
                Severity.INFO,
                reassurance,
                cleared=True,
            )
        )
    return findings


def facts_finding(facts: list[tuple[str, str, str]]) -> Finding | None:
    """The plain facts the messages state, for the facts-vs-feelings view. Never moves a check.

    Each statement is the model's neutral rewording; its evidence is the exact quote behind it.
    """
    if not facts:
        return None
    detail = " ".join(f"• {statement}" for statement, _, _ in facts)
    finding = _finding(
        "stated_facts", "What the messages actually state", detail, Severity.INFO, []
    )
    refs: list[EvidenceRef] = []
    for _, source, quote in facts:
        ref = EvidenceRef(evidence_id=source, quote=quote)
        if ref not in refs:
            refs.append(ref)
    return finding.model_copy(update={"evidence": refs})


class EmotionClassifierAgent(BaseAgent):
    name = "emotion_classifier"
    version = "0.2.0"
    requires = frozenset({Need.MESSAGES})

    def input_slice(self, case: Case) -> dict[str, Any]:
        """Messages plus the listing, so the pricing check reruns when rent or postcode change."""
        data = super().input_slice(case)
        data["listing"] = case.listing.model_dump(mode="json") if case.listing else None
        return data

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        try:
            llm = await facts_vs_feelings(case, ctx)
        except Exception as exc:  # noqa: BLE001 - the rules and pricing must still report
            ctx.log.warning("emotion_classifier: LLM pass failed, rules only (%r)", exc)
            llm = LLMResult()
        findings = pressure_findings(
            rule_hits(case) + llm.hits, reassurance_hits(case) + llm.reassurance
        )
        for extra in (facts_finding(llm.facts), price_finding(case)):
            if extra:
                findings.append(extra)
        return self.report(case, findings=findings)
