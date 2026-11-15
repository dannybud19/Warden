"""End-to-end scenarios X1 to X16 (plan section 11) through `review()`, offline with fake LLMs."""

import ast
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from app.aggregators.crosschecker import crosschecker
from app.aggregators.crosschecker.crosschecker import NAME, VERSION, recap, review
from app.aggregators.crosschecker.sources import (
    MIN_TRIMMED,
    SOURCE_BUDGET,
    TRIMMABLE_KINDS,
    Source,
    build_sources,
    collect,
    input_reports,
)
from app.aggregators.crosschecker.stub import STUB_VERSION
from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Category,
    CheckId,
    Evidence,
    EvidenceKind,
    EvidenceRef,
    Finding,
    Message,
    Severity,
)
from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.core.settings import Settings

T = TypeVar("T", bound=BaseModel)

FIXTURES = Path(__file__).parent / "fixtures"
PACKAGE = Path(__file__).parent.parent
KEY = "SOURCES"  # first line of the user message
UTILITIES_RECAP = (
    "Your contract charges £60 a month for utilities, but the agent said all bills are "
    "included. Ask the agent to confirm in writing which is right."
)
TEMPLATE_UTILITIES = (
    "A few details don't match between your documents: utilities. Before paying anything, ask "
    "the agent to confirm the correct terms in writing."
)


# --- helpers ---------------------------------------------------------------------------------


def load(name: str) -> Case:
    return Case.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def real(ctx: AgentContext, llm: Any) -> AgentContext:
    """A context in which the Cross-checker runs its LLM pass with `llm`."""
    settings = Settings(_env_file=None, default_agent_mode="real", storage="memory")  # type: ignore[call-arg]
    return replace(ctx, settings=settings, llm=llm)


def sid(
    sources: list[Source], contains: str, *, agent: str | None = None, kind: str | None = None
) -> str:
    """The id of the first source whose text contains `contains` (and matches agent/kind)."""
    for source in sources:
        if (
            contains in source.text
            and agent in (None, source.agent)
            and kind in (None, source.kind)
        ):
            return source.id
    raise AssertionError(f"no source contains {contains!r} (agent={agent}, kind={kind})")


def side(source_id: str, quote: str, claim: str = "it says so") -> dict[str, str]:
    return {"source_id": source_id, "claim": claim, "quote": quote}


def inconsistency(
    topic: str,
    a: dict[str, str],
    b: dict[str, str],
    *,
    check: str = "contract_consistency",
    severity: str = "medium",
    why: str = "You might pay more than you expect.",
) -> dict[str, Any]:
    return {
        "topic": topic,
        "check_id": check,
        "severity": severity,
        "a": a,
        "b": b,
        "why_it_matters": why,
    }


def llm_reply(*items: dict[str, Any], recap_text: str = "") -> FakeLLM:
    return FakeLLM({KEY: json.dumps({"inconsistencies": list(items), "recap": recap_text})})


def utilities_item(sources: list[Source]) -> dict[str, Any]:
    """The X1 disagreement: the contract's utilities charge vs "all bills are included"."""
    return inconsistency(
        "utilities",
        side(
            sid(sources, "Utilities: £60 per month", agent="contract_checker", kind="quote"),
            "Utilities: £60 per month",
            "utilities cost £60 a month on top of the rent",
        ),
        side(
            sid(sources, "all bills are included", kind="message"),
            "all bills are included",
            "all bills are included in the rent",
        ),
    )


def rule(
    key: str,
    label: str,
    values: list[tuple[str, str]],
    *,
    severity: Severity = Severity.HIGH,
    hard_flag: bool = False,
) -> Finding:
    """A rule finding shaped like `orchestrator/crosscheck.py` makes them."""
    return Finding(
        id=f"crosscheck:{key}",
        agent="crosscheck",
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title=f"{label} differs between sources",
        detail="; ".join(f"{value!r} (from {source})" for source, value in values),
        category=Category.CONSISTENCY,
        severity=severity,
        confidence=0.9,
        evidence=[EvidenceRef(evidence_id=source, quote=value) for source, value in values],
        hard_flag=hard_flag,
    )


