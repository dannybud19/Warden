"""Quote checks V1 to V7, finding format and recap cleaning (plan section 10)."""

import logging
from typing import Literal

import pytest

from app.aggregators.crosschecker.constants import NOT_RUN_ID
from app.aggregators.crosschecker.models import Inconsistency, ReviewOutput, Side
from app.aggregators.crosschecker.sources import Source, SourceKind
from app.aggregators.crosschecker.validate import (
    CONF_STUDENT,
    CONF_VERIFIED,
    MAX_KEPT,
    clean_quote,
    clean_recap,
    friendly_name,
    is_llm_finding,
    normalise,
    not_run_finding,
    original_span,
    slug,
    template_recap,
    to_findings,
)
from app.contracts import Category, CheckId, EvidenceRef, Finding, Severity

CH_URL = "https://find-and-update.company-information.service.gov.uk/company/01234567"
TENANCY_URL = "https://example.org/tenancy-guide"


def _src(sid: str, agent: str, evidence_id: str, kind: SourceKind, text: str) -> Source:
    return Source(id=sid, agent=agent, evidence_id=evidence_id, kind=kind, text=text)


SOURCES = [
    _src(
        "S1",
        "contract_checker",
        "ev_c",
        "finding",
        "Utilities charged. Extra monthly charge.\n"
        f"Source: {TENANCY_URL}\n"
        'quote: "Utilities: £60 per month"',
    ),
    _src("S2", "contract_checker", "ev_c", "quote", "Utilities: £60 per month"),
    _src("S3", "upload", "ev_chat", "message", "[agent] All bills are included in the rent"),
    _src("S4", "upload", "ev_chat", "message", "[agent] Rent is £850 per month, it’s fixed"),
    _src(
        "S5",
        "upload",
        "ev_c",
        "evidence",
        "Rent: £ 950 per month.  Deposit £1,200.00.\nTenancy  starts 15 September.",
    ),
    _src("S6", "student", "listing", "student", "rent_pcm: 850"),
    _src("S7", "contract_checker", "ev_c", "fact", "rent_pcm = 950"),
    _src("S8", "student", "listing", "student", "description: Available 1 September"),
    _src("S9", "companies_house", "companies_house", "finding", f"Dissolved.\nSource: {CH_URL}"),
    _src("S10", "companies_house", "companies_house", "fact", "company_number = 01234567"),
    _src("S11", "upload", "ev_mail", "message", "[agent] The deposit is £1,500"),
    _src("S12", "student", "landlord", "student", "company_number: 01234576"),
    _src("S13", "message_checker", "", "finding", "Odd wording. No quote."),
    _src("S14", "upload", "ev_mail2", "message", "[agent] Rent is £8500 a year"),
    _src("S15", "message_checker", "ev_chat", "finding", f"Bills flagged.\nSource: {TENANCY_URL}"),
]


def _inc(
    topic: str = "utilities",
    a: tuple[str, str] = ("S2", "Utilities: £60 per month"),
    b: tuple[str, str] = ("S3", "All bills are included"),
    *,
    check_id: CheckId = CheckId.CONTRACT_CONSISTENCY,
    severity: Literal["low", "medium", "high"] = "medium",
    claims: tuple[str, str] = ("charges £60 a month for utilities.", "bills are included"),
    why: str = "You may pay more than you expect.",
) -> Inconsistency:
    return Inconsistency(
        topic=topic,
        check_id=check_id,
        severity=severity,
        a=Side(source_id=a[0], claim=claims[0], quote=a[1]),
        b=Side(source_id=b[0], claim=claims[1], quote=b[1]),
        why_it_matters=why,
    )


def _rule(key: str, label: str, values: list[str]) -> Finding:
    return Finding(
        id=f"crosscheck:{key}",
        agent="crosscheck",
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title=f"{label} differs between sources",
        detail="; ".join(values),
        category=Category.CONSISTENCY,
        severity=Severity.HIGH,
        confidence=0.9,
        evidence=[EvidenceRef(evidence_id=f"ev_{n}", quote=v) for n, v in enumerate(values)],
    )


def _run(*incs: Inconsistency, rules: list[Finding] | None = None) -> list[Finding]:
    findings, kept = to_findings(ReviewOutput(inconsistencies=list(incs)), SOURCES, rules or [])
    assert len(findings) == len(kept)
    return findings


# --- a kept inconsistency becomes a finding ----------------------------------------------------


