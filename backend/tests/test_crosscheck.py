import pytest

from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    CheckId,
    Fact,
    FactKey,
    Severity,
)
from app.orchestrator.crosscheck import compare, facts_from_case, normalise


def _report(agent: str, facts: list[Fact]) -> AgentReport:
    return AgentReport(agent=agent, version="t", status=AgentStatus.OK, input_hash="", facts=facts)


def _fact(key: FactKey, value: str, source: str, agent: str = "x") -> Fact:
    return Fact(key=key, value=value, source=source, agent=agent)


def test_contract_vs_listing_address_is_a_critical_hard_flag(fake_agency_case: Case) -> None:
    reports = {
        "contract_checker": _report(
            "contract_checker",
            [_fact(FactKey.ADDRESS, "W12 7RJ", "ev_contract", "contract_checker")],
        )
    }
    findings = compare(fake_agency_case, reports)
    assert [f.id for f in findings] == ["crosscheck:address"]
    finding = findings[0]
    assert finding.severity == Severity.CRITICAL
    assert finding.hard_flag is True
    assert finding.check_id == CheckId.CONTRACT_CONSISTENCY
    assert finding.title == "Address differs between sources"
    assert {r.evidence_id for r in finding.evidence} == {"listing", "ev_contract"}


def test_matching_values_give_no_findings(fake_agency_case: Case) -> None:
    reports = {
        "contract_checker": _report(
            "contract_checker",
            [
                _fact(FactKey.ADDRESS, "48 Wood Lane, London W12 8QT", "ev_contract"),
                _fact(FactKey.DEPOSIT, "£1,700", "ev_contract"),
                _fact(FactKey.RENT_PCM, "850", "ev_contract"),
            ],
        )
    }
    assert compare(fake_agency_case, reports) == []


def test_address_mismatch_without_a_contract_is_not_a_hard_flag(fake_agency_case: Case) -> None:
    reports = {
        "message_checker": _report(
            "message_checker", [_fact(FactKey.ADDRESS, "SW1A 1AA", "ev_chat1")]
        )
    }
    (finding,) = compare(fake_agency_case, reports)
    assert finding.severity == Severity.CRITICAL and finding.hard_flag is False


def test_rent_deposit_and_company_number_rules(fake_agency_case: Case) -> None:
    case = fake_agency_case.model_copy(
        update={
            "landlord": fake_agency_case.landlord.model_copy(  # type: ignore[union-attr]
                update={"company_number": "1234567"}
            )
        }
    )
    reports = {
        "a": _report(
            "a",
            [
                _fact(FactKey.RENT_PCM, "£900", "ev_chat1"),
                _fact(FactKey.DEPOSIT, "2000", "ev_contract"),
                _fact(FactKey.COMPANY_NUMBER, "07654321", "ev_chat1"),
                _fact(
                    FactKey.LANDLORD_NAME, "Mark Evans Ltd", "ev_chat1"
                ),  # same person once normalised
            ],
        )
    }
    by_id = {f.id: f for f in compare(case, reports)}
    assert set(by_id) == {"crosscheck:rent_pcm", "crosscheck:deposit", "crosscheck:company_number"}
    assert by_id["crosscheck:rent_pcm"].severity == Severity.HIGH
    assert by_id["crosscheck:deposit"].severity == Severity.MEDIUM
    assert by_id["crosscheck:company_number"].check_id == CheckId.LANDLORD_IDENTITY


def test_non_ok_reports_are_ignored(fake_agency_case: Case) -> None:
    bad = _report("a", [_fact(FactKey.RENT_PCM, "999", "ev_chat1")]).model_copy(
        update={"status": AgentStatus.ERROR}
    )
    assert compare(fake_agency_case, {"a": bad}) == []


def test_facts_from_case(fake_agency_case: Case) -> None:
    facts = facts_from_case(fake_agency_case)
    assert {(f.key, f.source, f.agent) for f in facts} == {
        (FactKey.ADDRESS, "listing", "case"),
        (FactKey.RENT_PCM, "listing", "case"),
        (FactKey.DEPOSIT, "listing", "case"),
        (FactKey.LANDLORD_NAME, "landlord", "case"),
    }


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        (FactKey.RENT_PCM, "£1,200 pcm", "1200"),
        (FactKey.COMPANY_NUMBER, " 1234567 ", "01234567"),
        (FactKey.COMPANY_NUMBER, "sc123456", "SC123456"),
        (FactKey.ADDRESS, "Flat 3, 12 Elm Road, London w12 8qt", "W128QT"),
        (FactKey.ADDRESS, "W128QT", "W128QT"),
        (FactKey.ADDRESS, "12 Elm Road!", "12elmroad"),
        (FactKey.LANDLORD_NAME, "Prime City Lettings Ltd.", "prime city"),
    ],
)
def test_normalise(key: FactKey, value: str, expected: str) -> None:
    assert normalise(key, value) == expected
