"""The rule-only recap (ported from the orchestrator's stub) and stub mode."""

from typing import Literal

from app.aggregators.crosschecker import crosschecker
from app.aggregators.crosschecker.crosschecker import NAME, VERSION, recap, review
from app.aggregators.crosschecker.stub import STUB_VERSION
from app.contracts import AgentStatus, Case, Category, CheckId, EvidenceRef, Finding, Severity
from app.core.agent import AgentContext
from app.core.llm import FakeLLM


def _finding(
    label: str,
    severity: Severity = Severity.MEDIUM,
    *,
    hard_flag: bool = False,
    supports: Literal["suspicious", "cleared"] = "suspicious",
) -> Finding:
    slug = label.lower().replace(" ", "_")
    return Finding(
        id=f"crosscheck:{slug}",
        agent="crosscheck",
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title=f"{label} differs between sources",
        detail="'850' (from listing); '950' (from ev_1)",
        category=Category.CONSISTENCY,
        severity=severity,
        confidence=0.9,
        evidence=[EvidenceRef(evidence_id="ev_1", quote="950")],
        supports=supports,
        hard_flag=hard_flag,
    )


def test_public_names_the_orchestrator_uses() -> None:
    assert NAME == "crosscheck"
    assert VERSION == "1.1.0"
    assert crosschecker.recap is recap
    assert crosschecker.LLM_TIMEOUT_S < 30.0  # below the orchestrator's own deadline


def test_no_findings_gives_no_summary() -> None:
    assert recap([]) is None


def test_one_topic_wording() -> None:
    assert recap([_finding("Rent")]) == "Two sources disagree on the rent."


def test_two_topic_wording() -> None:
    findings = [_finding("Rent"), _finding("Address")]
    assert recap(findings) == "Sources disagree on: rent, address."


def test_multi_word_label_is_lower_cased() -> None:
    assert recap([_finding("Landlord name")]) == "Two sources disagree on the landlord name."


def test_title_without_suffix_uses_whole_title() -> None:
    finding = _finding("Rent").model_copy(update={"title": "Bills Mismatch"})
    assert recap([finding]) == "Two sources disagree on the bills mismatch."


def test_hard_flag_appends_warning() -> None:
    findings = [_finding("Address", hard_flag=True)]
    assert recap(findings) == "Two sources disagree on the address. Check these before you pay."


def test_high_severity_appends_warning() -> None:
    findings = [_finding("Deposit"), _finding("Rent", Severity.HIGH)]
    assert recap(findings) == "Sources disagree on: deposit, rent. Check these before you pay."


def test_medium_only_has_no_warning() -> None:
    assert recap([_finding("Deposit")]) == "Two sources disagree on the deposit."


def test_duplicate_topics_collapse() -> None:
    findings = [_finding("Rent"), _finding("Address"), _finding("Rent")]
    assert recap(findings) == "Sources disagree on: rent, address."


def test_cleared_findings_are_not_disagreements() -> None:
    cleared = _finding("Rent", Severity.CRITICAL, hard_flag=True, supports="cleared")
    assert recap([cleared]) is None
    assert recap([cleared, _finding("Deposit")]) == "Two sources disagree on the deposit."


def test_topics_beyond_the_cap_are_counted() -> None:
    labels = ["A", "B", "C", "D", "E", "F", "G", "H"]
    summary = recap([_finding(label) for label in labels])
    assert summary == "Sources disagree on: a, b, c, d, e, f and 2 more."


async def test_stub_passes_rule_findings_through_with_the_template_recap(
    fake_agency_case: Case, ctx: AgentContext
) -> None:
    findings = [_finding("Rent", Severity.HIGH), _finding("Deposit")]
    report = await review(fake_agency_case, findings, ctx)
    assert report.agent == NAME
    assert report.version == STUB_VERSION
    assert report.status == AgentStatus.OK
    assert report.input_hash == ""
    assert report.findings == findings
    assert report.findings is not findings
    assert report.summary == "Sources disagree on: rent, deposit. Check these before you pay."


async def test_stub_with_no_findings(fake_agency_case: Case, ctx: AgentContext) -> None:
    report = await review(fake_agency_case, [], ctx)
    assert report.findings == []
    assert report.summary is None


async def test_stub_never_calls_the_llm(fake_agency_case: Case, ctx: AgentContext) -> None:
    assert isinstance(ctx.llm, FakeLLM)
    await review(fake_agency_case, [_finding("Rent")], ctx)
    assert ctx.llm.calls == []