def test_valid_inconsistency_becomes_a_consistency_finding() -> None:
    findings, kept = to_findings(ReviewOutput(inconsistencies=[_inc()]), SOURCES, [])

    assert kept == [_inc()]
    (finding,) = findings
    assert finding.id == "crosscheck:utilities"
    assert finding.agent == "crosscheck"
    assert finding.check_id == CheckId.CONTRACT_CONSISTENCY
    assert finding.title == "Utilities: The contract and Your upload disagree"
    assert finding.detail == (
        'The contract says charges £60 a month for utilities ("Utilities: £60 per month"). '
        'Your upload says bills are included ("All bills are included"). '
        "You may pay more than you expect.\n"
        f"Source: {TENANCY_URL}"
    )
    assert finding.category == Category.CONSISTENCY
    assert finding.severity == Severity.MEDIUM
    assert finding.confidence == CONF_VERIFIED == 0.7
    assert finding.evidence == [
        EvidenceRef(evidence_id="ev_c", quote="Utilities: £60 per month"),
        EvidenceRef(evidence_id="ev_chat", quote="All bills are included"),
    ]
    assert finding.supports == "suspicious"
    assert finding.hard_flag is False
    assert is_llm_finding(finding)


@pytest.mark.parametrize(
    ("severity", "expected"),
    [("low", Severity.LOW), ("medium", Severity.MEDIUM), ("high", Severity.HIGH)],
)
def test_severity_follows_the_model(
    severity: Literal["low", "medium", "high"], expected: Severity
) -> None:
    (finding,) = _run(_inc(severity=severity))
    assert finding.severity == expected
    assert finding.hard_flag is False


def test_check_id_follows_the_model() -> None:
    (finding,) = _run(_inc("who to pay", check_id=CheckId.PAYMENT_SAFETY))
    assert finding.check_id == CheckId.PAYMENT_SAFETY
    assert finding.id == "crosscheck:who-to-pay"


def test_student_side_lowers_confidence_and_copies_source_via_fact() -> None:
    (finding,) = _run(
        _inc(
            "company number",
            ("S10", "01234567"),
            ("S12", "01234576"),
            check_id=CheckId.LANDLORD_IDENTITY,
            claims=("the company number is 01234567", "the company number is 01234576"),
            why="",
        )
    )
    assert finding.confidence == CONF_STUDENT == 0.5
    assert finding.title == "Company number: Agency check and What you entered disagree"
    assert finding.detail == (
        'Agency check says the company number is 01234567 ("01234567"). '
        'What you entered says the company number is 01234576 ("01234576").\n'
        f"Source: {CH_URL}"
    )
    assert [ref.evidence_id for ref in finding.evidence] == ["companies_house", "landlord"]


def test_source_line_copied_from_a_finding_side_and_deduped() -> None:
    (finding,) = _run(
        _inc("company status", ("S9", "Dissolved"), ("S1", "Utilities charged")),
    )
    assert finding.detail.endswith(f"\nSource: {CH_URL}\nSource: {TENANCY_URL}")
    (twice,) = _run(_inc("bills", ("S1", "Utilities charged"), ("S15", "Bills flagged")))
    assert twice.detail.count("Source: ") == 1
    assert twice.detail.endswith(f"\nSource: {TENANCY_URL}")


def test_no_source_lines_when_neither_side_has_one() -> None:
    (finding,) = _run(_inc("rent", ("S4", "£850 per month"), ("S5", "£950 per month")))
    assert "Source:" not in finding.detail


def test_same_friendly_name_title() -> None:
    (finding,) = _run(_inc("rent", ("S4", "Rent is £850"), ("S5", "Rent: £950")))
    assert finding.title == "Rent: two parts of your upload disagree"


def test_friendly_names() -> None:
    assert friendly_name("message_checker") == "Your messages"
    assert friendly_name("emotion_classifier") == "Pressure check"
    assert friendly_name("video_analysis") == "Video check"
    assert friendly_name("some_new_agent") == "Some New Agent"


# --- V1 to V7 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "inc",
    [
        _inc(a=("S99", "Utilities: £60 per month")),
        _inc(b=("S2", "Utilities: £60 per month")),
        _inc(a=("S13", "Odd wording")),
    ],
    ids=["unknown-source", "same-source", "source-without-evidence-id"],
)
def test_v1_drops_bad_source_ids(inc: Inconsistency) -> None:
    assert _run(inc) == []


