"""Sources the LLM may quote, the budget, and the input hash (plan section 6)."""

from datetime import UTC, datetime

from app.aggregators.crosschecker.sources import (
    EVIDENCE_EXCERPT,
    MIN_TRIMMED,
    STUDENT,
    UPLOAD,
    Source,
    SourceKind,
    build_sources,
    collect,
    fit_budget,
    input_hash,
    input_reports,
    quotable,
)
from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Category,
    CheckId,
    Evidence,
    EvidenceKind,
    EvidenceRef,
    Fact,
    FactKey,
    Finding,
    Landlord,
    Listing,
    Message,
    Severity,
)

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _finding(
    agent: str,
    slug: str,
    *,
    title: str = "Utilities charged",
    refs: list[EvidenceRef] | None = None,
) -> Finding:
    return Finding(
        id=f"{agent}:{slug}",
        agent=agent,
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title=title,
        detail="The contract adds a monthly charge.",
        category=Category.DOCUMENT,
        severity=Severity.MEDIUM,
        confidence=0.8,
        evidence=refs if refs is not None else [EvidenceRef(evidence_id="ev_c", quote="£60")],
    )


def _report(
    agent: str,
    findings: list[Finding] | None = None,
    facts: list[Fact] | None = None,
    *,
    status: AgentStatus = AgentStatus.OK,
    input_hash: str = "h1",
) -> AgentReport:
    return AgentReport(
        agent=agent,
        version="1.0.0",
        status=status,
        input_hash=input_hash,
        findings=findings or [],
        facts=facts or [],
    )


def _fact(agent: str, key: FactKey, value: str, source: str = "ev_c") -> Fact:
    return Fact(key=key, value=value, source=source, agent=agent)


def _evidence(ev_id: str, kind: EvidenceKind, text: str | None) -> Evidence:
    return Evidence(id=ev_id, kind=kind, uploaded_at=NOW, extracted_text=text)


def _message(msg_id: str, text: str, sender: str = "agent") -> Message:
    return Message.model_validate(
        {
            "id": msg_id,
            "evidence_id": "ev_chat",
            "sender": sender,
            "channel": "whatsapp",
            "text": text,
        }
    )


def _case(**fields: object) -> Case:
    return Case.model_validate({"case_id": "c1", "created_at": NOW, **fields})


def _src(sid: str, kind: SourceKind, text: str) -> Source:
    return Source(id=sid, agent="a", evidence_id="ev", kind=kind, text=text)


def _kinds(sources: list[Source]) -> list[str]:
    return [s.kind for s in sources]


# --- collect -----------------------------------------------------------------------------------


def test_finding_source_then_its_quotes_then_facts() -> None:
    finding = _finding(
        "contract_checker",
        "utilities",
        refs=[
            EvidenceRef(evidence_id="ev_c", quote="Utilities: £60 per month"),
            EvidenceRef(evidence_id="ev_c2", quote="  "),
            EvidenceRef(evidence_id="ev_c3", quote="paid to the landlord"),
        ],
    )
    fact = _fact("contract_checker", FactKey.RENT_PCM, "850")
    reports = {"contract_checker": _report("contract_checker", [finding], [fact])}

    sources = collect(_case(), reports)

    assert _kinds(sources) == ["finding", "quote", "quote", "fact"]
    first, quote_1, quote_2, fact_src = sources
    assert first.agent == "contract_checker"
    assert first.evidence_id == "ev_c"
    assert first.text == (
        "Utilities charged. The contract adds a monthly charge.\n"
        'quote: "Utilities: £60 per month"\n'
        'quote: "paid to the landlord"'
    )
    assert (quote_1.evidence_id, quote_1.text) == ("ev_c", "Utilities: £60 per month")
    assert (quote_2.evidence_id, quote_2.text) == ("ev_c3", "paid to the landlord")
    assert (fact_src.evidence_id, fact_src.text) == ("ev_c", "rent_pcm = 850")


def test_title_ending_in_punctuation_joins_with_a_space() -> None:
    finding = _finding("message_checker", "pressure", title="Pay today!")
    sources = collect(_case(), {"message_checker": _report("message_checker", [finding])})
    assert sources[0].text.startswith("Pay today! The contract adds")


