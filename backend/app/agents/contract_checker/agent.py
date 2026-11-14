"""Compatibility adapter for the existing Case -> AgentReport pipeline."""

from decimal import Decimal

from app.agents.contract_checker.models import ContractReview, ReviewContext
from app.agents.contract_checker.review import review_contract
from app.contracts import (
    AgentReport,
    AgentStatus,
    Case,
    Category,
    CheckId,
    EvidenceKind,
    EvidenceRef,
    Fact,
    FactKey,
    Finding,
    Severity,
)
from app.core.agent import AgentContext, BaseAgent, Need


class ContractCheckerAgent(BaseAgent):
    name = "contract_checker"
    version = "0.2.0"
    requires = frozenset({Need.CONTRACT})
    timeout_s = 120.0

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        """Adapt existing extracted evidence; raw-file callers use review_contract directly."""
        contracts = [e for e in case.evidence if e.kind == EvidenceKind.CONTRACT]
        if len(contracts) != 1 or not contracts[0].extracted_text:
            return self.report(
                case,
                status=AgentStatus.NEEDS_INPUT,
                questions=[
                    "Supply one readable current contract; version selection is not implemented."
                ],
            )
        contract = contracts[0]
        context = ReviewContext(
            assessment_date=case.created_at.date(),
            answers=[a.answer for a in case.actions if a.answer],
        )
        review = await review_contract(
            (contract.extracted_text or "").encode("utf-8"),
            "contract.txt",
            context,
            ctx,
            document_id=contract.id,
        )
        report = self.report(
            case,
            status=AgentStatus.OK if review.status == "complete" else AgentStatus.NEEDS_INPUT,
            findings=report_findings(review),
            facts=report_facts(review),
            questions=[q.text for q in review.questions],
        )
        return report.model_copy(update={"duration_ms": review.duration_ms})


def report_findings(review: ContractReview) -> list[Finding]:
    """Map concerns conservatively; a limited rule pass cannot clear a whole shared check."""
    findings: list[Finding] = []
    for issue in review.issues:
        if issue.status in {"cleared", "dismissed"}:
            continue
        check = {
            "deposit_cap": CheckId.DEPOSIT_PROTECTION,
            "holding_deposit_cap": CheckId.PAYMENT_SAFETY,
            "advance_rent": CheckId.PAYMENT_SAFETY,
        }.get(issue.rule_id, CheckId.CONTRACT_CONSISTENCY)
        detail = issue.explanation
        if issue.calculation:
            detail += " " + issue.calculation
        detail += f" Importance: {issue.importance}/100."
        if issue.uncertainty:
            detail += " Conditional: " + " ".join(issue.uncertainty)
        if issue.legal_sources:
            detail += " Sources: " + " ".join(s.url for s in issue.legal_sources)
        findings.append(
            Finding(
                id=issue.id,
                agent="contract_checker",
                check_id=check,
                title=issue.title,
                detail=detail,
                category=Category.DOCUMENT,
                severity=Severity.LOW if issue.status == "conditional" else Severity.HIGH,
                confidence=issue.confidence,
                evidence=[
                    EvidenceRef(evidence_id=e.document_id, quote=e.quote) for e in issue.evidence
                ],
                supports="suspicious",
                hard_flag=False,
            )
        )
    return findings


def report_facts(review: ContractReview) -> list[Fact]:
    """Expose unambiguous quoted contract facts for the separate comparison agent."""
    keys = {
        "property_address": FactKey.ADDRESS,
        "landlord_name": FactKey.LANDLORD_NAME,
        "move_in_date": FactKey.MOVE_IN_DATE,
    }
    facts = [
        Fact(key=keys[f.kind], value=f.value, source=review.document_id, agent="contract_checker")
        for f in review.facts
    ]
    monthly = {
        term.amount
        * {"month": Decimal(1), "week": Decimal(52) / 12, "year": Decimal(1) / 12}[term.frequency]
        for term in review.money
        if term.kind == "rent" and term.frequency in {"month", "week", "year"}
    }
    deposits = {term.amount for term in review.money if term.kind == "deposit"}
    for key, values in ((FactKey.RENT_PCM, monthly), (FactKey.DEPOSIT, deposits)):
        if len(values) == 1:
            value = next(iter(values))
            # Do not invent precision when a conversion produces a fractional penny.
            if value == value.quantize(Decimal("0.01")):
                facts.append(
                    Fact(
                        key=key,
                        value=format(value.normalize(), "f"),
                        source=review.document_id,
                        agent="contract_checker",
                    )
                )
    return facts
