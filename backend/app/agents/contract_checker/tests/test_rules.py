from datetime import date
from decimal import Decimal

import pytest

from app.agents.contract_checker.documents import extract_document
from app.agents.contract_checker.models import MoneyTerm, Quote, ReviewContext, RuleId
from app.agents.contract_checker.rulebook import load_rulebook
from app.agents.contract_checker.rules import (
    check_advance_amounts,
    check_amounts,
    check_candidates,
    explicit_candidates,
    extract_money,
    money_values,
    validate_money,
)


def context(**changes) -> ReviewContext:
    return ReviewContext.model_validate(
        {
            "assessment_date": "2026-11-14",
            "jurisdiction": "england",
            "tenancy_type": "ordinary_private",
            "agreement_date": "2026-11-14",
            "rent_basis": "whole_tenancy",
            **changes,
        }
    )


def amount_issues(text: str, **changes):
    doc = extract_document(text.encode(), "contract.txt")
    money, rejected = validate_money(doc, extract_money(doc))
    assert rejected == 0
    return check_amounts(doc, money, context(**changes), load_rulebook())


@pytest.mark.parametrize("deposit,status", [("1500", "cleared"), ("1500.01", "confirmed")])
def test_deposit_exact_boundary_and_decimal_penny(deposit: str, status: str) -> None:
    issues = amount_issues(f"1. Rent: £1,300 per month\n2. Deposit: £{deposit}")
    assert len(issues) == 1 and issues[0].status == status
    assert "15600 / 52 * 5" in (issues[0].calculation or "")


def test_six_week_threshold_is_not_treated_as_five() -> None:
    issues = amount_issues("1. Annual rent: £52,000 per year\n2. Deposit: £6,000")
    assert issues[0].status == "cleared"
    assert "52000 / 52 * 6" in (issues[0].calculation or "")


def test_annual_rent_outside_supported_scope_never_gets_a_false_cap() -> None:
    issue = amount_issues("1. Rent: £120,000 per year\n2. Deposit: £20,000")[0]
    assert issue.status == "conditional" and issue.calculation is None


def test_holding_deposit_is_not_also_counted_as_tenancy_deposit() -> None:
    issues = amount_issues("1. Rent: £300 per week\n2. Holding deposit: £301")
    assert [(i.rule_id, i.status) for i in issues] == [(RuleId.HOLDING, "confirmed")]


def test_equivalent_frequencies_agree_but_changed_amount_conflicts() -> None:
    clean = "1. Rent: £1300 per month\n2. Annual rent: £15600 per year\n3. Deposit: £1500"
    assert not any(i.rule_id == RuleId.CONFLICT for i in amount_issues(clean))
    bad = clean.replace("15600", "16800")
    assert any(i.rule_id == RuleId.CONFLICT for i in amount_issues(bad))
    assert all(i.status == "conditional" for i in amount_issues(bad))


def test_unknown_applicability_produces_conditional_concern() -> None:
    issue = amount_issues(
        "1. Rent: £1300 per month\n2. Deposit: £1800",
        tenancy_type="unknown",
        jurisdiction="unknown",
    )[0]
    assert issue.status == "conditional" and issue.question and issue.uncertainty


def test_invented_numeric_value_is_rejected_even_when_quote_exists() -> None:
    doc = extract_document(b"1. Rent: GBP 1300 per month", "contract.txt")
    term = MoneyTerm(
        kind="rent",
        amount=Decimal("130"),
        frequency="month",
        evidence=Quote(segment_id="s1", quote="Rent: GBP 1300 per month"),
    )
    assert validate_money(doc, [term]) == ([], 1)


def test_unknown_frequency_is_not_assumed_monthly() -> None:
    issue = amount_issues("1. Rent: £1300\n2. Deposit: £1500")[0]
    assert issue.status == "conditional" and issue.calculation is None


def test_short_quote_cannot_hide_a_conflicting_rent_period() -> None:
    doc = extract_document(b"1. The tenant owes GBP 300 per week.", "contract.txt")
    term = MoneyTerm(
        kind="rent",
        amount=Decimal("300"),
        frequency="month",
        evidence=Quote(segment_id="s1", quote="GBP 300"),
    )
    assert validate_money(doc, [term]) == ([], 1)


def test_money_parser_does_not_accept_a_prefix_of_a_malformed_amount() -> None:
    assert money_values("GBP 1,30 and GBP 500.001") == set()
    assert money_values("GBP 1,300.00. Other charge: GBP 50, payable later.") == {
        Decimal("1300"),
        Decimal("50"),
    }


