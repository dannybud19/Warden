"""Offline safety and accounting tests for the whole-system evaluation runner."""

import asyncio
import json
import logging
from argparse import Namespace
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from app.agents.companies_house.agent import CompaniesHouseAgent
from app.agents.message_checker.agent import MessageCheckerAgent
from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Category,
    CheckId,
    EvidenceRef,
    Finding,
    Landlord,
    Severity,
)
from app.core.agent import AgentContext
from app.core.llm import AnthropicLLM, FakeLLM
from app.orchestrator import checks, conversation, payment_confirmation
from eval import run as evaluation
from eval.contract_metering import PRICES, usage_cost
from eval.synthetic.engine import build_dataset
from eval.synthetic.external import FixtureUnavailableError
from eval.synthetic.models import CaseEntry, Manifest
from eval.system_fixtures import build_external
from eval.system_grading import grade_case
from eval.system_runtime import EvaluationSettings, RecordedLLM


def _settings(**overrides: Any) -> EvaluationSettings:
    """Construct settings without loading a developer's local environment file."""
    options: dict[str, Any] = {"_env_file": None, **overrides}
    return EvaluationSettings(**options)


def _corpus_case(
    *, family: str = "fake_agency", variant: str = "concern"
) -> tuple[Case, CaseEntry, dict[str, Any]]:
    artifacts = build_dataset()
    manifest = Manifest.model_validate_json(artifacts["manifest.json"])
    entry = next(
        item for item in manifest.cases if item.family == family and item.variant == variant
    )
    case = Case.model_validate_json(artifacts[entry.files["case.json"]])
    bundle = json.loads(artifacts[entry.files["external.json"]])
    return case, entry, bundle


def _runtime_case(*, hard_flag: bool = False) -> tuple[Case, CaseEntry, dict[str, Any]]:
    case, entry, bundle = _corpus_case()
    if hard_flag:
        source = next(item for item in case.evidence if item.filename == "chat.txt")
        quote = (source.extracted_text or "split into lines").splitlines()[0]
        finding = Finding(
            id="test_agent:pre_viewing_payment",
            agent="test_agent",
            check_id=CheckId.PAYMENT_SAFETY,
            title="Payment demanded before viewing",
            detail="A fictional test report records the stated payment condition.",
            category=Category.PAYMENT,
            severity=Severity.CRITICAL,
            confidence=0.99,
            evidence=[EvidenceRef(evidence_id=source.id, quote=quote)],
            hard_flag=True,
        )
        case.reports["test_agent"] = AgentReport(
            agent="test_agent",
            version="test",
            status=AgentStatus.OK,
            input_hash="test",
            findings=[finding],
        )
    return case, entry, bundle


def _grade_payload(entry: CaseEntry, *, omit_last_expectation: bool = False) -> str:
    expectations = [
        {
            "expectation_index": i,
            "judgement": "indeterminate",
            "explanation": "The output lacks enough evidence for a semantic judgement.",
            "finding_ids": [],
            "action_ids": [],
            "agent_questions": [],
        }
        for i in range(len(entry.expectations) - int(omit_last_expectation))
    ]
    forbidden = [
        {
            "forbidden_index": i,
            "judgement": "absent",
            "output_quote": None,
            "explanation": "No output asserts this prohibited claim.",
            "finding_ids": [],
            "action_ids": [],
            "agent_questions": [],
        }
        for i in range(len(entry.forbidden_assertions))
    ]
    return json.dumps(
        {
            "expectations": expectations,
            "forbidden_assertions": forbidden,
            "unsupported_claims": [],
            "grounding_issues": [],
            "reviewer_note": None,
        }
    )


async def _no_wait(_: float) -> None:
    return None