def test_v2_drops_same_agent_and_same_evidence() -> None:
    assert _run(_inc(a=("S1", "Utilities charged"), b=("S2", "£60 per month"))) == []
    assert _run(_inc("rent", ("S3", "All bills"), ("S4", "Rent is £850"))) == []


def test_v2_keeps_same_agent_on_different_evidence_and_same_evidence_from_another_agent() -> None:
    assert len(_run(_inc("rent", ("S4", "Rent is £850"), ("S5", "Rent: £950")))) == 1
    assert len(_run(_inc("rent", ("S7", "rent_pcm = 950"), ("S5", "Rent: £950")))) == 1


@pytest.mark.parametrize(
    "quote",
    ["All bills are included in the price", "bills included", "£6", "  ...  "],
    ids=["not-in-source", "paraphrase", "too-short", "only-ellipsis"],
)
def test_v3_drops_quotes_not_found_or_too_short(quote: str) -> None:
    assert _run(_inc(b=("S3", quote))) == []


@pytest.mark.parametrize(
    "quote",
    [
        "“All bills are included”",
        '"all BILLS are included"',
        "'All bills are included'",
        "...all bills are included…",
        '  "…All bills  are\nincluded..."  ',
    ],
)
def test_v3_accepts_wrapped_cased_and_spaced_quotes_and_stores_the_source_wording(
    quote: str,
) -> None:
    (finding,) = _run(_inc(b=("S3", quote)))
    assert finding.evidence[1].quote == "All bills are included"  # as written in S3


def test_v3_normalises_pound_spacing_curly_apostrophes_and_whitespace() -> None:
    (finding,) = _run(_inc("rent", ("S4", "it's fixed"), ("S5", "Rent: £950 per month. Deposit")))
    assert [ref.quote for ref in finding.evidence] == [
        "it’s fixed",  # the source's curly apostrophe
        "Rent: £ 950 per month.  Deposit",  # the source's spacing
    ]


@pytest.mark.parametrize(
    ("quote", "text", "span"),
    [
        ("exact words", "some exact words here", "exact words"),
        ("ALL BILLS", "[agent] All bills are in", "All bills"),
        ("£60 a month", "costs £ 60 a  month", "£ 60 a  month"),
        ("it's", "and it’s fine", "it’s"),
        ("not there", "something else", "not there"),
    ],
)
def test_original_span(quote: str, text: str, span: str) -> None:
    assert original_span(quote, text) == span


def test_normalise() -> None:
    assert normalise("  It’s “ALL” in  —  £ 60\n\tpcm – ok ") == 'it\'s "all" in - £60 pcm - ok'
    assert normalise("£ 60") == "£60"


def test_clean_quote() -> None:
    assert clean_quote(' "…it’s fine..." ') == "it’s fine"
    assert clean_quote("‘quoted’") == "quoted"
    assert clean_quote("no wrapping") == "no wrapping"


def test_v4_payment_topic_under_another_check_is_kept_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("test.crosscheck.v4")
    output = ReviewOutput(inconsistencies=[_inc("bank transfer", check_id=CheckId.FAIR_PRICE)])
    with caplog.at_level(logging.INFO, logger=log.name):
        findings, _ = to_findings(output, SOURCES, [], log=log)
    assert findings[0].check_id == CheckId.FAIR_PRICE
    assert "payment topic" in caplog.text


def test_dropped_inconsistencies_are_logged_by_topic_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("test.crosscheck.drop")
    output = ReviewOutput(inconsistencies=[_inc(b=("S3", "a secret made-up quote"))])
    with caplog.at_level(logging.INFO, logger=log.name):
        findings, kept = to_findings(output, SOURCES, [], log=log)
    assert (findings, kept) == ([], [])
    assert "'utilities'" in caplog.text
    assert "V3" in caplog.text
    assert "secret" not in caplog.text


RENT_RULE = _rule("rent_pcm", "Rent", ["850", "950"])


def test_v5_drops_a_repeat_of_a_rule_finding() -> None:
    assert (
        _run(_inc("rent", ("S6", "rent_pcm: 850"), ("S7", "rent_pcm = 950")), rules=[RENT_RULE])
        == []
    )
    assert (
        _run(_inc("monthly rent", ("S4", "£850 per month"), ("S5", "£ 950")), rules=[RENT_RULE])
        == []
    )


