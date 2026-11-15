"""A certain listing-vs-contract address disagreement found by the LLM is a hard flag.

The rule crosscheck only compares addresses that both carry a full postcode, so a listing that
gives only "W12" was never compared with the contract. The LLM now makes that comparison.
"""

import json
from dataclasses import replace
from typing import Any, Literal

from app.aggregators.crosschecker.crosschecker import review
from app.aggregators.crosschecker.models import Inconsistency, ReviewOutput, Side
from app.aggregators.crosschecker.sources import Source, SourceKind, build_sources
from app.aggregators.crosschecker.tests.test_review_flow import load, real, sid
from app.aggregators.crosschecker.validate import CONF_HARD, CONF_VERIFIED, to_findings
from app.contracts import CheckId, Evidence, EvidenceKind, Listing, Severity
from app.core.agent import AgentContext
from app.core.llm import FakeLLM

LISTING_ADDRESS = "12 Elm Road, London W12"
CONTRACT_ADDRESS = "7 Hackney Road, London E2 7NS"
KINDS = {
    "ev_c": EvidenceKind.CONTRACT,
    "ev_l": EvidenceKind.LISTING,
    "ev_chat": EvidenceKind.CHAT_EXPORT,
}


def _src(sid_: str, agent: str, evidence_id: str, kind: SourceKind, text: str) -> Source:
    return Source(id=sid_, agent=agent, evidence_id=evidence_id, kind=kind, text=text)


SOURCES = [
    _src("S1", "student", "listing", "student", f"address: {LISTING_ADDRESS}"),
    _src("S2", "upload", "ev_c", "evidence", f"Property: {CONTRACT_ADDRESS}. Rent £1,300 pcm."),
    _src("S3", "upload", "ev_l", "evidence", "Double room, 12 Elm Road, London W12 8QT"),
    _src("S4", "upload", "ev_chat", "message", "[agent] The flat is at 9 Bow Road, London E3 2SE"),
    _src("S5", "upload", "ev_c2", "evidence", "Property: 12 Elm Road, London W12 8QT"),
]


def _inc(
    a: tuple[str, str],
    b: tuple[str, str],
    *,
    certainty: Literal["certain", "likely", "possible"] = "certain",
    topic: str = "property address",
    check_id: CheckId = CheckId.CONTRACT_CONSISTENCY,
) -> Inconsistency:
    return Inconsistency(
        topic=topic,
        check_id=check_id,
        severity="high",
        certainty=certainty,
        a=Side(source_id=a[0], claim="the home is here", quote=a[1]),
        b=Side(source_id=b[0], claim="the home is there", quote=b[1]),
        why_it_matters="The contract may be for a different home.",
    )


def _run(inc: Inconsistency, kinds: dict[str, EvidenceKind] | None = KINDS) -> Any:
    findings, _ = to_findings(
        ReviewOutput(inconsistencies=[inc]), SOURCES, [], evidence_kinds=kinds
    )
    (finding,) = findings
    return finding


def test_certain_mismatch_between_typed_listing_and_contract_is_a_hard_flag() -> None:
    finding = _run(_inc(("S1", LISTING_ADDRESS), ("S2", CONTRACT_ADDRESS)))

    assert finding.hard_flag is True
    assert finding.severity == Severity.CRITICAL
    assert finding.check_id == CheckId.CONTRACT_CONSISTENCY
    assert finding.confidence == CONF_HARD


def test_uploaded_listing_counts_as_the_listing() -> None:
    finding = _run(_inc(("S3", "12 Elm Road, London W12 8QT"), ("S2", CONTRACT_ADDRESS)))
    assert finding.hard_flag is True


def test_check_is_forced_to_contract_consistency() -> None:
    inc = _inc(("S1", LISTING_ADDRESS), ("S2", CONTRACT_ADDRESS), check_id=CheckId.RIGHT_TO_LET)
    assert _run(inc).check_id == CheckId.CONTRACT_CONSISTENCY