def test_missing_search_and_http_routes_are_audited_without_live_fallback() -> None:
    case, _, bundle = _corpus_case()
    search, transport, audit = build_external(case, bundle)

    async def exercise() -> None:
        with pytest.raises(FixtureUnavailableError, match="missing_fixture"):
            await search.search("unlisted evaluation query")
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get("https://outside-fixture.invalid/path")
            assert response.status_code == 503

    asyncio.run(exercise())
    assert audit["live_network_allowed"] is False
    assert [row["classification"] for row in audit["requests"]] == [
        "missing_fixture",
        "missing_fixture",
    ]
    assert all(row["fixture_ids"] == [] for row in audit["requests"])


async def test_companies_house_search_profile_and_dissolved_flag_use_declared_sources() -> None:
    case = Case(
        case_id="c_registry_dissolved",
        created_at=datetime(2026, 11, 14, 12, tzinfo=UTC),
        landlord=Landlord(name="Mira Vale", company_name="Northbank Example Lettings Ltd"),
    )
    bundle = {
        "schema_version": "1.0",
        "records": [
            {
                "id": "external_dissolved_company",
                "key": "company_register",
                "query_terms": ["Northbank Example Lettings Ltd"],
                "query_alternatives": [["09123456"]],
                "outcome": "found",
                "title": "Fictional company register entry",
                "url": "https://register.example/company/09123456",
                "snippet": ("Company 09123456: Northbank Example Lettings Ltd. Status: dissolved."),
                "company_status": "dissolved",
            }
        ],
        "http_routes": [],
        "unmatched_request": "error",
        "live_network_allowed": False,
    }
    search, transport, audit = build_external(case, bundle)
    settings = _settings(
        companies_house_api_key="synthetic-fixture-only",
        anthropic_api_key="",
        linkup_api_key="",
    )
    log = logging.Logger("companies-house-test", level=logging.WARNING)
    async with httpx.AsyncClient(transport=transport) as http:
        context = AgentContext(llm=FakeLLM(), search=search, http=http, settings=settings, log=log)
        report = await CompaniesHouseAgent(
            today=case.created_at.date(), sleep=_no_wait, deadline_s=2
        ).run(case, context)

    assert report.status == AgentStatus.OK
    hard = [finding for finding in report.findings if finding.hard_flag]
    assert len(hard) == 1
    assert hard[0].supports == "suspicious"
    assert hard[0].evidence
    assert any("dissolved" in (reference.quote or "").lower() for reference in hard[0].evidence)
    assert any("/search/companies" in row["request"] for row in audit["requests"])
    assert any("/company/09123456" in row["request"] for row in audit["requests"])
    assert [row["classification"] for row in audit["requests"][:2]] == [
        "fixture_found",
        "fixture_found",
    ]
    assert audit["live_network_allowed"] is False


async def test_case_service_distinguishes_open_pending_from_hard_flag_verdict(monkeypatch) -> None:
    monkeypatch.setattr(evaluation, "real_agents", lambda _: [])
    settings = _settings()
    open_case, entry, bundle = _runtime_case()
    llm = FakeLLM()
    pending = await evaluation.evaluate_case(open_case, entry, bundle, settings, llm)

    decided_case, decided_entry, decided_bundle = _runtime_case(hard_flag=True)
    decided_case.checks = checks.update(decided_case, decided_case.reports["test_agent"].findings)
    decided_case.actions = payment_confirmation.questions(decided_case)
    decided_case.actions = conversation.parse(
        decided_case, "yes", [], action_id=decided_case.actions[0].id
    )
    decided = await evaluation.evaluate_case(
        decided_case, decided_entry, decided_bundle, settings, FakeLLM()
    )

    assert pending["outcome"] == "pending"
    assert pending["result_case"]["status"] == "open"
    assert pending["result_case"]["decision"] is None
    assert pending["result_case"]["actions"]
    assert decided["outcome"] == "likely_scam"
    assert decided["result_case"]["status"] == "decided"
    assert decided["result_case"]["decision"]["verdict"] == "likely_scam"