def test_v5_compares_numbers_without_commas_and_zero_decimals() -> None:
    rule = _rule("deposit", "Deposit", ["1200", "£1500.00"])
    inc = _inc("deposit amount", ("S5", "Deposit £1,200.00"), ("S11", "deposit is £1,500"))
    assert _run(inc, rules=[rule]) == []


def test_v5_keeps_same_family_with_other_values() -> None:
    rule = _rule("deposit", "Deposit", ["1200", "1100"])
    inc = _inc("deposit amount", ("S5", "Deposit £1,200.00"), ("S11", "deposit is £1,500"))
    assert len(_run(inc, rules=[rule])) == 1


def test_v5_number_must_match_whole() -> None:
    inc = _inc("rent", ("S4", "Rent is £850"), ("S14", "Rent is £8500"))
    assert len(_run(inc, rules=[_rule("rent_pcm", "Rent", ["850", "500"])])) == 1


def test_v5_keeps_other_topics_and_ignores_non_rule_findings() -> None:
    assert len(_run(_inc(), rules=[RENT_RULE])) == 1
    other = RENT_RULE.model_copy(update={"id": "message_checker:rent"})
    inc = _inc("rent", ("S6", "rent_pcm: 850"), ("S7", "rent_pcm = 950"))
    assert len(_run(inc, rules=[other])) == 1


def test_v6_drops_a_repeated_slug() -> None:
    findings = _run(_inc("Utilities"), _inc("utilities!", b=("S3", "included in the rent")))
    assert [f.evidence[1].quote for f in findings] == ["All bills are included"]


def test_v7_keeps_at_most_five() -> None:
    findings = _run(*(_inc(f"topic {n}") for n in range(MAX_KEPT + 1)))  # the model allows 6
    assert [f.id for f in findings] == [f"crosscheck:topic-{n}" for n in range(MAX_KEPT)]


def test_v7_counts_only_kept_ones() -> None:
    bad = [_inc("bad", b=("S3", "not in the source"))]
    good = [_inc(f"good {n}") for n in range(MAX_KEPT)]
    assert len(_run(*bad, *good)) == MAX_KEPT


def test_empty_slug_is_dropped() -> None:
    assert _run(_inc("!!! ??")) == []


# --- ids -----------------------------------------------------------------------------------------


def test_slug_rules() -> None:
    assert slug("Who to pay?") == "who-to-pay"
    assert slug("  Deposit   amount ") == "deposit-amount"
    assert slug("Move-in date / start") == "move-in-date-start"
    long = slug("utilities and council tax and broadband and water rates")
    assert len(long) <= 40
    assert long == "utilities-and-council-tax-and-broadband"
    assert slug("a" * 39 + " b") == "a" * 39


def test_ids_never_take_a_rule_or_not_run_id() -> None:
    findings = _run(_inc("Address"), _inc("deposit"), _inc("not run"))
    assert [f.id for f in findings] == [
        "crosscheck:address-2",
        "crosscheck:deposit-2",
        "crosscheck:not-run-2",
    ]
    assert all(is_llm_finding(f) for f in findings)


def test_same_topic_gives_the_same_id() -> None:
    assert _run(_inc("Utilities"))[0].id == _run(_inc("utilities "))[0].id


# --- clean_recap ---------------------------------------------------------------------------------

UTILITIES = _inc(claims=("charges £60 a month for utilities", "says bills are included"))
GOOD_RECAP = (
    "The contract charges £60 a month for utilities, but your messages say all bills are "
    "included. Ask the agent to confirm in writing."
)


def _template(topics: str) -> str:
    return (
        f"A few details don't match between your documents: {topics}. Before paying anything, "
        "ask the agent to confirm the correct terms in writing."
    )


def test_clean_recap_none_when_nothing_kept() -> None:
    assert clean_recap(GOOD_RECAP, [], [RENT_RULE]) is None


def test_clean_recap_strips_and_collapses_whitespace() -> None:
    messy = "  The contract charges £60   a month for utilities,\n but your messages\tsay all "
    messy += "bills are included. Ask the agent to confirm in writing.  "
    assert clean_recap(messy, [UTILITIES], []) == GOOD_RECAP


def test_clean_recap_empty_uses_template() -> None:
    assert clean_recap("   ", [UTILITIES], []) == _template("utilities")


