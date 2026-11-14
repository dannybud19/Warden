"""Every fixture case and report loads, dumps and reloads unchanged."""

import json
from pathlib import Path

import pytest

from app.contracts import AgentReport, Case

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
CASE_FILES = sorted((FIXTURES / "cases").glob("*.json"))
REPORT_FILES = sorted((FIXTURES / "reports").glob("*.json"))
STUB_REPORT_FILES = [p for p in REPORT_FILES if p.name != "full_case.json"]


def _model_for(path: Path) -> type[Case] | type[AgentReport]:
    return Case if path.parent.name == "cases" or path.name == "full_case.json" else AgentReport


@pytest.mark.parametrize(
    "path", CASE_FILES + REPORT_FILES, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_fixture_roundtrips(path: Path) -> None:
    model = _model_for(path)
    loaded = model.model_validate_json(path.read_text())
    dumped = loaded.model_dump_json()
    assert model.model_validate_json(dumped) == loaded
    assert model.model_validate(json.loads(dumped)) == loaded


def test_expected_fixtures_exist() -> None:
    assert {p.stem for p in CASE_FILES} >= {"fake_agency", "overseas_landlord", "genuine_flat"}
    assert {p.stem for p in REPORT_FILES} >= {
        "companies_house",
        "message_checker",
        "contract_checker",
        "emotion_classifier",
        "video_analysis",
        "full_case",
    }


def test_stub_finding_quotes_appear_in_fake_agency() -> None:
    """Stub reports must make sense against fake_agency.json: every quote is real."""
    case = Case.model_validate_json((FIXTURES / "cases" / "fake_agency.json").read_text())
    texts = {e.id: e.extracted_text or "" for e in case.evidence}
    for path in STUB_REPORT_FILES:
        report = AgentReport.model_validate_json(path.read_text())
        for finding in report.findings:
            assert finding.evidence, finding.id
            for ref in finding.evidence:
                assert ref.quote and ref.quote in texts[ref.evidence_id], finding.id


def test_case_json_defaults_survive_a_minimal_case() -> None:
    case = Case.model_validate({"case_id": "c", "created_at": "2026-11-14T15:00:00Z"})
    assert case.status == "open" and case.checks == [] and case.decision is None