def previous_report(summary: str | None, *, input_hash: str = "stale") -> AgentReport:
    return AgentReport(
        agent=NAME,
        version=VERSION,
        status=AgentStatus.OK,
        input_hash=input_hash,
        findings=[],
        summary=summary,
    )


def with_reports(case: Case, **reports: AgentReport) -> Case:
    return case.model_copy(update={"reports": {**case.reports, **reports}})


def with_email(case: Case, text: str = "Hello, the flat is still available.") -> Case:
    """`case` plus one more readable upload: new material for the Cross-checker to compare."""
    email = Evidence(
        id=f"ev_email{len(case.evidence)}",
        kind=EvidenceKind.EMAIL,
        uploaded_at=case.evidence[0].uploaded_at,
        extracted_text=text,
    )
    return case.model_copy(update={"evidence": [*case.evidence, email]})


def llm_findings(report: AgentReport, rules: list[Finding]) -> list[Finding]:
    return report.findings[len(rules) :]


class RaisingLLM(FakeLLM):
    """An LLM whose `complete_json` fails like a network or API error."""

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        self.calls.append({"method": "complete_json", "system": system, "user": user})
        raise RuntimeError("upstream exploded")


class SleepingLLM(FakeLLM):
    """An LLM that answers far too slowly."""

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        self.calls.append({"method": "complete_json", "system": system, "user": user})
        await asyncio.sleep(5)
        return schema.model_validate_json('{"inconsistencies": [], "recap": ""}')


@pytest.fixture
def utilities() -> Case:
    return load("utilities")


@pytest.fixture
def genuine() -> Case:
    return load("genuine")


# --- X1 to X3: real disagreements --------------------------------------------------------------


async def test_x1_utilities_disagreement_is_flagged_with_both_quotes(
    utilities: Case, ctx: AgentContext
) -> None:
    sources = build_sources(utilities)
    llm = llm_reply(utilities_item(sources), recap_text=UTILITIES_RECAP)
    report = await review(utilities, [], real(ctx, llm))

    assert [f.id for f in report.findings] == ["crosscheck:utilities"]
    finding = report.findings[0]
    assert finding.agent == NAME
    assert finding.check_id == CheckId.CONTRACT_CONSISTENCY
    assert finding.severity in (Severity.MEDIUM, Severity.HIGH)
    assert finding.confidence == 0.7
    assert finding.category == Category.CONSISTENCY
    assert finding.supports == "suspicious"
    assert finding.hard_flag is False
    assert [(r.evidence_id, r.quote) for r in finding.evidence] == [
        ("ev_contract", "Utilities: £60 per month"),
        ("ev_chat", "all bills are included"),
    ]
    assert finding.title.startswith("Utilities: ")
    assert report.summary == UTILITIES_RECAP
    assert "utilities" in report.summary
    assert report.status == AgentStatus.OK
    assert report.version == VERSION
    assert report.input_hash != ""
    assert len(llm.calls) == 1


async def test_x1_recap_may_name_a_rule_topic_too(utilities: Case, ctx: AgentContext) -> None:
    rules = [rule("rent_pcm", "Rent", [("listing", "950"), ("ev_contract", "900")])]
    text = "The rent differs between sources, and the contract adds £60 for utilities."
    llm = llm_reply(utilities_item(build_sources(utilities)), recap_text=text)
    report = await review(utilities, rules, real(ctx, llm))

    assert report.findings[0] == rules[0]
    assert [f.id for f in llm_findings(report, rules)] == ["crosscheck:utilities"]
    assert report.summary == text  # "rent" is a rule topic, so the recap is not replaced


async def test_x2_who_to_pay_goes_to_payment_safety(utilities: Case, ctx: AgentContext) -> None:
    sources = build_sources(utilities)
    rules = [rule("deposit", "Deposit", [("listing", "1000"), ("ev_contract", "1200")])]
    item = inconsistency(
        "who to pay",
        side(
            sid(sources, "pay to Prime City Lettings Ltd", kind="evidence"),
            "pay to Prime City Lettings Ltd",
            "rent is paid to the company",
        ),
        side(
            sid(sources, "send it to my personal account", agent="message_checker", kind="quote"),
            "send it to my personal account",
            "money goes to the agent's personal account",
        ),
        check="payment_safety",
        severity="high",
    )
    report = await review(utilities, rules, real(ctx, llm_reply(item)))

    assert report.findings[0] == rules[0]  # rule findings first and unchanged
    [finding] = llm_findings(report, rules)
    assert finding.id == "crosscheck:who-to-pay"
    assert finding.check_id == CheckId.PAYMENT_SAFETY
    assert finding.severity == Severity.HIGH
    assert finding.confidence == 0.7
    assert finding.hard_flag is False