@pytest.mark.parametrize(
    "word",
    [
        "safe",
        "Safer",
        "SAFEST",
        "safely",
        "scam",
        "scams",
        "Scammer",
        "scammers",
        "scammed",
        "fraud",
        "frauds",
        "fraudulent",
        "fraudster",
        "fraudsters",
        "legit",
        "legitimate",
        "legitimacy",
        "guarantee",
        "guarantees",
        "guaranteed",
        "illegal",
        "illegally",
        "sue",
        "suing",
        "sued",
        "lawyer",
        "lawyers",
        "genuine",
        "fake",
    ],
)
def test_clean_recap_rejects_banned_words(word: str) -> None:
    recap = f"The utilities charge looks {word}. Ask the agent."
    assert clean_recap(recap, [UTILITIES], []) == _template("utilities")


@pytest.mark.parametrize("word", ["unsafe", "safety", "pursue", "legitimise", "fakery"])
def test_clean_recap_banned_words_are_whole_words(word: str) -> None:
    recap = f"The utilities charge is {word}. Ask the agent."
    assert clean_recap(recap, [UTILITIES], []) == recap


def test_clean_recap_rejects_a_topic_nothing_flagged() -> None:
    recap = "The utilities don't match and the deposit is high. Ask the agent."
    assert clean_recap(recap, [UTILITIES], []) == _template("utilities")


def test_clean_recap_allows_topics_from_claims_quotes_and_why() -> None:
    inc = _inc(why="It changes your monthly rent.")
    recap = "The utilities charge changes your rent. Ask the agent."
    assert clean_recap(recap, [inc], []) == recap


def test_clean_recap_allows_rule_finding_topics() -> None:
    recap = "The utilities charge and the rent both differ. Ask the agent."
    assert clean_recap(recap, [UTILITIES], [RENT_RULE]) == recap
    assert clean_recap(recap, [UTILITIES], []) == _template("utilities")
    cleared = RENT_RULE.model_copy(update={"supports": "cleared"})
    assert clean_recap(recap, [UTILITIES], [cleared]) == _template("utilities")


def test_clean_recap_trims_to_whole_sentences_within_80_words() -> None:
    sentence = " ".join(["utilities"] * 29) + " differ."  # 30 words
    recap = " ".join([sentence, sentence, sentence])
    assert clean_recap(recap, [UTILITIES], []) == f"{sentence} {sentence}"


def test_clean_recap_keeps_exactly_80_words() -> None:
    recap = " ".join(["utilities"] * 79) + " differ."
    assert clean_recap(recap, [UTILITIES], []) == recap


def test_clean_recap_single_overlong_sentence_uses_template() -> None:
    recap = " ".join(["utilities"] * 90) + "."
    assert clean_recap(recap, [UTILITIES], [RENT_RULE]) == _template("rent and utilities")


@pytest.mark.parametrize(
    ("topics", "joined"),
    [
        (["rent"], "rent"),
        (["rent", "Utilities"], "rent and utilities"),
        (["rent", "deposit", "utilities"], "rent, deposit and utilities"),
        (["rent", "deposit", "utilities", "dates"], "rent, deposit, utilities and more"),
        (["Rent", "rent ", "deposit"], "rent and deposit"),
    ],
)
def test_template_recap_joins_topics(topics: list[str], joined: str) -> None:
    assert template_recap(topics) == _template(joined)


# --- not-run and is_llm_finding ----------------------------------------------------------------


def test_not_run_finding_matches_appendix_c() -> None:
    finding = not_run_finding("it took too long")
    assert finding.id == NOT_RUN_ID == "crosscheck:not-run"
    assert finding.agent == "crosscheck"
    assert finding.check_id == CheckId.CONTRACT_CONSISTENCY
    assert finding.title == "Cross-check could not run this time"
    assert finding.detail == (
        "The comparison between agents' reports failed (it took too long). "
        "Rule-based checks still ran."
    )
    assert finding.category == Category.CONSISTENCY
    assert finding.severity == Severity.INFO
    assert finding.confidence == 0.0
    assert finding.evidence == []
    assert finding.supports == "suspicious"
    assert finding.hard_flag is False


def test_is_llm_finding() -> None:
    assert is_llm_finding(_run(_inc())[0])
    assert not is_llm_finding(RENT_RULE)
    assert not is_llm_finding(not_run_finding("x"))
    assert not is_llm_finding(RENT_RULE.model_copy(update={"id": "contract_checker:utilities"}))
