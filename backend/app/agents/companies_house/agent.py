"""CompaniesHouse agent: a background check on the company, contact details and property.

I/O orchestration only. It produces evidence and never gives a verdict. See README.md.
"""

import asyncio
from collections.abc import Awaitable
from datetime import date
from typing import Any, ClassVar

from app.agents.companies_house.constants import AGENT_NAME, AGENT_TIMEOUT_S, MODULE_DEADLINE_S
from app.agents.companies_house.evidence import not_run_finding
from app.agents.companies_house.models import ModuleResult, QueryBudget
from app.agents.companies_house.modules import contact, property, register, reputation
from app.agents.companies_house.normalise import extract_contacts, extract_postcode
from app.agents.companies_house.retry import Sleep
from app.contracts import AgentReport, AgentStatus, Case, Fact, Finding, Severity
from app.core.agent import AgentContext, BaseAgent, Need

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


def _order(finding: Finding) -> tuple[int, int, int]:
    """Hard flags first, then suspicious by severity, then clears (App. D)."""
    return (
        1 if finding.supports == "cleared" else 0,
        0 if finding.hard_flag else 1,
        _SEVERITY_RANK[finding.severity],
    )


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """Dedupe by id (first wins) and order for display."""
    seen: dict[str, Finding] = {}
    for f in findings:
        seen.setdefault(f.id, f)
    return sorted(seen.values(), key=_order)


def merge_facts(facts: list[Fact]) -> list[Fact]:
    seen: dict[tuple[str, str, str], Fact] = {}
    for f in facts:
        seen.setdefault((f.key.value, f.value, f.source), f)
    return list(seen.values())


class CompaniesHouseAgent(BaseAgent):
    name: ClassVar[str] = AGENT_NAME
    requires = frozenset({Need.LANDLORD})
    timeout_s: ClassVar[float] = AGENT_TIMEOUT_S

    def __init__(
        self,
        *,
        today: date | None = None,
        sleep: Sleep = asyncio.sleep,
        deadline_s: float = MODULE_DEADLINE_S,
    ) -> None:
        # NOTE: today, sleep and the deadline are injectable so tests are deterministic and fast.
        self._today = today
        self._sleep = sleep
        self._deadline_s = deadline_s

    def input_slice(self, case: Case) -> dict[str, Any]:
        """Landlord, answers and student plus the listing postcode and landlord contacts."""
        data = super().input_slice(case)
        data["listing_postcode"] = extract_postcode(case.listing)
        data["contacts"] = extract_contacts(case).keys()
        return data

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        landlord = case.landlord
        has_company = bool(
            landlord
            and ((landlord.company_number or "").strip() or (landlord.company_name or "").strip())
        )
        if not has_company:
            return self.report(case, status=AgentStatus.SKIPPED, error="no company name or number")
        if not ctx.settings.companies_house_api_key:
            return self.report(
                case, status=AgentStatus.ERROR, error="COMPANIES_HOUSE_API_KEY is not set"
            )

        started = asyncio.get_running_loop().time()
        reg = await register.run(ctx, case, today=self._today, sleep=self._sleep)
        if reg.fatal:
            return self.report(
                case,
                status=AgentStatus.ERROR,
                error=reg.error or "companies house: register unavailable after 3 attempts",
            )

        budget = QueryBudget()
        company = reg.resolved_company
        tasks: dict[str, Awaitable[ModuleResult]] = {}
        if company is not None:
            tasks["reputation"] = reputation.run(
                ctx, case, company, budget, today=self._today, sleep=self._sleep
            )
        tasks["contact"] = contact.run(
            ctx, case, company, budget, today=self._today, sleep=self._sleep
        )
        tasks["property"] = property.run(ctx, case, sleep=self._sleep)
        remaining = max(1.0, self._deadline_s - (asyncio.get_running_loop().time() - started))
        outcomes = await asyncio.gather(
            *(asyncio.wait_for(task, remaining) for task in tasks.values()),
            return_exceptions=True,
        )

        results: list[ModuleResult] = [reg]
        for module_name, outcome in zip(tasks, outcomes, strict=True):
            if isinstance(outcome, ModuleResult):
                results.append(outcome)
                continue
            if isinstance(outcome, BaseException) and not isinstance(outcome, Exception):
                raise outcome
            reason = "timed out" if isinstance(outcome, TimeoutError) else "unexpected error"
            ctx.log.error(
                "companies_house: %s module failed (%s): %r", module_name, reason, outcome
            )
            results.append(
                ModuleResult(name=module_name, failed_checks=[f"{module_name} checks ({reason})"])
            )

        findings: list[Finding] = []
        facts: list[Fact] = []
        questions: list[str] = []
        for result in results:
            findings.extend(result.findings)
            facts.extend(result.facts)
            questions.extend(q for q in result.questions if q not in questions)
            if result.failed_checks:
                findings.append(not_run_finding(result.name, result.failed_checks))

        return self.report(
            case,
            status=AgentStatus.OK,
            findings=merge_findings(findings),
            facts=merge_facts(facts),
            questions=questions,
        )