async def test_x3_student_side_gets_lower_confidence(utilities: Case, ctx: AgentContext) -> None:
    sources = build_sources(utilities)
    item = inconsistency(
        "move-in date",
        side(sid(sources, "available 1 Sep", agent="student"), "available 1 Sep"),
        side(sid(sources, "tenancy starts 15 Sep", kind="evidence"), "tenancy starts 15 Sep"),
    )
    report = await review(utilities, [], real(ctx, llm_reply(item)))

    [finding] = report.findings
    assert finding.id == "crosscheck:move-in-date"
    assert finding.confidence == 0.5
    assert {r.evidence_id for r in finding.evidence} == {"listing", "ev_contract"}


# --- X4 to X7: nothing real to flag --------------------------------------------------------------


async def test_x4_consistent_case_gives_no_findings_and_no_summary(
    genuine: Case, ctx: AgentContext
) -> None:
    llm = llm_reply()
    report = await review(genuine, [], real(ctx, llm))
    assert report.findings == []
    assert report.summary is None
    assert len(llm.calls) == 1


async def test_x4_rule_findings_alone_get_the_template_recap(
    genuine: Case, ctx: AgentContext
) -> None:
    rules = [rule("rent_pcm", "Rent", [("listing", "1200"), ("ev_contract", "1250")])]
    report = await review(genuine, rules, real(ctx, llm_reply()))
    assert report.findings == rules
    assert report.summary == recap(rules)
    assert report.summary == "Two sources disagree on the rent. Check these before you pay."


async def test_x5_fabricated_quote_is_dropped(utilities: Case, ctx: AgentContext) -> None:
    sources = build_sources(utilities)
    item = inconsistency(
        "utilities",
        side(sid(sources, "Utilities: £60 per month", kind="quote"), "Utilities: £75 per month"),
        side(sid(sources, "all bills are included", kind="message"), "all bills are included"),
    )
    report = await review(utilities, [], real(ctx, llm_reply(item, recap_text=UTILITIES_RECAP)))
    assert report.findings == []
    assert report.summary is None


async def test_x6_same_agent_and_same_evidence_is_dropped(
    utilities: Case, ctx: AgentContext
) -> None:
    sources = build_sources(utilities)
    # Two different sources, both the contract checker's reading of the contract.
    a = sid(sources, "Utilities: £60 per month", agent="contract_checker", kind="quote")
    b = sid(sources, "950", agent="contract_checker", kind="fact")
    assert a != b
    item = inconsistency("rent", side(a, "Utilities: £60 per month"), side(b, "950"))
    llm = llm_reply(item)
    report = await review(utilities, [], real(ctx, llm))
    assert len(llm.calls) == 1
    assert report.findings == []


async def test_x7_llm_copy_of_a_rule_mismatch_is_dropped(
    utilities: Case, ctx: AgentContext
) -> None:
    listing_address = "12 Baker Street, NW1 6XE"
    contract_address = "4 Oak Road, E2 7QR"
    assert utilities.listing is not None
    evidence = [
        e.model_copy(update={"extracted_text": f"{e.extracted_text}Property: {contract_address}\n"})
        if e.id == "ev_contract"
        else e
        for e in utilities.evidence
    ]
    case = utilities.model_copy(
        update={
            "listing": utilities.listing.model_copy(update={"address": listing_address}),
            "evidence": evidence,
        }
    )
    rules = [
        rule(
            "address",
            "Address",
            [("listing", listing_address), ("ev_contract", contract_address)],
            severity=Severity.CRITICAL,
            hard_flag=True,
        )
    ]
    sources = build_sources(case)
    item = inconsistency(
        "property address",
        side(sid(sources, listing_address, agent="student"), listing_address),
        side(sid(sources, contract_address, kind="evidence"), contract_address),
        severity="high",
    )
    report = await review(case, rules, real(ctx, llm_reply(item, recap_text="Addresses differ.")))

    assert report.findings == rules
    assert report.findings[0].hard_flag is True
    assert report.summary == recap(rules)


