"""The standalone extraction, rule checking and challenge pipeline."""

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from app.agents.contract_checker.documents import DocumentError, cite, cite_all, extract_document
from app.agents.contract_checker.models import (
    ChallengeResponse,
    ContractReview,
    Document,
    Extraction,
    Issue,
    Question,
    ReviewContext,
    RuleId,
)
from app.agents.contract_checker.rulebook import load_rulebook
from app.agents.contract_checker.rules import (
    check_advance_amounts,
    check_amounts,
    check_candidates,
    explicit_candidates,
    extract_money,
    question_for,
    validate_money,
)
from app.core.agent import AgentContext


def _prompt(name: str) -> str:
    return (Path(__file__).parent / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def _deduplicate(issues: list[Issue]) -> list[Issue]:
    unique: dict[tuple[str, tuple[str, ...]], Issue] = {}
    for issue in issues:
        key = (issue.rule_id, tuple(sorted({ref.segment_id for ref in issue.evidence})))
        if key not in unique:
            unique[key] = issue
    return sorted(unique.values(), key=lambda issue: (-issue.importance, issue.id))


def apply_challenge(
    document: Document, issues: list[Issue], response: ChallengeResponse
) -> tuple[list[Issue], list[str]]:
    """Apply supported challenges without letting a model vote away arithmetic or missing facts."""
    warnings: list[str] = []
    decisions = {decision.issue_id: decision for decision in response.decisions}
    duplicates = len(decisions) != len(response.decisions)
    if duplicates or set(decisions) != {issue.id for issue in issues}:
        warnings.append("Challenge response did not cover every issue exactly once.")
    result: list[Issue] = []
    for issue in issues:
        decision = decisions.get(issue.id)
        if decision is None or duplicates:
            result.append(
                issue.model_copy(
                    update={
                        "status": "conditional",
                        "supports": "suspicious",
                        "confidence": min(issue.confidence, 0.5),
                        "uncertainty": [
                            *issue.uncertainty,
                            "This issue did not receive a valid second review.",
                        ],
                        "question": question_for(issue.rule_id),
                    }
                )
            )
            continue
        counter = cite_all(document, decision.counter_evidence) if decision.counter_evidence else []
        if counter is None:
            warnings.append(f"Rejected unsupported counter-evidence for {issue.id}.")
            counter = []
        update: dict[str, Any] = {"review_reason": decision.reason, "counter_evidence": counter}
        if decision.decision == "conditional":
            update.update(
                status="conditional",
                supports="suspicious",
                confidence=min(issue.confidence, 0.5),
                uncertainty=[*issue.uncertainty, decision.reason],
                question=question_for(issue.rule_id),
            )
        elif decision.decision == "dismiss":
            reassurance_only = bool(counter) and all(
                re.search(
                    r"don.t worry|do not worry|standard contract|"
                    r"everything is fine|nothing to worry",
                    ref.quote,
                    re.I,
                )
                for ref in counter
            )
            if not counter or reassurance_only:
                warnings.append(f"Kept {issue.id}: dismissal lacked substantive counter-evidence.")
                update["review_reason"] = (
                    "Dismissal rejected: no substantive quoted counter-evidence."
                )
            elif issue.calculation:
                update.update(
                    status="conditional",
                    supports="suspicious",
                    confidence=0.5,
                    uncertainty=[*issue.uncertainty, decision.reason],
                    question=question_for(issue.rule_id),
                )
            else:
                update.update(status="dismissed", supports="cleared", importance=0, question=None)
        result.append(issue.model_copy(update=update))
    return result, warnings


def _context_questions(context: ReviewContext) -> list[Question]:
    if context.jurisdiction == "unknown" or context.tenancy_type == "unknown":
        return [
            Question(
                id="contract_checker:question:scope",
                rule_id=RuleId.STRUCTURE,
                text="Is this a private tenancy in England with the landlord living elsewhere?",
                why="Legal applicability differs for lodgers, halls and other jurisdictions.",
                resolves_when="The jurisdiction and tenancy type are supplied as explicit context.",
            )
        ]
    return []


async def review_document(
    document: Document, context: ReviewContext, ctx: AgentContext
) -> ContractReview:
    """Review an extracted contract through injected clients and a bounded two-pass workflow."""
    started = time.perf_counter()
    book = load_rulebook()
    review = ContractReview(
        status="partial",
        context=context,
        document_id=document.id,
        document_sha256=document.sha256,
        warnings=list(document.warnings),
        rulebook_version=book.version,
    )
    if context.jurisdiction not in {"england", "unknown"} or context.tenancy_type not in {
        "ordinary_private",
        "unknown",
    }:
        review.status = "unsupported"
        review.warnings.append("This version reviews ordinary private tenancies in England only.")
        return review
    payload = {
        "contract": document.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
        "rulebook": book.model_dump(mode="json"),
    }
    extraction = Extraction()
    try:
        extraction = await ctx.llm.complete_json(
            _prompt("extract"), json.dumps(payload, ensure_ascii=False), Extraction
        )
        semantic_rules = set(RuleId) - {RuleId.DEPOSIT, RuleId.HOLDING}
        review.extraction_completed = semantic_rules.issubset(extraction.reviewed_rules)
        review.reviewed_rules = sorted(set(extraction.reviewed_rules) & semantic_rules, key=str)
        if not review.extraction_completed:
            review.warnings.append(
                "LLM extraction did not establish coverage of all selected checks."
            )
    except Exception as exc:
        review.warnings.append(f"Structured extraction unavailable ({type(exc).__name__}).")
        ctx.log.warning("contract extraction unavailable: %s", type(exc).__name__)
    terms, rejected_money = validate_money(document, extract_money(document) + extraction.money)
    review.money = terms
    deterministic = check_amounts(document, terms, context, book)
    review.reviewed_rules = sorted(
        set(review.reviewed_rules) | {RuleId.DEPOSIT, RuleId.HOLDING}, key=str
    )
    deterministic += check_advance_amounts(document, terms, context, book)
    explicit, rejected_explicit = check_candidates(
        document, explicit_candidates(document), context, book, origin="rule"
    )
    semantic, rejected_candidates = check_candidates(document, extraction.candidates, context, book)
    rejected = rejected_money + rejected_explicit + rejected_candidates
    for fact in extraction.facts:
        if cite(document, fact.evidence) and fact.value in fact.evidence.quote:
            review.facts.append(fact)
        else:
            rejected += 1
    if rejected:
        review.warnings.append(f"Rejected {rejected} unsupported or out-of-scope extracted items.")
    review.issues = _deduplicate(deterministic + explicit + semantic)
    try:
        challenge_payload = {
            **payload,
            "issues": [i.model_dump(mode="json") for i in review.issues],
        }
        response = await ctx.llm.complete_json(
            _prompt("challenge"),
            json.dumps(challenge_payload, ensure_ascii=False),
            ChallengeResponse,
        )
        review.issues, challenge_warnings = apply_challenge(document, review.issues, response)
        review.warnings.extend(challenge_warnings)
        review.challenge_completed = not challenge_warnings
    except Exception as exc:
        review.warnings.append(f"Challenge review unavailable ({type(exc).__name__}).")
        ctx.log.warning("contract challenge unavailable: %s", type(exc).__name__)
    if not review.extraction_completed or not review.challenge_completed or rejected:
        for issue in review.issues:
            if issue.status == "cleared" or (
                issue.status == "confirmed" and not review.challenge_completed
            ):
                issue.status = "conditional"
                issue.supports = "suspicious"
                issue.uncertainty.append(
                    "Review coverage is incomplete; this conclusion needs review."
                )
                issue.question = question_for(issue.rule_id)
                issue.confidence = min(issue.confidence, 0.5)
    review.status = (
        "complete"
        if review.extraction_completed and review.challenge_completed and not rejected
        else "partial"
    )
    questions = _context_questions(context) + [i.question for i in review.issues if i.question]
    review.questions = list({q.id: q for q in questions}.values())
    review.duration_ms = int((time.perf_counter() - started) * 1000)
    return review


async def review_contract(
    data: bytes,
    filename: str,
    context: ReviewContext,
    ctx: AgentContext,
    *,
    document_id: str = "contract",
) -> ContractReview:
    """Standalone backend entry: raw PDF/text bytes plus explicit orchestrator context."""
    try:
        document = await asyncio.to_thread(extract_document, data, filename, document_id)
    except DocumentError as exc:
        return ContractReview(
            status="needs_input",
            context=context,
            document_id=document_id,
            document_sha256=hashlib.sha256(data).hexdigest(),
            warnings=[str(exc)],
            questions=[
                Question(
                    id="contract_checker:question:readable_document",
                    rule_id=RuleId.SCHEDULE,
                    text="Can you supply the full contract as a text-based PDF or UTF-8 text?",
                    why="Unreadable or omitted pages prevent a complete evidence-backed review.",
                    resolves_when="All supplied contract pages contain extractable text.",
                )
            ],
        )
    return await review_document(document, context, ctx)