def test_advance_rent_limit_keeps_signing_and_date_uncertainty() -> None:
    doc = extract_document(
        b"1. Rent: GBP 1300 per month\n2. Rent in advance: GBP 3900 before tenancy starts",
        "contract.txt",
    )
    issues = check_advance_amounts(doc, extract_money(doc), context(), load_rulebook())
    assert len(issues) == 1 and issues[0].status == "confirmed"
    old = context(agreement_date=date(2026, 4, 1))
    assert (
        check_advance_amounts(doc, extract_money(doc), old, load_rulebook())[0].status
        == "conditional"
    )


def test_missing_schedule_is_incomplete_not_an_allegation_of_illegality() -> None:
    doc = extract_document(b"1. Payments are defined in Schedule 2.", "contract.txt")
    issues, _ = check_candidates(
        doc, explicit_candidates(doc), context(), load_rulebook(), origin="rule"
    )
    assert issues[0].status == "conditional" and issues[0].legal_sources == []
    supplied = extract_document(
        b"1. Payments are defined in Schedule 2.\nSchedule 2:\nRent is paid monthly.",
        "contract.txt",
    )
    assert explicit_candidates(supplied) == []


def test_no_fee_and_ast_heading_alone_are_not_findings() -> None:
    doc = extract_document(
        b"ASSURED SHORTHOLD TENANCY AGREEMENT\n1. No administration fee of GBP 150 is payable.",
        "contract.txt",
    )
    assert explicit_candidates(doc) == []


def test_same_deposit_in_two_clauses_is_one_issue_citing_both() -> None:
    issues = amount_issues(
        "1. Rent: £1,450 per month\n2. Deposit: £1,670\n"
        "3. The tenancy deposit of £1,670 is protected with the DPS."
    )
    deposits = [i for i in issues if i.rule_id == RuleId.DEPOSIT]
    assert len(deposits) == 1
    assert len({ref.segment_id for ref in deposits[0].evidence}) == 3
    assert deposits[0].within_cap is True


def test_two_different_deposit_amounts_still_give_two_issues() -> None:
    issues = amount_issues("1. Rent: £1,450 per month\n2. Deposit: £1,670\n3. Deposit: £2,000")
    assert [i.within_cap for i in issues if i.rule_id == RuleId.DEPOSIT].count(None) == 0
    assert len([i for i in issues if i.rule_id == RuleId.DEPOSIT]) == 2


def test_deposit_over_cap_is_not_within_cap() -> None:
    issue = amount_issues("1. Rent: £1,300 per month\n2. Deposit: £1,800")[0]
    assert issue.within_cap is False and issue.status == "confirmed"


def _adapted(text: str, **changes):
    from app.agents.contract_checker.agent import report_findings
    from app.agents.contract_checker.models import ContractReview

    doc = extract_document(text.encode(), "contract.txt")
    issues = amount_issues(text, **changes)
    review = ContractReview(
        status="partial",
        context=context(**changes),
        document_id=doc.id,
        document_sha256=doc.sha256,
        issues=issues,
    )
    return report_findings(review)


def test_deposit_within_cap_with_unknown_scope_is_an_info_note_not_a_concern() -> None:
    # E2E S4: two clauses stated the same deposit; both came out as "suspicious" concerns.
    findings = _adapted(
        "1. Rent: GBP 1450 per calendar month.\n2. Tenancy deposit: GBP 1670.\n"
        "3. The deposit GBP 1670 is protected in the DPS.",
        jurisdiction="unknown",
        tenancy_type="unknown",
        rent_basis="unknown",
    )
    deposits = [f for f in findings if f.id.startswith("contract_checker:deposit_cap:")]
    assert len(deposits) == 1
    note = deposits[0]
    assert note.severity == "info" and note.confidence == 0.0
    assert note.title == "Deposit is within the legal cap (scope not confirmed)"
    assert "Confirm that the rented property is in England." in note.detail


def test_deposit_over_cap_with_unknown_scope_stays_a_concern() -> None:
    findings = _adapted(
        "1. Rent: £1,300 per month\n2. Deposit: £1,800",
        jurisdiction="unknown",
        tenancy_type="unknown",
    )
    assert [(f.severity, f.title) for f in findings] == [
        ("low", "Deposit exceeds the calculated cap")
    ]