# --- X8 to X10: when the LLM is (not) called ------------------------------------------------------


@pytest.mark.parametrize("with_rule", [False, True])
async def test_x8_fewer_than_two_ok_reports_skip_the_llm(
    utilities: Case, ctx: AgentContext, with_rule: bool
) -> None:
    failed = utilities.reports["message_checker"].model_copy(
        update={"status": AgentStatus.ERROR, "error": "boom"}
    )
    case = with_reports(utilities, message_checker=failed)
    rules = (
        [rule("rent_pcm", "Rent", [("listing", "950"), ("ev_contract", "900")])]
        if with_rule
        else []
    )
    llm = llm_reply(utilities_item(build_sources(utilities)), recap_text=UTILITIES_RECAP)
    report = await review(case, rules, real(ctx, llm))

    assert llm.calls == []
    assert report.findings == rules
    assert report.summary == recap(rules)
    assert (report.summary is None) is (not with_rule)
    assert report.input_hash != ""


async def test_x9_unchanged_inputs_reuse_the_previous_result(
    utilities: Case, ctx: AgentContext
) -> None:
    rules = [rule("rent_pcm", "Rent", [("listing", "950"), ("ev_contract", "900")])]
    first_llm = llm_reply(utilities_item(build_sources(utilities)), recap_text=UTILITIES_RECAP)
    first = await review(utilities, rules, real(ctx, first_llm))
    assert len(first_llm.calls) == 1

    second_llm = llm_reply()
    second = await review(with_reports(utilities, crosscheck=first), rules, real(ctx, second_llm))

    assert second_llm.calls == []
    assert second.findings == first.findings
    assert [f.id for f in second.findings] == ["crosscheck:rent_pcm", "crosscheck:utilities"]
    assert second.summary == first.summary == UTILITIES_RECAP
    assert second.input_hash == first.input_hash


async def test_x9_changed_inputs_call_the_llm_again(utilities: Case, ctx: AgentContext) -> None:
    first = await review(
        utilities, [], real(ctx, llm_reply(utilities_item(build_sources(utilities))))
    )
    case = with_reports(with_email(utilities), crosscheck=first)
    llm = llm_reply()
    await review(case, [], real(ctx, llm))
    assert len(llm.calls) == 1


def _failing_llm(kind: str) -> FakeLLM:
    if kind == "raises":
        return RaisingLLM()
    if kind == "invalid_json":
        return FakeLLM({KEY: "not json at all"})
    return SleepingLLM()


@pytest.mark.parametrize("kind", ["raises", "invalid_json", "timeout"])
@pytest.mark.parametrize("previous_summary", [None, "Earlier recap about utilities."])
async def test_x10_llm_failure_keeps_rules_and_adds_not_run(
    utilities: Case,
    ctx: AgentContext,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    previous_summary: str | None,
) -> None:
    monkeypatch.setattr(crosschecker, "LLM_TIMEOUT_S", 0.05)
    rules = [rule("rent_pcm", "Rent", [("listing", "950"), ("ev_contract", "900")])]
    case = with_reports(utilities, crosscheck=previous_report(previous_summary))
    llm = _failing_llm(kind)
    report = await review(case, rules, real(ctx, llm))

    assert len(llm.calls) == 1
    assert report.findings[:1] == rules
    [not_run] = report.findings[1:]
    assert not_run.id == "crosscheck:not-run"
    assert not_run.severity == Severity.INFO
    assert not_run.confidence == 0.0
    assert not_run.evidence == []
    assert not_run.hard_flag is False
    assert "upstream exploded" not in not_run.detail  # no raw exception text
    assert report.input_hash == ""  # so the next analysis retries
    assert report.status == AgentStatus.OK
    assert report.summary == (previous_summary or recap(rules))


