"""Standalone contract review and paired-case evaluation: python -m eval.contract_checker."""

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.agents.contract_checker.models import ContractReview, ReviewContext
from app.agents.contract_checker.review import review_contract
from app.core.agent import AgentContext
from app.core.factory import build_context
from app.core.settings import Settings
from eval.contract_metering import MeteredAnthropicLLM, UsageLedger

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "backend" / ".uploads" / "contract_checker" / "usage.json"
DEFAULT_PAIRS = ROOT / "fixtures" / "cases" / "contract_checker" / "pairs.json"


def read_context(path: Path | None) -> ReviewContext:
    """Read caller-supplied facts, leaving applicability unknown when no context is supplied."""
    if path:
        return ReviewContext.model_validate_json(path.read_text(encoding="utf-8"))
    return ReviewContext(assessment_date=datetime.now(UTC).date())


async def evaluate_pairs(path: Path, ctx: AgentContext) -> dict[str, Any]:
    """Run labelled controlled changes; keep incomplete reviews visible in evaluation output."""
    manifest = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
    context = ReviewContext.model_validate(manifest["context"])
    results: list[dict[str, Any]] = []
    reviews: dict[str, ContractReview] = {}
    for example in manifest["cases"]:
        file = path.parent / example["file"]
        data = await asyncio.to_thread(file.read_bytes)
        review = await review_contract(data, file.name, context, ctx)
        ctx.log.info("contract pair %s reviewed: %s", example["id"], review.status)
        reviews[example["id"]] = review
        expected = set(example["expected_concerns"])
        actual = {
            i.rule_id.value
            for i in review.issues
            if i.status in {"confirmed", "conditional"} and i.importance > 0
        }
        results.append(
            {
                "id": example["id"],
                "pair": example["pair"],
                "expected": sorted(expected),
                "observed": sorted(actual),
                "missed": sorted(expected - actual),
                "unexpected": sorted(actual - expected),
                "status": review.status,
                "latency_ms": review.duration_ms,
                "warnings": review.warnings,
                "review": review.model_dump(mode="json"),
            }
        )
    return {
        "cases": len(results),
        "complete_reviews": sum(r["status"] == "complete" for r in results),
        "missed_expected_rule_types": sum(len(r["missed"]) for r in results),
        "unexpected_rule_types": sum(len(r["unexpected"]) for r in results),
        "results": results,
        "interpretation": "Synthetic pairs only; not real-world scam-detection accuracy.",
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Build an injected context; paid requests require explicit --live and a local key."""
    settings = Settings()
    # Avoid opening an unused live SDK client. Tests and default CLI runs never use the network.
    offline_settings = settings.model_copy(update={"anthropic_api_key": "", "linkup_api_key": ""})
    ctx = build_context(offline_settings)
    live: MeteredAnthropicLLM | None = None
    ledger: UsageLedger | None = None
    lock_file = None
    lock_path = args.ledger.with_suffix(args.ledger.suffix + ".lock")
    try:
        if args.live:
            if not settings.anthropic_api_key:
                raise ValueError("Set ANTHROPIC_API_KEY in the local .env before using --live.")
            ledger = UsageLedger(args.ledger, Decimal(args.budget_gbp))
            await asyncio.to_thread(lock_path.parent.mkdir, parents=True, exist_ok=True)
            try:
                lock_file = await asyncio.to_thread(lock_path.open, "x", encoding="utf-8")
            except FileExistsError as exc:
                raise ValueError(
                    "An evaluation holds the budget lock; check it before retrying."
                ) from exc
            ledger = UsageLedger(args.ledger, Decimal(args.budget_gbp))
            live = MeteredAnthropicLLM(settings, ledger)
            ctx = replace(ctx, llm=live, settings=settings)
        if args.command == "review":
            data = await asyncio.to_thread(args.file.read_bytes)
            review = await review_contract(data, args.file.name, read_context(args.context), ctx)
            result: dict[str, Any] = {"review": review.model_dump(mode="json")}
        else:
            result = await evaluate_pairs(args.manifest, ctx)
        result["mode"] = "live" if args.live else "offline_rules_only"
        result["usage"] = (
            ledger.summary()
            if ledger
            else {
                "paid_requests": 0,
                "measured_cost_usd": "0",
                "note": "No live API evaluation performed.",
            }
        )
        return result
    finally:
        if live:
            await live.close()
        await ctx.http.aclose()
        if lock_file:
            lock_file.close()
            await asyncio.to_thread(lock_path.unlink)


def main() -> int:
    """Write useful JSON, keeping logs and errors off standard output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Use the configured paid API with metering"
    )
    parser.add_argument(
        "--budget-gbp", default="5", help="Total budget, maximum 5; ledger persists"
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="Review a text-based PDF or UTF-8 text file")
    review.add_argument("file", type=Path)
    review.add_argument("--context", type=Path)
    evaluate = commands.add_parser("evaluate", help="Evaluate the controlled paired contracts")
    evaluate.add_argument("--manifest", type=Path, default=DEFAULT_PAIRS)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
        output = json.dumps(result, indent=2, ensure_ascii=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            sys.stdout.write(output + "\n")
        return 0
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"Contract review could not run: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
