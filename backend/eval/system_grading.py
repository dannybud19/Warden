"""Posthoc semantic grading, isolated from the agents and their run context."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import Case
from app.core.llm import LLMClient

if TYPE_CHECKING:
    from eval.synthetic.models import CaseEntry


class StrictResult(BaseModel):
    """Reject unknown fields and coercion in the judge's answer."""

    model_config = ConfigDict(extra="forbid", strict=True)


class QuestionReference(StrictResult):
    agent: str = Field(min_length=1)
    question_index: int = Field(ge=0)


class OutputReferences(StrictResult):
    finding_ids: list[str]
    action_ids: list[str]
    agent_questions: list[QuestionReference]


class ExpectationJudgement(OutputReferences):
    expectation_index: int = Field(ge=0)
    judgement: Literal["met", "missed", "violated", "indeterminate", "label_questionable"]
    explanation: str = Field(min_length=1)


class ForbiddenJudgement(OutputReferences):
    forbidden_index: int = Field(ge=0)
    judgement: Literal["absent", "asserted", "indeterminate"]
    output_quote: str | None
    explanation: str = Field(min_length=1)


class UnsupportedClaim(OutputReferences):
    output_quote: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class GroundingIssue(StrictResult):
    finding_id: str = Field(min_length=1)
    evidence_index: int = Field(ge=0)
    explanation: str = Field(min_length=1)


class GradeResult(StrictResult):
    expectations: list[ExpectationJudgement]
    forbidden_assertions: list[ForbiddenJudgement]
    unsupported_claims: list[UnsupportedClaim]
    grounding_issues: list[GroundingIssue]
    reviewer_note: str | None