async def test_x10_failure_without_previous_or_rules_has_no_summary(
    utilities: Case, ctx: AgentContext
) -> None:
    report = await review(utilities, [], real(ctx, RaisingLLM()))
    assert [f.id for f in report.findings] == ["crosscheck:not-run"]
    assert report.summary is None


# --- X11: recap rules --------------------------------------------------------------------------


async def test_x11_recap_with_a_banned_word_becomes_the_template(
    utilities: Case, ctx: AgentContext
) -> None:
    text = "This flat looks safe, but the utilities don't match."
    llm = llm_reply(utilities_item(build_sources(utilities)), recap_text=text)
    report = await review(utilities, [], real(ctx, llm))
    assert report.summary == TEMPLATE_UTILITIES


async def test_x11_long_recap_is_cut_to_whole_sentences(utilities: Case, ctx: AgentContext) -> None:
    sentence = "The utilities terms do not match " + "and this matters " * 7 + "to you."
    assert len(sentence.split()) == 29
    text = " ".join([sentence] * 3)  # 87 words
    llm = llm_reply(utilities_item(build_sources(utilities)), recap_text=text)
    report = await review(utilities, [], real(ctx, llm))

    assert report.summary is not None
    assert report.summary == f"{sentence} {sentence}"
    assert len(report.summary.split()) <= 80


# --- X12, X13: stub mode and its own previous report ---------------------------------------------


async def test_x12_stub_mode_returns_rules_and_the_template(
    utilities: Case, ctx: AgentContext
) -> None:
    assert isinstance(ctx.llm, FakeLLM)
    rules = [rule("rent_pcm", "Rent", [("listing", "950"), ("ev_contract", "900")])]
    report = await review(utilities, rules, ctx)  # the default ctx is stub mode

    assert ctx.llm.calls == []
    assert report.findings == rules
    assert report.summary == recap(rules)
    assert report.version == STUB_VERSION
    assert report.input_hash == ""


def _previous_with_text(marker: str) -> AgentReport:
    finding = Finding(
        id="crosscheck:old-topic",
        agent=NAME,
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title=f"{marker} previous finding",
        detail=f"{marker} detail",
        category=Category.CONSISTENCY,
        severity=Severity.MEDIUM,
        confidence=0.7,
        evidence=[EvidenceRef(evidence_id="ev_chat", quote=f"{marker} quote")],
    )
    return previous_report("Old recap.").model_copy(update={"findings": [finding]})


async def test_x13_own_previous_report_is_not_an_input(utilities: Case, ctx: AgentContext) -> None:
    reports = {
        "contract_checker": utilities.reports["contract_checker"],
        "crosscheck": _previous_with_text("ZEBRA"),
    }
    case = utilities.model_copy(update={"reports": reports})
    llm = llm_reply()
    await review(case, [], real(ctx, llm))
    assert llm.calls == []  # one other OK report only: nothing to compare


async def test_x13_own_previous_report_is_not_a_source(utilities: Case, ctx: AgentContext) -> None:
    case = with_reports(utilities, crosscheck=_previous_with_text("ZEBRA"))
    assert all(s.agent != NAME for s in build_sources(case))
    llm = llm_reply()
    report = await review(case, [], real(ctx, llm))

    assert len(llm.calls) == 1
    assert "ZEBRA" not in llm.calls[0]["user"]
    assert report.findings == []  # the old LLM finding is not carried over on a fresh pass


# --- X14: source budget ------------------------------------------------------------------------