def test_finding_without_evidence_has_empty_evidence_id_and_no_quotes() -> None:
    finding = _finding("message_checker", "odd", refs=[])
    sources = collect(_case(), {"message_checker": _report("message_checker", [finding])})
    assert _kinds(sources) == ["finding"]
    assert sources[0].evidence_id == ""
    assert "quote:" not in sources[0].text


def test_not_run_findings_are_skipped() -> None:
    findings = [
        _finding("companies_house", "not-run-register"),
        _finding("companies_house", "not-run"),
        _finding("companies_house", "dissolved"),
    ]
    sources = collect(_case(), {"companies_house": _report("companies_house", findings)})
    assert [s.kind for s in sources] == ["finding", "quote"]
    assert all("not-run" not in s.text for s in sources)


def test_only_readable_evidence_kinds_become_sources() -> None:
    evidence = [
        _evidence("ev_contract", EvidenceKind.CONTRACT, "Rent £850"),
        _evidence("ev_doc", EvidenceKind.DOCUMENT, "Inventory"),
        _evidence("ev_mail", EvidenceKind.EMAIL, "Hello"),
        _evidence("ev_chat", EvidenceKind.CHAT_EXPORT, "[agent] hi"),
        _evidence("ev_shot", EvidenceKind.CHAT_SCREENSHOT, "ocr text"),
        _evidence("ev_video", EvidenceKind.VIDEO, "transcript"),
        _evidence("ev_blank", EvidenceKind.CONTRACT, "   \n"),
        _evidence("ev_none", EvidenceKind.CONTRACT, None),
    ]
    sources = collect(_case(evidence=evidence), {})
    assert [s.evidence_id for s in sources] == ["ev_contract", "ev_doc", "ev_mail", "ev_chat"]
    assert {s.kind for s in sources} == {"evidence"}
    assert {s.agent for s in sources} == {UPLOAD}
    assert sources[0].text == "Rent £850"


def test_evidence_excerpt_is_cut_to_4000_chars() -> None:
    text = "x" * (EVIDENCE_EXCERPT + 500)
    sources = collect(_case(evidence=[_evidence("ev_1", EvidenceKind.CONTRACT, text)]), {})
    assert sources[0].text == "x" * EVIDENCE_EXCERPT


def test_message_sources_note_the_sender() -> None:
    messages = [_message("m1", "All bills are included"), _message("m2", "Great", "student")]
    sources = collect(_case(messages=messages), {})
    assert [s.text for s in sources] == ["[agent] All bills are included\n[student] Great"]
    assert {(s.kind, s.agent, s.evidence_id) for s in sources} == {("message", UPLOAD, "ev_chat")}


def test_student_sources_one_per_filled_field() -> None:
    case = _case(
        listing=Listing(address="1 High St", postcode=" ", rent_pcm=850, deposit=0),
        landlord=Landlord(name="Ann Lee", company_number="01234567", email=""),
    )
    sources = collect(case, {})
    assert [(s.evidence_id, s.text) for s in sources] == [
        ("listing", "address: 1 High St"),
        ("listing", "rent_pcm: 850"),
        ("listing", "deposit: 0"),
        ("landlord", "name: Ann Lee"),
        ("landlord", "company_number: 01234567"),
    ]
    assert {(s.kind, s.agent) for s in sources} == {("student", STUDENT)}


def test_sorted_by_agent_stably_and_numbered() -> None:
    reports = {
        "contract_checker": _report("contract_checker", [_finding("contract_checker", "a")]),
        "video_analysis": _report(
            "video_analysis", facts=[_fact("video_analysis", FactKey.ADDRESS, "1 High St")]
        ),
    }
    case = _case(
        messages=[_message("m1", "first"), _message("m2", "second")],
        listing=Listing(address="1 High St"),
    )
    sources = collect(case, reports)
    assert [s.id for s in sources] == [f"S{n}" for n in range(1, len(sources) + 1)]
    assert [(s.agent, s.kind) for s in sources] == [
        ("contract_checker", "finding"),
        ("contract_checker", "quote"),
        (STUDENT, "student"),
        (UPLOAD, "message"),
        ("video_analysis", "fact"),
    ]
    assert [s.text for s in sources if s.kind == "message"] == ["[agent] first\n[agent] second"]