async def test_agent_prompt_inputs_do_not_contain_eval_labels_or_external_manifest(
    monkeypatch,
) -> None:
    monkeypatch.setattr(evaluation, "real_agents", lambda _: [MessageCheckerAgent()])
    case, entry, bundle = _runtime_case()
    llm = FakeLLM()
    await evaluation.evaluate_case(case, entry, bundle, _settings(), llm)

    prompt_text = "\n".join(
        call.get("system", "") + "\n" + call.get("user", "") for call in llm.calls
    )
    assert llm.calls
    for secret in (
        '"truth"',
        '"expectations"',
        '"allowed_outcomes"',
        '"forbidden_assertions"',
        '"label_review"',
        entry.expectations[0].explanation,
        json.dumps(bundle, ensure_ascii=False),
    ):
        assert secret not in prompt_text


async def test_evaluation_runs_the_llm_crosschecker_through_case_service(monkeypatch) -> None:
    monkeypatch.setattr(evaluation, "real_agents", lambda _: [])
    case, entry, bundle = _runtime_case()
    case.reports = {
        name: AgentReport(agent=name, version="test", status=AgentStatus.OK, input_hash="test")
        for name in ("message_checker", "contract_checker")
    }
    llm = FakeLLM()
    result = await evaluation.evaluate_case(case, entry, bundle, _settings(), llm)
    assert any("You are the Cross-checker for Warden" in c.get("system", "") for c in llm.calls)
    report = result["result_case"]["reports"]["crosscheck"]
    assert report["status"] == "ok"
    assert not any(f["id"] == "crosscheck:not-run" for f in report["findings"])


def test_summary_keeps_unknown_out_of_binary_truth_denominators_and_counts_pairs() -> None:
    artifacts = build_dataset()
    manifest = Manifest.model_validate_json(artifacts["manifest.json"])
    results = [
        {
            "case_id": entry.case_id,
            "truth": entry.truth,
            "outcome": "pending",
            "run_status": "complete",
            "allowed_outcome": True,
            "suspicious_checks": [],
            "cleared_checks": [],
            "grading": {"status": "not_run", "counts": {}},
            "follow_up_used": False,
            "external_audit": {"requests": []},
        }
        for entry in manifest.cases
    ]
    wording_pair = next(
        comparison for comparison in manifest.comparisons if comparison.kind == "wording_only"
    )
    next(result for result in results if result["case_id"] == wording_pair.variant_case_id)[
        "outcome"
    ] = "likely_scam"
    summary = evaluation.summarise(results, manifest)

    expected = Counter(entry.truth for entry in manifest.cases)
    assert summary["truth_counts"] == dict(expected)
    binary_denominator = (
        summary["likely_scam_by_truth"]["scam"]["total"]
        + summary["likely_scam_by_truth"]["genuine"]["total"]
    )
    assert binary_denominator == expected["scam"] + expected["genuine"]
    assert summary["likely_scam_by_truth"]["unknown"]["total"] == expected["unknown"]
    assert len(summary["comparisons"]) == len(manifest.comparisons) == 24
    assert Counter(row["kind"] for row in summary["comparisons"]) == Counter(
        {"meaningful_change": 16, "wording_only": 8}
    )
    reported_pair = next(
        row
        for row in summary["comparisons"]
        if row["variant_case_id"] == wording_pair.variant_case_id
    )
    assert reported_pair["same_outcome"] is False


def _recorded_llm(tmp_path: Path, provider: Any) -> RecordedLLM:
    """Build the real meter around a mocked SDK endpoint, without SDK/network creation."""
    llm = object.__new__(RecordedLLM)
    llm._client = cast(Any, SimpleNamespace(messages=provider))
    llm._model = "claude-sonnet-5-5"
    llm.journal = tmp_path / "usage.jsonl"
    llm.events = []
    llm._journal_lock = asyncio.Lock()
    llm._scope = ContextVar("test_evaluation_scope", default=None)
    llm.authentication_failed = False
    return llm