async def test_x14_oversized_evidence_is_trimmed_but_findings_survive(
    utilities: Case, ctx: AgentContext
) -> None:
    base = utilities.evidence[0]
    documents = [
        Evidence(
            id=f"ev_doc{i}",
            kind=EvidenceKind.DOCUMENT,
            uploaded_at=base.uploaded_at,
            extracted_text=f"Document {i}. " + "Filler text for the budget test. " * 200,
        )
        for i in range(8)
    ]
    long_message = Message(
        id="msg_long",
        evidence_id="ev_chat",
        sender="agent",
        channel="whatsapp",
        text="Long message. " * 2_000,
    )
    case = utilities.model_copy(
        update={
            "evidence": [*utilities.evidence, *documents],
            "messages": [*utilities.messages, long_message],
        }
    )
    raw = {s.id: s.text for s in collect(case, input_reports(case))}
    assert sum(map(len, raw.values())) > SOURCE_BUDGET  # the test really is over budget
    sources = build_sources(case)
    assert sum(len(s.text) for s in sources) <= SOURCE_BUDGET
    assert [s.id for s in sources] == list(raw)
    trimmed = 0
    for source in sources:
        if source.kind in TRIMMABLE_KINDS:
            assert raw[source.id].startswith(source.text)
            assert len(source.text) >= min(MIN_TRIMMED, len(raw[source.id]))
            trimmed += source.text != raw[source.id]
        else:
            assert source.text == raw[source.id]  # findings, quotes, facts, student: whole
    assert trimmed > 0

    item = inconsistency(
        "utilities",
        side(sid(sources, "Utilities: £60 per month", kind="quote"), "Utilities: £60 per month"),
        side(
            sid(sources, "all bills are included", agent="message_checker", kind="quote"),
            "all bills are included",
        ),
    )
    llm = llm_reply(item)
    report = await review(case, [], real(ctx, llm))

    assert len(llm.calls) == 1
    assert [f.id for f in report.findings] == ["crosscheck:utilities"]


# --- X15, X16: import rules and stable ids -------------------------------------------------

FORBIDDEN = ("app.orchestrator", "app.api", "app.storage", "app.intake")


def test_x15_package_imports_only_contracts_core_and_itself() -> None:
    offenders: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{path.name}: {name}"
                for name in names
                if any(name == f or name.startswith(f"{f}.") for f in FORBIDDEN)
            ]
    assert offenders == []


async def test_x16_same_topic_gives_the_same_id(utilities: Case, ctx: AgentContext) -> None:
    sources = build_sources(utilities)
    first = await review(utilities, [], real(ctx, llm_reply(utilities_item(sources))))
    renamed = utilities_item(sources) | {"topic": "  Utilities "}
    second = await review(utilities, [], real(ctx, llm_reply(renamed)))
    assert [f.id for f in first.findings] == [f.id for f in second.findings]
    assert [f.id for f in first.findings] == ["crosscheck:utilities"]


# --- carried over when this run can't check again ---------------------------------------------


async def _first_run(utilities: Case, ctx: AgentContext) -> AgentReport:
    llm = llm_reply(utilities_item(build_sources(utilities)), recap_text=UTILITIES_RECAP)
    report = await review(utilities, [], real(ctx, llm))
    assert [f.id for f in report.findings] == ["crosscheck:utilities"]
    return report


async def test_llm_failure_keeps_the_disagreements_already_verified(
    utilities: Case, ctx: AgentContext
) -> None:
    first = await _first_run(utilities, ctx)
    case = with_reports(with_email(utilities), crosscheck=first)
    report = await review(case, [], real(ctx, RaisingLLM()))

    assert [f.id for f in report.findings] == ["crosscheck:utilities", "crosscheck:not-run"]
    assert report.findings[0] == first.findings[0]
    assert report.summary == UTILITIES_RECAP
    assert report.input_hash == ""


async def test_a_report_failing_for_now_keeps_the_disagreements_already_verified(
    utilities: Case, ctx: AgentContext
) -> None:
    first = await _first_run(utilities, ctx)
    failed = utilities.reports["message_checker"].model_copy(update={"status": AgentStatus.ERROR})
    case = with_reports(utilities, crosscheck=first, message_checker=failed)
    llm = llm_reply()
    report = await review(case, [], real(ctx, llm))

    assert llm.calls == []
    assert report.findings == first.findings
    assert report.summary == UTILITIES_RECAP


async def test_a_new_version_checks_again_and_carries_nothing(
    utilities: Case, ctx: AgentContext
) -> None:
    first = await _first_run(utilities, ctx)
    older = first.model_copy(update={"version": "0.9.0"})
    llm = llm_reply()
    report = await review(with_reports(utilities, crosscheck=older), [], real(ctx, llm))

    assert len(llm.calls) == 1  # same input hash, but another version: no reuse
    assert report.findings == []


