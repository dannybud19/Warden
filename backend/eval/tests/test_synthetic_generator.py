"""Offline checks for the synthetic case corpus and its evaluator boundary."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.contracts import Case, CheckId, CheckState
from eval.synthetic.engine import apply_paraphrase, build_dataset, facts_for, load_scenarios
from eval.synthetic.external import (
    FixtureSearch,
    FixtureUnavailableError,
    MissingFixtureError,
    mock_transport,
)
from eval.synthetic.models import FAMILIES, Paraphrase, Rewrite, Scenario
from eval.synthetic.storage import contained_path, validate_dataset, write_dataset


def _generated(root: Path, *, seed: int = 20261114, paraphrases: bool = True) -> Any:
    """Generate into an isolated directory so tests never touch the committed corpus."""
    return write_dataset(root, seed, paraphrases=paraphrases)


def _manifest_path(root: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = root / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path


def _replace_manifest(root: Path, manifest: dict[str, Any]) -> None:
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(("paraphrases", "expected"), [(True, 40), (False, 32)])
def test_generate_expected_corpus_size_and_validate(
    tmp_path: Path, paraphrases: bool, expected: int
) -> None:
    manifest = _generated(tmp_path / "corpus", paraphrases=paraphrases)

    assert len(manifest.cases) == expected
    assert len(validate_dataset(tmp_path / "corpus").cases) == expected
    assert {"scam", "genuine", "unknown"}.issubset({entry.truth for entry in manifest.cases})


def test_generation_is_deterministic_and_label_data_is_outside_case_inputs(tmp_path: Path) -> None:
    first = build_dataset(20261114)
    second = build_dataset(20261114)
    assert first == second

    root = tmp_path / "corpus"
    _generated(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    labels = json.loads((root / "labels.json").read_text(encoding="utf-8"))
    assert labels == {entry["case_id"]: entry["truth"] for entry in manifest["cases"]}
    assert Counter(c["kind"] for c in manifest["comparisons"]) == Counter(
        {"meaningful_change": 16, "wording_only": 8}
    )
    for entry in manifest["cases"]:
        case_file = root / entry["files"]["case.json"]
        raw = json.loads(case_file.read_text(encoding="utf-8"))
        forbidden = {"truth", "label", "labels", "expectations", "allowed_outcomes"}
        assert forbidden.isdisjoint(raw)
        assert all(forbidden.isdisjoint(evidence) for evidence in raw["evidence"])


def test_catalogue_has_eight_core_families_and_balanced_core_controls() -> None:
    scenarios = load_scenarios(paraphrases=False)
    core = [
        scenario
        for scenario in scenarios
        if scenario.variant in {"concern", "genuine", "unresolved"}
    ]
    assert {scenario.family for scenario in core} == set(FAMILIES)
    for family in FAMILIES:
        assert Counter(
            scenario.variant for scenario in core if scenario.family == family
        ) == Counter({"concern": 1, "genuine": 1, "unresolved": 1})


def test_controls_distinguish_payment_urgency_from_benign_confounders() -> None:
    scenarios = {scenario.key: scenario for scenario in load_scenarios()}
    urgent = scenarios["compound_deadline_prepaid_no_viewing"]
    benign = scenarios["compound_genuine_urgent_abroad_explained_roles"]
    urgent_stances = {(e.check_id.value, e.stance) for e in urgent.expectations}
    benign_stances = {(e.check_id.value, e.stance) for e in benign.expectations}

    assert ("payment_safety", "concern") in urgent_stances
    assert ("no_pressure", "concern") in urgent_stances
    assert ("no_pressure", "must_not_assert") in benign_stances
    assert ("fair_price", "must_not_assert") in benign_stances
    assert ("landlord_identity", "must_not_assert") in benign_stances
    assert any("abroad" in e.topic for e in benign.expectations)
    assert any("roles" in e.topic for e in benign.expectations)
    assert any("lower rent" in message.text.lower() for message in benign.messages)
    assert any(
        "smaller room" in message.text.lower() and "explain" in message.text.lower()
        for message in benign.messages
    )


def test_case_inputs_have_fresh_eight_unverified_checks_and_raw_sources(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)

    for entry in manifest.cases:
        raw = json.loads((root / entry.files["case.json"]).read_text(encoding="utf-8"))
        case = Case.model_validate(raw)
        assert Counter(check.id for check in case.checks) == Counter(CheckId)
        assert all(
            check.state == CheckState.UNVERIFIED
            and check.clear_confidence == 0
            and not check.finding_ids
            and check.reason is None
            for check in case.checks
        )
        assert {e.filename for e in case.evidence} >= {"chat.txt", "contract.txt"}
        evidence_by_id = {e.id: e for e in case.evidence}
        assert all(message.evidence_id in evidence_by_id for message in case.messages)
        assert all(
            message.text in (evidence_by_id[message.evidence_id].extracted_text or "")
            for message in case.messages
        )


def test_rendered_facts_are_source_backed_and_followups_are_later(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)
    for entry in manifest.cases:
        case = Case.model_validate_json((root / entry.files["case.json"]).read_bytes())
        sources = {evidence.filename: evidence.extracted_text or "" for evidence in case.evidence}
        assert case.listing is not None
        assert case.landlord is not None
        if case.landlord.company_number:
            assert case.landlord.company_number in sources["chat.txt"]

        contract = sources["contract.txt"]
        listing_text = sources["listing.txt"]
        for label, value in (
            ("Rent", case.listing.rent_pcm),
            ("Tenancy deposit", case.listing.deposit),
        ):
            assert value is not None
            amount = re.escape(str(value))
            assert re.search(rf"{label}: GBP {amount}(?: per calendar month)?\.", contract)
            assert re.search(rf"{label}: GBP {amount}(?: per calendar month)?\.", listing_text)

        if entry.follow_up_available_at is not None:
            assert entry.follow_up_available_at > case.created_at

        if "Completed" in entry.commitments.get("viewing_status", ""):
            assert "15 November 2026 at 16:00" not in sources["chat.txt"]


def test_generated_expectation_quotes_are_grounded_and_mutations_are_detected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)
    for entry in manifest.cases:
        sources = {
            source.id: source.extracted_text or ""
            for source in Case.model_validate_json(
                (root / entry.files["case.json"]).read_bytes()
            ).evidence
        }
        external = json.loads((root / entry.files["external.json"]).read_text(encoding="utf-8"))
        sources.update({record["id"]: record["snippet"] for record in external["records"]})
        for expectation in entry.expectations:
            assert expectation.evidence
            assert all(
                ref.quote.strip() and ref.quote in sources[ref.source]
                for ref in expectation.evidence
            )

    raw, _ = _manifest_path(root)
    raw["cases"][0]["expectations"][0]["evidence"][0]["quote"] = "fabricated evidence"
    _replace_manifest(root, raw)
    with pytest.raises(ValueError, match="Unsupported expectation evidence"):
        validate_dataset(root)


def test_validator_rejects_concluded_or_empty_checks(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)
    entry = manifest.cases[0]
    case_path = root / entry.files["case.json"]
    raw_case = json.loads(case_path.read_text(encoding="utf-8"))
    raw_case["checks"] = []
    case_path.write_text(
        json.dumps(raw_case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    raw_manifest, _ = _manifest_path(root)
    raw_manifest["cases"][0]["sha256"]["case.json"] = hashlib.sha256(
        case_path.read_bytes()
    ).hexdigest()
    _replace_manifest(root, raw_manifest)

    with pytest.raises(ValueError, match="all eight checks"):
        validate_dataset(root)


def test_validator_rejects_non_unverified_initial_check(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)
    entry = manifest.cases[0]
    case_path = root / entry.files["case.json"]
    raw_case = json.loads(case_path.read_text(encoding="utf-8"))
    raw_case["checks"][0]["state"] = "suspicious"
    case_path.write_text(
        json.dumps(raw_case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    raw_manifest, _ = _manifest_path(root)
    raw_manifest["cases"][0]["sha256"]["case.json"] = hashlib.sha256(
        case_path.read_bytes()
    ).hexdigest()
    _replace_manifest(root, raw_manifest)

    with pytest.raises(ValueError, match="must not initialise check conclusions"):
        validate_dataset(root)


def test_committed_corpus_accepts_new_optional_schema_defaults() -> None:
    root = Path(__file__).resolve().parents[3] / "fixtures" / "cases" / "synthetic"
    assert len(validate_dataset(root).cases) == 40


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("expected_truth", "genuine", "Unexpected fields"),
        (
            "chat",
            [{"role": "orchestrator", "text": "Already reviewed", "at": "2026-11-14T12:00:00Z"}],
            "fresh inputs only",
        ),
    ],
)
def test_optional_schema_defaults_do_not_allow_labels_or_previous_chat(
    tmp_path: Path, field: str, value: object, error: str
) -> None:
    root = tmp_path / "corpus"
    entry = _generated(root).cases[0]
    path = root / entry.files["case.json"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[field] = value
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest, _ = _manifest_path(root)
    manifest["cases"][0]["sha256"]["case.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _replace_manifest(root, manifest)
    with pytest.raises(ValueError, match=error):
        validate_dataset(root)


def test_contained_path_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    with pytest.raises(ValueError):
        contained_path(root, "../outside.txt")


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("The rent is GBP 850 per month.", "The rent is GBP 851 per month."),
        (
            "Please pay at https://example.test/pay/123.",
            "Please pay at https://example.test/pay/124.",
        ),
    ],
)
def test_paraphrase_cannot_change_literal_facts(original: str, replacement: str) -> None:
    base = Scenario.model_validate(
        {
            "key": "literal_guard",
            "family": "fake_agency",
            "variant": "concern",
            "truth": "scam",
            "messages": [
                {"sender": "student", "text": "Could you confirm the details?"},
                {"sender": "agent", "text": original},
            ],
            "expectations": [
                {
                    "check_id": "payment_safety",
                    "topic": "payment",
                    "stance": "concern",
                    "source": "chat",
                    "quote": original,
                    "explanation": "The wording requests payment.",
                }
            ],
            "allowed_outcomes": ["pending"],
        }
    )
    paraphrase = Paraphrase(
        base_key=base.key, rewrites=[Rewrite(message_index=1, text=replacement)]
    )
    with pytest.raises(ValueError, match="literal fact"):
        apply_paraphrase(base, paraphrase)


@pytest.mark.asyncio
async def test_external_search_distinguishes_not_found_unavailable_and_unmatched() -> None:
    search = FixtureSearch(
        {
            "schema_version": "1.0",
            "records": [
                {
                    "id": "e_name_check",
                    "key": "name_check",
                    "query_terms": ["Northbank Example Lettings"],
                    "query_alternatives": [["09123456"]],
                    "outcome": "not_found",
                    "title": "No matching record",
                    "url": "https://registry.example/search",
                    "snippet": "No matching record was returned.",
                },
                {
                    "id": "e_reviews",
                    "key": "reviews",
                    "query_terms": ["Northbank reviews"],
                    "outcome": "unavailable",
                    "title": "Reviews unavailable",
                    "url": "https://reviews.example/",
                    "snippet": "The service could not be reached.",
                },
            ],
            "http_routes": [],
            "unmatched_request": "error",
            "live_network_allowed": False,
        }
    )

    assert await search.search("Northbank Example Lettings") == []
    assert await search.search("look up company 09123456") == []
    with pytest.raises(FixtureUnavailableError):
        await search.search("Northbank reviews")
    with pytest.raises(MissingFixtureError):
        await search.search("unregistered query")


def test_malformed_external_http_route_is_rejected() -> None:
    bundle = {
        "schema_version": "1.0",
        "records": [],
        "http_routes": [
            {
                "method": "GET",
                "url": "https://fixture.invalid/declared",
                "status": "200",
                "json": {"title": "Declared result"},
            }
        ],
        "unmatched_request": "error",
        "live_network_allowed": False,
    }
    with pytest.raises(ValueError, match="status must be an integer"):
        mock_transport(bundle)


def test_generated_external_fixtures_represent_all_three_lookup_outcomes(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)
    outcomes: set[str] = set()
    for entry in manifest.cases:
        bundle = json.loads((root / entry.files["external.json"]).read_text(encoding="utf-8"))
        outcomes.update(record["outcome"] for record in bundle["records"])
        assert bundle["live_network_allowed"] is False
        assert bundle["unmatched_request"] == "error"
    assert {"found", "not_found", "unavailable"}.issubset(outcomes)


@pytest.mark.asyncio
async def test_external_http_mock_only_serves_declared_routes(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)
    entry = next(entry for entry in manifest.cases if entry.files.get("external.json"))
    bundle = json.loads((root / entry.files["external.json"]).read_text(encoding="utf-8"))
    route = {
        "method": "GET",
        "url": "https://fixture.invalid/declared",
        "status": 200,
        "json": {"title": "Declared result"},
    }
    transport = mock_transport({**bundle, "http_routes": [route]})
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(route["url"])
        assert response.status_code == 200
        assert response.json() == {"title": "Declared result"}
        with pytest.raises(MissingFixtureError):
            await client.get("https://not-fixtured.invalid/unexpected")


def test_same_seed_is_stable_and_alternate_seed_preserves_family_fact_pairing(
    tmp_path: Path,
) -> None:
    first_root, second_root = tmp_path / "seed_a", tmp_path / "seed_b"
    first = _generated(first_root, seed=20261114)
    second = _generated(second_root, seed=20261115)
    assert [entry.case_id for entry in first.cases] != [entry.case_id for entry in second.cases]
    assert len({entry.case_id for entry in second.cases}) == len(second.cases)

    grouped: dict[str, list[Any]] = defaultdict(list)
    for entry in second.cases:
        grouped[entry.family].append(entry)
    for family, entries in grouped.items():
        assert len({entry.group_id for entry in entries}) == 1
        assert entries[0].group_id == next(
            entry.group_id for entry in entries if entry.family == family
        )
        shared_facts = facts_for(20261115, family)
        for entry in entries:
            case = Case.model_validate_json((second_root / entry.files["case.json"]).read_bytes())
            assert case.listing is not None
            assert case.listing.address == shared_facts["address"]
            assert case.landlord is not None
            assert case.landlord.company_number in (None, shared_facts["company_number"])


def test_rerun_refuses_to_overwrite_locally_edited_corpus(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    manifest = _generated(root)
    entry = manifest.cases[0]
    source_path = root / entry.files["chat.txt"]
    edited = source_path.read_text(encoding="utf-8") + "LOCAL EDIT\n"
    source_path.write_text(edited, encoding="utf-8")

    with pytest.raises(ValueError):
        write_dataset(root, 20261114)
    assert source_path.read_text(encoding="utf-8") == edited