async def test_recorded_llm_journals_scoped_usage_and_unlimited_success(tmp_path: Path) -> None:
    requested_caps: list[int] = []

    class Provider:
        calls = 0

        async def create(self, **options: Any) -> Any:
            requested_caps.append(options["max_tokens"])
            self.calls += 1
            return SimpleNamespace(
                usage=SimpleNamespace(
                    model_dump=lambda: {"input_tokens": 1000, "output_tokens": 500}
                ),
                model="claude-sonnet-5-5",
                id=f"req_{self.calls}",
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="ready")],
            )

    provider = Provider()
    llm = _recorded_llm(tmp_path, provider)
    with llm.scope(case_id="case_a", stage="agents", max_tokens=777):
        assert await llm.complete("system", "input") == "ready"
        assert await llm.complete("system", "input") == "ready"

    events = [json.loads(line) for line in llm.journal.read_text(encoding="utf-8").splitlines()]
    assert provider.calls == 2
    assert [event["event"] for event in events] == ["started", "completed"] * 2
    assert all(event["case_id"] == "case_a" for event in events)
    assert all(event["stage"] == "agents" and event["max_tokens"] == 777 for event in events)
    usage = llm.usage_summary("case_a")
    expected_cost = sum(
        (
            usage_cost(
                {"input_tokens": 1000, "output_tokens": 500},
                PRICES["claude-sonnet-5-5"],
            )
            for _ in range(2)
        ),
        start=0,
    )
    assert usage["completed_requests"] == 2
    assert usage["cost_usd"] == str(expected_cost)
    assert usage["budget_policy"].startswith("User removed GBP 5 limit")
    assert await llm.complete("system", "input") == "ready"
    assert requested_caps == [777, 777, AnthropicLLM.MAX_TOKENS]