def test_own_report_and_non_ok_reports_are_never_sources() -> None:
    case = _case(
        reports={
            "crosscheck": _report("crosscheck", [_finding("crosscheck", "utilities")]),
            "contract_checker": _report("contract_checker", [_finding("contract_checker", "a")]),
            "message_checker": _report(
                "message_checker", [_finding("message_checker", "b")], status=AgentStatus.ERROR
            ),
            "video_analysis": _report("video_analysis", status=AgentStatus.SKIPPED),
        }
    )
    assert list(input_reports(case)) == ["contract_checker"]
    assert {s.agent for s in build_sources(case)} == {"contract_checker"}


# --- fit_budget --------------------------------------------------------------------------------


def test_fit_budget_is_a_no_op_under_budget() -> None:
    sources = [_src("S1", "evidence", "x" * 600), _src("S2", "finding", "y" * 100)]
    fitted, trimmed = fit_budget(sources, budget=700)
    assert fitted == sources
    assert trimmed == 0


def test_fit_budget_trims_longest_trimmable_first() -> None:
    sources = [
        _src("S1", "finding", "f" * 1000),
        _src("S2", "evidence", "e" * 3000),
        _src("S3", "message", "m" * 600),
        _src("S4", "evidence", "s" * 2000),
    ]
    fitted, trimmed = fit_budget(sources, budget=4000)
    # fixed 1000 + 600 + 2 * cap = 4000 -> cap 1200: both evidence sources cut, the message kept.
    assert [len(s.text) for s in fitted] == [1000, 1200, 600, 1200]
    assert trimmed == 2
    assert [s.id for s in fitted] == ["S1", "S2", "S3", "S4"]
    assert fitted[1].text == "e" * 1200
    assert sum(len(s.text) for s in fitted) <= 4000


def test_fit_budget_never_trims_below_the_floor() -> None:
    sources = [
        _src("S1", "quote", "q" * 3000),
        _src("S2", "evidence", "e" * 2000),
        _src("S3", "message", "m" * 400),
    ]
    fitted, trimmed = fit_budget(sources, budget=1000)
    assert [len(s.text) for s in fitted] == [3000, MIN_TRIMMED, 400]
    assert trimmed == 1


def test_fit_budget_never_touches_finding_quote_fact_or_student() -> None:
    fixed = [
        _src("S1", "finding", "f" * 5000),
        _src("S2", "quote", "q" * 5000),
        _src("S3", "fact", "k" * 5000),
        _src("S4", "student", "s" * 5000),
    ]
    sources = [*fixed, _src("S5", "message", "m" * 5000)]
    fitted, trimmed = fit_budget(sources, budget=10_000)
    assert fitted[:4] == fixed
    assert len(fitted[4].text) == MIN_TRIMMED
    assert trimmed == 1


# --- input_hash --------------------------------------------------------------------------------


def _hash_case(**overrides: object) -> Case:
    fields: dict[str, object] = {
        "reports": {
            "contract_checker": _report(
                "contract_checker",
                [_finding("contract_checker", "utilities")],
                [_fact("contract_checker", FactKey.RENT_PCM, "850")],
            ),
            "message_checker": _report("message_checker", [_finding("message_checker", "bills")]),
        },
        "listing": Listing(address="1 High St", rent_pcm=850),
        "landlord": Landlord(name="Ann Lee"),
        "evidence": [_evidence("ev_c", EvidenceKind.CONTRACT, "Rent £850")],
        "messages": [_message("m1", "All bills are included")],
    }
    return _case(**(fields | overrides))


def _digest(case: Case) -> str:
    return input_hash(case, input_reports(case))


def _with_report(report: AgentReport) -> Case:
    case = _hash_case()
    return case.model_copy(update={"reports": case.reports | {report.agent: report}})


def test_input_hash_is_stable() -> None:
    assert _digest(_hash_case()) == _digest(_hash_case())