class CancelledLLM(FakeLLM):
    """An LLM call cancelled from outside (the orchestrator's own deadline)."""

    async def complete_json(
        self, system: str, user: str, schema: type[T], *, model: str | None = None
    ) -> T:
        raise asyncio.CancelledError


async def test_cancellation_is_not_swallowed(utilities: Case, ctx: AgentContext) -> None:
    with pytest.raises(asyncio.CancelledError):
        await review(utilities, [], real(ctx, CancelledLLM()))


# --- stable findings across reruns (E9) -------------------------------------------------------


async def test_a_reply_with_no_new_evidence_does_not_call_the_llm_again(
    utilities: Case, ctx: AgentContext
) -> None:
    """Action answers change the agents' input hashes and may reword their findings, but not the
    material the Cross-checker compares: the earlier findings and recap stand, with no LLM call."""
    first = await _first_run(utilities, ctx)
    contract = utilities.reports["contract_checker"]
    reworded = contract.model_copy(
        update={
            "input_hash": "after-the-student-answered",
            "findings": [
                f.model_copy(update={"title": "A new title", "detail": "New wording."})
                for f in contract.findings
            ],
        }
    )
    case = with_reports(utilities, crosscheck=first, contract_checker=reworded)
    llm = llm_reply()
    report = await review(case, [], real(ctx, llm))

    assert llm.calls == []
    assert report.findings == first.findings
    assert report.summary == UTILITIES_RECAP
    assert report.input_hash == first.input_hash


async def test_a_rerun_that_words_the_same_disagreement_differently_keeps_one_finding(
    utilities: Case, ctx: AgentContext
) -> None:
    first = await _first_run(utilities, ctx)
    case = with_reports(with_email(utilities), crosscheck=first)
    sources = build_sources(case)
    renamed = utilities_item(sources) | {"topic": "Bills charged on top of the rent"}
    report = await review(case, [], real(ctx, llm_reply(renamed, recap_text=UTILITIES_RECAP)))

    assert [f.id for f in report.findings] == ["crosscheck:bills-charged-on-top-of-the-rent"]


async def test_a_rerun_that_misses_a_disagreement_keeps_it_while_its_quotes_stand(
    utilities: Case, ctx: AgentContext
) -> None:
    first = await _first_run(utilities, ctx)
    case = with_reports(with_email(utilities), crosscheck=first)
    llm = llm_reply()  # the new run finds nothing at all
    report = await review(case, [], real(ctx, llm))

    assert len(llm.calls) == 1
    assert report.findings == first.findings
    assert report.summary == UTILITIES_RECAP  # nothing new, so the same recap
    assert report.input_hash != first.input_hash


async def test_a_rerun_that_adds_a_disagreement_keeps_the_old_one_and_names_both(
    utilities: Case, ctx: AgentContext
) -> None:
    first = await _first_run(utilities, ctx)
    case = with_reports(with_email(utilities), crosscheck=first)
    sources = build_sources(case)
    account = inconsistency(
        "who to pay",
        side(sid(sources, "send it to my personal account", kind="message"), "my personal account"),
        side(
            sid(sources, "Utilities: £60 per month", agent="contract_checker", kind="quote"),
            "Utilities: £60 per month",
        ),
        check="payment_safety",
    )
    report = await review(case, [], real(ctx, llm_reply(account)))

    assert [f.id for f in report.findings] == ["crosscheck:who-to-pay", "crosscheck:utilities"]
    assert report.summary is not None
    assert "who to pay" in report.summary and "utilities" in report.summary


async def test_a_carried_disagreement_is_dropped_when_its_quote_is_gone(
    utilities: Case, ctx: AgentContext
) -> None:
    first = await _first_run(utilities, ctx)
    messages = [m.model_copy(update={"text": "Nothing else to add."}) for m in utilities.messages]
    message_checker = utilities.reports["message_checker"].model_copy(update={"findings": []})
    case = with_reports(
        with_email(utilities).model_copy(update={"messages": messages}),
        crosscheck=first,
        message_checker=message_checker,
    )
    report = await review(case, [], real(ctx, llm_reply()))

    assert report.findings == []
    assert report.summary is None