async def test_recorded_llm_journals_provider_failure_with_unknown_billing(tmp_path: Path) -> None:
    class Provider:
        class ProviderError(Exception):
            status_code = 503

        async def create(self, **_: Any) -> Any:
            raise self.ProviderError("temporary provider error")

    llm = _recorded_llm(tmp_path, Provider())
    with llm.scope(case_id="case_b", stage="grading"), pytest.raises(Provider.ProviderError):
        await llm.complete("system", "input")

    event = json.loads(llm.journal.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event"] == "failed"
    assert event["case_id"] == "case_b" and event["stage"] == "grading"
    assert event["http_status"] == 503 and event["billing_unknown"] is True
    assert llm.usage_summary("case_b")["unknown_billing_requests"] == 1


async def test_grader_requires_complete_expectation_reference_coverage() -> None:
    case, entry, bundle = _runtime_case()
    valid = FakeLLM({"You are a posthoc evaluation judge": _grade_payload(entry)})
    judged = await grade_case(case, case, entry, bundle, valid)
    assert judged["status"] == "ok"
    assert len(judged["expectations"]) == len(entry.expectations)

    incomplete = FakeLLM(
        {"You are a posthoc evaluation judge": _grade_payload(entry, omit_last_expectation=True)}
    )
    rejected = await grade_case(case, case, entry, bundle, incomplete)
    assert rejected["status"] == "error"
    assert "Expectations requires each index" in rejected["error"]


async def test_grader_rejects_met_concern_without_supporting_finding() -> None:
    case, entry, bundle = _runtime_case()
    rows = json.loads(_grade_payload(entry))
    concern_index = next(i for i, item in enumerate(entry.expectations) if item.stance == "concern")
    rows["expectations"][concern_index]["judgement"] = "met"
    raw = json.dumps(rows)
    rejected = await grade_case(
        case, case, entry, bundle, FakeLLM({"You are a posthoc evaluation judge": raw})
    )

    assert rejected["status"] == "error"
    assert "met concern requires an actual finding reference" in rejected["error"]


async def test_grader_repairs_once_and_retains_invalid_attempt() -> None:
    case, entry, bundle = _runtime_case()
    llm = FakeLLM(
        {
            '"specific_validation_error":': _grade_payload(entry),
            "You are a posthoc evaluation judge": _grade_payload(entry, omit_last_expectation=True),
        }
    )
    result = await grade_case(case, case, entry, bundle, llm)
    assert result["status"] == "ok"
    assert len(llm.calls) == 2
    assert result["correction_attempted"] is True
    assert result["grading_attempts"][0]["validated"] is False
    assert result["grading_attempts"][0]["validation_error"]
    assert result["grading_attempts"][0]["unvalidated_judgement"]
    assert result["grading_attempts"][1]["validated"] is True


async def test_client_initialisation_failure_releases_run_lock(monkeypatch, tmp_path: Path) -> None:
    from eval.synthetic.storage import write_dataset

    dataset = tmp_path / "dataset"
    write_dataset(dataset)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=test-key\n", encoding="utf-8")

    def unavailable_client(*_: Any) -> None:
        raise ValueError("client initialisation failed")

    monkeypatch.setattr(evaluation, "RecordedLLM", unavailable_client)
    monkeypatch.setattr(evaluation, "revision", lambda: "offline-test-revision")
    args = Namespace(
        live=True,
        dataset=dataset,
        env_file=env_file,
        output=tmp_path / "output",
        resume=False,
        limit=1,
        parallel=1,
        no_grade=True,
        retry_grading=False,
    )
    with pytest.raises(ValueError, match="client initialisation failed"):
        await evaluation.run(args)
    assert not (args.output / ".running.lock").exists()


async def test_runner_resume_skips_checkpoint_without_live_calls(
    monkeypatch, tmp_path: Path
) -> None:
    dataset = tmp_path / "dataset"
    from eval.synthetic.storage import write_dataset

    manifest = write_dataset(dataset)
    output = tmp_path / "results"
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=test-key\n", encoding="utf-8")
    calls = 0

    class FakeRecordedLLM:
        authentication_failed = False

        def __init__(self, settings: Any, journal: Path) -> None:
            self.journal = journal

        @contextmanager
        def scope(self, **_: Any):
            yield

        def usage_summary(self, _: str | None = None) -> dict[str, Any]:
            return {"attempts": 0, "cost_usd": "0"}

        async def close(self) -> None:
            return None

    async def fake_evaluate_case(case: Case, entry: CaseEntry, *_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "case_id": entry.case_id,
            "family": entry.family,
            "variant": entry.variant,
            "truth": entry.truth,
            "label_review": entry.label_review,
            "run_status": "complete",
            "runner_error": None,
            "latency_ms": 0,
            "outcome": "pending",
            "allowed_outcome": True,
            "final_score": 100.0,
            "suspicious_checks": [],
            "cleared_checks": [],
            "agent_statuses": {},
            "hard_flags": [],
            "logs": [],
            "external_audit": {"requests": []},
            "result_case": case.model_dump(mode="json"),
            "follow_up_used": False,
        }

    monkeypatch.setattr(evaluation, "RecordedLLM", FakeRecordedLLM)
    monkeypatch.setattr(evaluation, "evaluate_case", fake_evaluate_case)
    monkeypatch.setattr(evaluation, "revision", lambda: "offline-test-revision")
    args = Namespace(
        live=True,
        dataset=dataset,
        env_file=env_file,
        output=output,
        resume=False,
        limit=1,
        parallel=1,
        no_grade=True,
        retry_grading=False,
    )
    first = await evaluation.run(args)
    assert calls == 1 and first["cases"] == 1
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["agent_max_tokens"] == AnthropicLLM.MAX_TOKENS
    assert "LLM cross-checker" in metadata["pipeline"]
    assert "LLM cross-checker" not in metadata["unimplemented_capabilities"]
    assert metadata["not_exercised"]

    args.resume = True
    resumed = await evaluation.run(args)
    assert calls == 1 and resumed["cases"] == 1
    assert (output / "cases" / f"{manifest.cases[0].case_id}.json").exists()