def test_input_hash_changes_with_each_input() -> None:
    base = _digest(_hash_case())
    contract = _hash_case().reports["contract_checker"]
    changed = [
        _with_report(contract.model_copy(update={"input_hash": "h2"})),
        _with_report(
            contract.model_copy(update={"findings": [_finding("contract_checker", "other")]})
        ),
        _with_report(
            contract.model_copy(
                update={"facts": [_fact("contract_checker", FactKey.RENT_PCM, "950")]}
            )
        ),
        _hash_case(listing=Listing(address="2 High St", rent_pcm=850)),
        _hash_case(landlord=Landlord(name="Bob Ray")),
        _hash_case(
            evidence=[
                _evidence("ev_c", EvidenceKind.CONTRACT, "Rent £850"),
                _evidence("ev_mail", EvidenceKind.EMAIL, "Bills included"),
            ]
        ),
        _hash_case(messages=[_message("m1", "All bills"), _message("m2", "Pay today")]),
    ]
    digests = [_digest(case) for case in changed]
    assert base not in digests
    assert len(set(digests)) == len(digests)


def test_input_hash_ignores_unreadable_evidence_and_own_report() -> None:
    base = _digest(_hash_case())
    with_video = _hash_case(
        evidence=[
            _evidence("ev_c", EvidenceKind.CONTRACT, "Rent £850"),
            _evidence("ev_v", EvidenceKind.VIDEO, "transcript"),
        ]
    )
    with_own = _with_report(_report("crosscheck", [_finding("crosscheck", "utilities")]))
    assert _digest(with_video) == base
    assert _digest(with_own) == base


def test_messages_are_one_source_per_upload_in_order() -> None:
    other = _message("m3", "Hi from email").model_copy(update={"evidence_id": "ev_mail"})
    messages = [_message("m1", "first"), other, _message("m2", "second", "student")]
    sources = collect(_case(messages=messages), {})
    assert [(s.evidence_id, s.text) for s in sources] == [
        ("ev_chat", "[agent] first\n[student] second"),
        ("ev_mail", "[agent] Hi from email"),
    ]


def test_an_upload_with_parsed_messages_is_not_sent_twice() -> None:
    evidence = [
        _evidence("ev_chat", EvidenceKind.CHAT_EXPORT, "[05/11] Agent: All bills are included"),
        _evidence("ev_contract", EvidenceKind.CONTRACT, "Rent £850"),
    ]
    sources = collect(_case(evidence=evidence, messages=[_message("m1", "All bills")]), {})
    assert [(s.kind, s.evidence_id) for s in sources] == [
        ("evidence", "ev_contract"),
        ("message", "ev_chat"),
    ]


def test_a_long_chat_is_trimmed_as_one_source() -> None:
    messages = [_message(f"m{n}", f"message number {n:03d} " * 4) for n in range(300)]
    raw = collect(_case(messages=messages), {})
    assert len(raw) == 1 and len(raw[0].text) > 24_000
    fitted, trimmed = fit_budget(raw)
    assert trimmed == 1
    assert sum(len(s.text) for s in fitted) <= 24_000


def test_quotable_text_leaves_out_labels_and_agents_words() -> None:
    finding = _finding("contract_checker", "fee")
    report = _report(
        "contract_checker",
        [finding],
        facts=[_fact("contract_checker", FactKey.RENT_PCM, "950")],
    )
    case = _case(
        messages=[_message("m1", "All bills"), _message("m2", "[agent] in text", "student")],
        listing=Listing(description="Available 1 Sep"),
        evidence=[_evidence("ev_contract", EvidenceKind.CONTRACT, "Rent £950")],
    )
    by_kind = {s.kind: quotable(s) for s in collect(case, {"contract_checker": report})}
    assert by_kind["finding"] == ""  # the agent's own words are not evidence
    assert by_kind["quote"] == finding.evidence[0].quote
    assert by_kind["fact"] == "950"
    assert by_kind["student"] == "Available 1 Sep"
    # Only the sender label we add is removed; "[agent]" typed in the message itself stays.
    assert by_kind["message"] == "All bills\n[agent] in text"
    assert by_kind["evidence"] == "Rent £950"