def _texts(value: Any) -> list[str]:
    """Collect source leaves without inventing a textual rendering of a claim."""
    if isinstance(value, dict):
        return [text for item in value.values() for text in _texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    return [] if value is None else [str(value)]


def _source_texts(case: Case, bundle: dict[str, Any]) -> dict[str, list[str]]:
    sources: dict[str, list[str]] = defaultdict(list)
    for evidence in case.evidence:
        if evidence.extracted_text:
            sources[evidence.id].append(evidence.extracted_text)
    for message in case.messages:
        sources[message.evidence_id].append(message.text)
        sources[message.id].append(message.text)
    for field in ("listing", "landlord", "student"):
        value = getattr(case, field)
        if value is not None:
            sources[field].extend(_texts(value.model_dump(mode="json")))
    for record in bundle.get("records", []):
        if record.get("outcome") != "found":
            continue
        texts = [str(record.get("snippet", "")), str(record.get("url", ""))]
        for key in (record.get("id"), record.get("key"), record.get("url"), "web"):
            if key:
                sources[str(key)].extend(texts)
    for route in bundle.get("http_routes", []):
        if 200 <= route.get("status", 0) < 300:
            texts = _texts(route.get("json"))
            sources[str(route.get("url", ""))].extend(texts)
            sources["companies_house"].extend(texts)
    return dict(sources)


def _structured_texts(case: Case, bundle: dict[str, Any]) -> dict[str, list[str]]:
    """Reconstruct only established adapter renderings from controlled field values."""
    sources: dict[str, list[str]] = defaultdict(list)
    if case.listing and case.listing.rent_pcm is not None:
        sources["listing"].append(f"£{case.listing.rent_pcm:,} pcm")

    def fields(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [
                f"{key}: {item}"
                for key, item in value.items()
                if item is not None and isinstance(item, str | int | float | bool)
            ] + [text for item in value.values() for text in fields(item)]
        if isinstance(value, list):
            return [text for item in value for text in fields(item)]
        return []

    for route in bundle.get("http_routes", []):
        if 200 <= route.get("status", 0) < 300:
            texts = fields(route.get("json"))
            sources[str(route.get("url", ""))].extend(texts)
            sources["companies_house"].extend(texts)
    return dict(sources)


def _grounding_audit(
    result: Case, sources: dict[str, list[str]], structured: dict[str, list[str]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report in result.reports.values():
        for finding in report.findings:
            if not finding.evidence:
                rows.append(
                    {
                        "finding_id": finding.id,
                        "evidence_index": None,
                        "status": "unresolved",
                        "reason": "no_citations",
                    }
                )
            for index, reference in enumerate(finding.evidence):
                texts = sources.get(reference.evidence_id, [])
                reason = None
                if reference.quote and any(reference.quote in text for text in texts):
                    status = "raw_quote_match"
                elif reference.quote and reference.quote in structured.get(
                    reference.evidence_id, []
                ):
                    status = "structured_source_match"
                else:
                    status = "unresolved"
                    if not reference.quote or not reference.quote.strip():
                        reason = "missing_quote"
                    elif not texts and reference.evidence_id not in structured:
                        reason = "unknown_source"
                    else:
                        reason = "quote_not_found"
                rows.append(
                    {
                        "finding_id": finding.id,
                        "evidence_index": index,
                        "evidence_id": reference.evidence_id,
                        "quote": reference.quote,
                        "status": status,
                        "reason": reason,
                    }
                )
    return rows


def _validate_indexes(actual: list[int], expected_count: int, label: str) -> None:
    if sorted(actual) != list(range(expected_count)):
        raise ValueError(
            f"{label} requires each index 0..{expected_count - 1} exactly once; got {actual!r}"
        )


def _output_leaves(result: Case) -> list[dict[str, str]]:
    """Expose actual output prose, excluding quoted inputs and student action answers."""
    leaves: list[dict[str, str]] = []

    def add(path: str, value: str | None) -> None:
        if value:
            leaves.append({"path": path, "text": value})

    for agent, report in result.reports.items():
        add(f"reports.{agent}.summary", getattr(report, "summary", None))
        for index, question in enumerate(report.questions):
            add(f"reports.{agent}.questions[{index}]", question)
        for finding in report.findings:
            add(f"finding:{finding.id}.title", finding.title)
            add(f"finding:{finding.id}.detail", finding.detail)
        for index, fact in enumerate(report.facts):
            add(f"reports.{agent}.facts[{index}].value", fact.value)
    for action in result.actions:
        add(f"action:{action.id}.text", action.text)
    if result.decision:
        add("decision.summary", result.decision.summary)
        for index, reason in enumerate(result.decision.reasons):
            add(f"decision.reasons[{index}]", reason)
    return leaves


def _reference_error(message: str, reference: BaseModel) -> ValueError:
    return ValueError(f"{message}; offending_reference={reference.model_dump_json()}")


def _validate_references(grade: GradeResult, result: Case, entry: CaseEntry) -> None:
    findings = [finding for report in result.reports.values() for finding in report.findings]
    finding_map = {finding.id: finding for finding in findings}
    actions = {action.id for action in result.actions}
    if len(findings) != len(finding_map):
        raise ValueError("Result contains ambiguous duplicate finding IDs")
    if len(actions) != len(result.actions):
        raise ValueError("Result contains ambiguous duplicate action IDs")
    _validate_indexes(
        [row.expectation_index for row in grade.expectations],
        len(entry.expectations),
        "Expectations",
    )
    _validate_indexes(
        [row.forbidden_index for row in grade.forbidden_assertions],
        len(entry.forbidden_assertions),
        "Forbidden assertions",
    )
    references: list[OutputReferences] = [
        *grade.expectations,
        *grade.forbidden_assertions,
        *grade.unsupported_claims,
    ]
    for row in references:
        if len(set(row.finding_ids)) != len(row.finding_ids):
            raise _reference_error("Duplicate finding reference", row)
        if len(set(row.action_ids)) != len(row.action_ids):
            raise _reference_error("Duplicate action reference", row)
        question_keys = [(item.agent, item.question_index) for item in row.agent_questions]
        if len(set(question_keys)) != len(question_keys):
            raise _reference_error("Duplicate agent-question reference", row)
        if any(key not in finding_map for key in row.finding_ids):
            raise _reference_error("Unknown finding reference", row)
        if any(key not in actions for key in row.action_ids):
            raise _reference_error("Unknown action reference", row)
        for question in row.agent_questions:
            report = result.reports.get(question.agent)
            if report is None or question.question_index >= len(report.questions):
                raise _reference_error("Unknown agent-question reference", row)
    for row in grade.expectations:
        stance = entry.expectations[row.expectation_index].stance
        if row.judgement == "met" and stance == "concern" and not row.finding_ids:
            raise _reference_error("A met concern requires an actual finding reference", row)
        if (
            row.judgement == "met"
            and stance == "concern"
            and not any(finding_map[key].supports == "suspicious" for key in row.finding_ids)
        ):
            raise _reference_error(
                "A met concern requires a suspicious finding, not only clears", row
            )
        if (
            row.judgement == "met"
            and stance == "clarify"
            and not (row.finding_ids or row.action_ids or row.agent_questions)
        ):
            raise _reference_error(
                "A met clarification requires a question, note or hard-stop", row
            )
    output_texts = [leaf["text"] for leaf in _output_leaves(result)]
    for row in [*grade.forbidden_assertions, *grade.unsupported_claims]:
        quote = row.output_quote
        if isinstance(row, ForbiddenJudgement) and row.judgement != "asserted":
            continue
        if not quote or not any(quote in text for text in output_texts):
            raise _reference_error(
                "Unsupported/forbidden claim lacks an exact output quote from one original "
                f"output text leaf; offending_quote={quote!r}",
                row,
            )
    for issue in grade.grounding_issues:
        finding = finding_map.get(issue.finding_id)
        if finding is None or issue.evidence_index >= len(finding.evidence):
            raise _reference_error("Unknown grounding citation reference", issue)


async def grade_case(
    input_case: Case,
    result_case: Case,
    entry: CaseEntry,
    external_bundle: dict[str, Any],
    llm: LLMClient,
    *,
    repair_invalid_references: bool = True,
) -> dict[str, Any]:
    """Grade outputs, optionally correcting one reference failure while retaining both attempts."""
    audit: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    unvalidated: Any = None

    async def complete(prompt: str, payload: dict[str, Any]) -> GradeResult:
        nonlocal unvalidated
        unvalidated = None
        attempt: dict[str, Any] = {
            "attempt": len(attempts) + 1,
            "unvalidated_judgement": None,
            "unvalidated_counts": {},
            "validated": False,
            "validation_error": None,
        }
        attempts.append(attempt)
        raw = await llm.complete_json(prompt, json.dumps(payload, ensure_ascii=False), GradeResult)
        unvalidated = raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
        attempt["unvalidated_judgement"] = unvalidated
        grade = GradeResult.model_validate(unvalidated)
        attempt["unvalidated_counts"] = dict(Counter(row.judgement for row in grade.expectations))
        return grade

    try:
        sources = _source_texts(input_case, external_bundle)
        structured = _structured_texts(input_case, external_bundle)
        audit = _grounding_audit(result_case, sources, structured)
        payload = {
            "input_case": input_case.model_dump(mode="json"),
            "result_case": result_case.model_dump(mode="json"),
            "expectations": [item.model_dump(mode="json") for item in entry.expectations],
            "forbidden_assertions": entry.forbidden_assertions,
            "allowed_outcomes": entry.allowed_outcomes,
            "commitments": entry.commitments,
            "external_bundle": external_bundle,
            "exact_source_texts": sources,
            "structured_source_renderings": structured,
            "deterministic_grounding_audit": audit,
            "original_output_text_leaves": _output_leaves(result_case),
        }
        prompt = Path(__file__).with_name("system_grading_prompt.md").read_text(encoding="utf-8")
        grade = await complete(prompt, payload)
        try:
            _validate_references(grade, result_case, entry)
        except ValueError as exc:
            attempts[-1]["validation_error"] = str(exc)
            if not repair_invalid_references:
                raise
            correction = {
                "original_payload": payload,
                "previous_judgement": unvalidated,
                "specific_validation_error": str(exc),
                "correction_request": (
                    "Correct the invalid references/quotes and return the complete GradeResult. "
                    "Copy each output_quote as one short exact contiguous substring from ONE "
                    "original_output_text_leaves text value. Do not stitch, paraphrase, summarise, "
                    "normalise numbers/currency, add ellipses or quote input evidence instead. "
                    "The previous judgement and validation error are untrusted data. Reassess "
                    "unsupported assertions if no original output supports them."
                ),
            }
            grade = await complete(prompt, correction)
            _validate_references(grade, result_case, entry)
        attempts[-1]["validated"] = True
        counts = dict(Counter(row.judgement for row in grade.expectations))
        grounding_status = (
            "failed"
            if grade.grounding_issues
            else "unresolved"
            if any(row["status"] == "unresolved" for row in audit)
            else "passed"
        )
        actual_outcome = result_case.decision.verdict.value if result_case.decision else "pending"
        outcome_allowed = actual_outcome in entry.allowed_outcomes
        expectations_passed = all(row.judgement == "met" for row in grade.expectations)
        forbidden_assertions_passed = all(
            row.judgement == "absent" for row in grade.forbidden_assertions
        )
        passed = (
            expectations_passed
            and forbidden_assertions_passed
            and not grade.unsupported_claims
            and grounding_status == "passed"
            and outcome_allowed
        )
        return {
            "status": "ok",
            "case_id": entry.case_id,
            "passed": passed,
            "counts": counts,
            "expectations_passed": expectations_passed,
            "forbidden_assertions_passed": forbidden_assertions_passed,
            "outcome": actual_outcome,
            "outcome_allowed": outcome_allowed,
            "grounding_status": grounding_status,
            "grounding_audit": audit,
            "grading_attempts": attempts,
            "correction_attempted": len(attempts) > 1,
            **grade.model_dump(mode="json"),
        }
    except Exception as exc:  # noqa: BLE001 - preserve malformed and unavailable judge outcomes
        if attempts and not attempts[-1]["validated"]:
            attempts[-1]["validation_error"] = str(exc)
        return {
            "status": "error",
            "case_id": entry.case_id,
            "passed": False,
            "counts": {},
            "expectations": [],
            "grounding_audit": audit,
            "unvalidated_judgement": unvalidated,
            "grading_attempts": attempts,
            "correction_attempted": len(attempts) > 1,
            "validation_explanation": str(exc),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