def test_likely_or_possible_mismatch_stays_soft() -> None:
    for certainty in ("likely", "possible"):
        inc = _inc(("S1", LISTING_ADDRESS), ("S2", CONTRACT_ADDRESS), certainty=certainty)
        finding = _run(inc)
        assert finding.hard_flag is False
        assert finding.severity == Severity.HIGH


def test_chat_against_contract_is_not_a_hard_flag() -> None:
    finding = _run(_inc(("S4", "9 Bow Road, London E3 2SE"), ("S2", CONTRACT_ADDRESS)))
    assert finding.hard_flag is False
    assert finding.confidence == CONF_VERIFIED


def test_other_topics_are_never_hard() -> None:
    finding = _run(_inc(("S1", LISTING_ADDRESS), ("S2", "Rent £1,300 pcm"), topic="rent"))
    assert finding.hard_flag is False


def test_same_full_postcode_overrules_the_llm() -> None:
    kinds = {**KINDS, "ev_c2": EvidenceKind.CONTRACT}
    inc = _inc(("S3", "12 Elm Road, London W12 8QT"), ("S5", "12 Elm Road, London W12 8QT"))
    assert _run(inc, kinds).hard_flag is False


def test_without_evidence_kinds_nothing_is_hard() -> None:
    finding = _run(_inc(("S1", LISTING_ADDRESS), ("S2", CONTRACT_ADDRESS)), kinds=None)
    assert finding.hard_flag is False


def test_certainty_defaults_to_likely_for_older_replies() -> None:
    inc = Inconsistency.model_validate(
        {
            "topic": "rent",
            "check_id": "contract_consistency",
            "severity": "high",
            "a": {"source_id": "S1", "claim": "x", "quote": "abc"},
            "b": {"source_id": "S2", "claim": "y", "quote": "def"},
            "why_it_matters": "",
        }
    )
    assert inc.certainty == "likely"


async def test_review_flags_a_contract_for_another_home_when_the_listing_has_no_full_postcode(
    ctx: AgentContext,
) -> None:
    case = load("utilities")
    contract = next(e for e in case.evidence if e.kind == EvidenceKind.CONTRACT)
    contract_text = f"Property: {CONTRACT_ADDRESS}\n{contract.extracted_text}"
    evidence: list[Evidence] = [
        e.model_copy(update={"extracted_text": contract_text}) if e.id == contract.id else e
        for e in case.evidence
    ]
    listing = (case.listing or Listing()).model_copy(
        update={"address": LISTING_ADDRESS, "postcode": "W12"}
    )
    case = case.model_copy(update={"evidence": evidence, "listing": listing})
    sources = build_sources(case)
    item = {
        "topic": "property address",
        "check_id": "contract_consistency",
        "severity": "high",
        "certainty": "certain",
        "a": {
            "source_id": sid(sources, f"address: {LISTING_ADDRESS}", agent="student"),
            "claim": "the listing is on Elm Road in W12",
            "quote": LISTING_ADDRESS,
        },
        "b": {
            "source_id": sid(sources, CONTRACT_ADDRESS, kind="evidence"),
            "claim": "the contract is for a home on Hackney Road in E2",
            "quote": CONTRACT_ADDRESS,
        },
        "why_it_matters": "The contract may be for a different home than the one you viewed.",
    }
    llm = FakeLLM({"SOURCES": json.dumps({"inconsistencies": [item], "recap": ""})})

    report = await review(case, [], real(replace(ctx), llm))

    (finding,) = [f for f in report.findings if f.hard_flag]
    assert finding.id == "crosscheck:property-address"
    assert finding.severity == Severity.CRITICAL
    assert [r.evidence_id for r in finding.evidence] == ["listing", contract.id]


def test_an_uploaded_listing_is_sent_to_the_llm() -> None:
    case = load("utilities")
    listing = Evidence.model_validate(
        {
            "id": "ev_listing",
            "kind": "listing",
            "uploaded_at": "2026-11-15T09:00:00Z",
            "extracted_text": "Double room, 12 Elm Road, London W12",
        }
    )
    case = case.model_copy(update={"evidence": [*case.evidence, listing]})
    assert any(s.evidence_id == "ev_listing" for s in build_sources(case))
