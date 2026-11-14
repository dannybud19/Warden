"""Evaluate the synthetic corpus through CaseService: python -m eval.run --live."""

import argparse
import asyncio
import hashlib
import json
import logging
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.agents.companies_house.agent import CompaniesHouseAgent
from app.aggregators.scoring.scoring import load_weights, score
from app.contracts import AgentStatus, Case, CheckState
from app.core.agent import AgentContext, BaseAgent
from app.core.llm import LLMClient
from app.orchestrator.events import EventBus
from app.orchestrator.registry import AGENT_PAIRS
from app.orchestrator.service import CaseService
from app.storage.memory import InMemoryCaseRepo
from eval.synthetic.models import CaseEntry, Manifest
from eval.synthetic.storage import contained_path, validate_dataset
from eval.system_fixtures import build_external
from eval.system_runtime import EvaluationSettings, RecordedLLM

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "fixtures" / "cases" / "synthetic"


def save_json(path: Path, value: Any) -> None:
    """Replace a checkpoint atomically; an interrupted case never appears complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class CaptureLogs(logging.Handler):
    """Capture recoverable agent failures that an OK report would otherwise hide."""

    def __init__(self, secret: str) -> None:
        super().__init__(logging.WARNING)
        self.entries: list[dict[str, str]] = []
        self.secret = secret

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if self.secret:
            text = text.replace(self.secret, "[REDACTED]")
        self.entries.append({"level": record.levelname, "message": text[:3000]})


async def no_wait(seconds: float) -> None:
    """Mock services answer immediately; real network retry backoff is unnecessary here."""


def real_agents(case: Case) -> list[BaseAgent]:
    """Instantiate real classes directly, retaining production agent timeouts."""
    return [
        CompaniesHouseAgent(today=case.created_at.date(), sleep=no_wait),
        *(real() for real, _ in AGENT_PAIRS if real.name != "companies_house"),
    ]


async def evaluate_case(
    case: Case,
    entry: CaseEntry,
    bundle: dict[str, Any],
    settings: EvaluationSettings,
    llm: LLMClient,
) -> dict[str, Any]:
    """Run initial evidence once; do not inject expected results or scripted answers."""
    search, transport, audit = build_external(case, bundle)
    handler = CaptureLogs(settings.anthropic_api_key)
    logger = logging.Logger(f"evaluation.{case.case_id}", level=logging.WARNING)
    logger.addHandler(handler)
    logger.propagate = False
    repo = InMemoryCaseRepo()
    weights = load_weights()
    seed = case.model_copy(deep=True)
    seed.score_history = [score(seed.checks, weights).model_copy(update={"at": seed.created_at})]
    await repo.create(seed)
    started = time.perf_counter()
    fatal: str | None = None
    async with httpx.AsyncClient(transport=transport) as http:
        ctx = AgentContext(llm=llm, search=search, http=http, settings=settings, log=logger)
        service = CaseService(repo, EventBus(), real_agents(case), ctx, weights)
        try:
            result = await service.analyse(case.case_id)
        except Exception as exc:
            fatal = type(exc).__name__
            logger.exception("CaseService failed: %s", fatal)
            result = await repo.get(case.case_id) or seed
    degraded = fatal or any(
        report.status in {AgentStatus.ERROR, AgentStatus.NEEDS_INPUT}
        for report in result.reports.values()
    )
    return {
        "case_id": case.case_id,
        "family": entry.family,
        "variant": entry.variant,
        "truth": entry.truth,
        "label_review": entry.label_review,
        "run_status": "runner_error" if fatal else "degraded" if degraded else "complete",
        "runner_error": fatal,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "outcome": result.decision.verdict.value if result.decision else "pending",
        "allowed_outcome": (result.decision.verdict.value if result.decision else "pending")
        in entry.allowed_outcomes,
        "final_score": result.score_history[-1].score,
        "suspicious_checks": [
            c.id.value for c in result.checks if c.state == CheckState.SUSPICIOUS
        ],
        "cleared_checks": [c.id.value for c in result.checks if c.state == CheckState.CLEARED],
        "agent_statuses": {name: report.status.value for name, report in result.reports.items()},
        "hard_flags": [f.id for r in result.reports.values() for f in r.findings if f.hard_flag],
        "logs": handler.entries,
        "external_audit": audit,
        "result_case": result.model_dump(mode="json"),
        "follow_up_used": False,
    }


def summarise(results: list[dict[str, Any]], manifest: Manifest) -> dict[str, Any]:
    """Compute observable counts independently of optional semantic grading."""
    by_id = {r["case_id"]: r for r in results}
    truth_counts = Counter(r["truth"] for r in results)
    pairs = []
    for comparison in manifest.comparisons:
        left, right = by_id.get(comparison.baseline_case_id), by_id.get(comparison.variant_case_id)
        if not left or not right:
            continue
        pairs.append(
            {
                **comparison.model_dump(),
                "same_outcome": left["outcome"] == right["outcome"],
                "same_suspicious_checks": set(left["suspicious_checks"])
                == set(right["suspicious_checks"]),
                "same_cleared_checks": set(left["cleared_checks"]) == set(right["cleared_checks"]),
                "baseline_outcome": left["outcome"],
                "variant_outcome": right["outcome"],
            }
        )
    grade_counts: Counter[str] = Counter()
    for result in results:
        grade_counts.update(result.get("grading", {}).get("counts", {}))
    return {
        "cases": len(results),
        "truth_counts": dict(truth_counts),
        "outcomes": dict(Counter(r["outcome"] for r in results)),
        "run_statuses": dict(Counter(r["run_status"] for r in results)),
        "likely_scam_by_truth": {
            truth: {
                "count": sum(
                    r["truth"] == truth and r["outcome"] == "likely_scam" for r in results
                ),
                "total": truth_counts[truth],
            }
            for truth in ("scam", "genuine", "unknown")
        },
        "genuine_with_suspicious_checks": sum(
            r["truth"] == "genuine" and bool(r["suspicious_checks"]) for r in results
        ),
        "allowed_outcomes": sum(r["allowed_outcome"] for r in results),
        "grading_statuses": dict(
            Counter(r.get("grading", {}).get("status", "not_run") for r in results)
        ),
        "expectation_counts": dict(grade_counts),
        "external_requests": dict(
            Counter(
                request["classification"]
                for r in results
                for request in r["external_audit"]["requests"]
            )
        ),
        "comparisons": pairs,
        "interpretation": "Unreviewed synthetic development cases; no real-world accuracy claim.",
    }


def revision() -> str:
    """Record the tested checkout without fetching or altering it."""
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Run a pilot or resume the full corpus, preserving completed paid cases."""
    if not args.live:
        raise ValueError(
            "Use --live explicitly for this paid evaluation; tests use injected fakes."
        )
    manifest = validate_dataset(args.dataset)
    settings_options: dict[str, Any] = {"_env_file": str(args.env_file)}
    settings = EvaluationSettings(**settings_options).model_copy(
        update={
            "companies_house_api_key": "synthetic-fixture-only",
            "linkup_api_key": "synthetic-fixture-only",
        }
    )
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is missing from the selected local environment file.")
    selected = manifest.cases[: args.limit] if args.limit else manifest.cases
    signature = {
        "schema_version": "1.0",
        "git_revision": revision(),
        "dataset_sha256": hashlib.sha256((args.dataset / "manifest.json").read_bytes()).hexdigest(),
        "model": settings.llm_model,
        "agent_max_tokens": 2048,
        "rounds": "initial_only",
        "external_services": "controlled_fixtures",
        "label_review": "pending_agent_owner_review",
        "semantic_grading": not args.no_grade,
    }
    metadata_file = args.output / "metadata.json"
    if args.resume:
        previous = json.loads(metadata_file.read_text(encoding="utf-8"))
        if any(previous.get(k) != v for k, v in signature.items()):
            raise ValueError("Resume configuration or dataset changed; use a new result directory.")
    elif args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Result directory exists; use --resume or a new empty directory.")
    else:
        await asyncio.to_thread(
            save_json,
            metadata_file,
            {
                **signature,
                "started_at": datetime.now(UTC).isoformat(),
                "parallel_cases": args.parallel,
                "unimplemented_capabilities": ["video analysis", "LLM cross-checker"],
            },
        )
    ledger_lock = args.output / ".running.lock"
    lock_file = ledger_lock.open("x", encoding="utf-8")
    try:
        llm = RecordedLLM(settings, args.output / "usage.jsonl")
    except BaseException:
        lock_file.close()
        ledger_lock.unlink()
        raise
    semaphore = asyncio.Semaphore(args.parallel)

    async def one(entry: CaseEntry) -> None:
        async with semaphore:
            checkpoint = args.output / "cases" / f"{entry.case_id}.json"
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                if not args.retry_grading or saved.get("grading", {}).get("status") != "error":
                    return
            if llm.authentication_failed:
                return
            case = Case.model_validate_json(
                contained_path(args.dataset, entry.files["case.json"]).read_bytes()
            )
            bundle = json.loads(
                contained_path(args.dataset, entry.files["external.json"]).read_bytes()
            )
            raw_path = args.output / "raw" / f"{entry.case_id}.json"
            if raw_path.exists():
                result = json.loads(raw_path.read_text(encoding="utf-8"))
            else:
                with llm.scope(case_id=entry.case_id, stage="agents"):
                    result = await evaluate_case(case, entry, bundle, settings, llm)
                # A judge failure must not discard paid agent work.
                await asyncio.to_thread(save_json, raw_path, result)
            if checkpoint.exists():
                prior = json.loads(checkpoint.read_text(encoding="utf-8"))
                result["prior_grading_attempts"] = [
                    *prior.get("prior_grading_attempts", []),
                    prior.get("grading", {}),
                ]
            if not args.no_grade and not llm.authentication_failed:
                from eval.system_grading import grade_case

                grading_bundle = {
                    **bundle,
                    "http_routes": [
                        *bundle["http_routes"],
                        *(
                            {
                                "method": request["method"],
                                "url": request["request"],
                                "status": request["status"],
                                "json": request["response_body"],
                            }
                            for request in result["external_audit"]["requests"]
                            if request["transport"] == "http" and "response_body" in request
                        ),
                    ],
                }
                with llm.scope(case_id=entry.case_id, stage="grading", max_tokens=8192):
                    result["grading"] = await grade_case(
                        case, Case.model_validate(result["result_case"]), entry, grading_bundle, llm
                    )
            result["usage"] = llm.usage_summary(entry.case_id)
            await asyncio.to_thread(save_json, checkpoint, result)
            sys.stdout.write(
                json.dumps(
                    {
                        "case": entry.case_id,
                        "family": entry.family,
                        "variant": entry.variant,
                        "outcome": result["outcome"],
                        "status": result["run_status"],
                        "cost_usd": result["usage"]["cost_usd"],
                    }
                )
                + "\n"
            )
            sys.stdout.flush()

    try:
        await asyncio.gather(*(one(entry) for entry in selected))
        results = [
            json.loads(path.read_text(encoding="utf-8"))
            for entry in manifest.cases
            if (path := args.output / "cases" / f"{entry.case_id}.json").exists()
        ]
        summary = summarise(results, manifest)
        summary["usage"] = llm.usage_summary()
        summary["finished_at"] = datetime.now(UTC).isoformat()
        summary["authentication_failed"] = llm.authentication_failed
        await asyncio.to_thread(save_json, args.output / "summary.json", summary)
        return summary
    finally:
        await llm.close()
        lock_file.close()
        ledger_lock.unlink()


def main() -> int:
    """Require explicit live mode and write progress plus a resumable results directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--retry-grading",
        action="store_true",
        help="With --resume, retry failed graders without rerunning agents",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--parallel", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--no-grade", action="store_true")
    args = parser.parse_args()
    if args.retry_grading and (not args.resume or args.no_grade):
        parser.error("--retry-grading requires --resume and enabled grading")
    if args.limit is not None and not 1 <= args.limit <= 40:
        parser.error("--limit must be between 1 and 40")
    try:
        summary = asyncio.run(run(args))
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"Evaluation stopped: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 1 if summary["authentication_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
