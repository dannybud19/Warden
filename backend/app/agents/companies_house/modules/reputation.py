"""Reputation module: scam reports, reviews, redress/CMP, Rogue Checker (plan section 6).

Phase 1 skeleton: returns an empty result. The reputation subagent fills this in.
"""

import asyncio
from datetime import date

from app.agents.companies_house.models import ModuleResult, QueryBudget, ResolvedCompany
from app.agents.companies_house.retry import Sleep
from app.contracts import Case
from app.core.agent import AgentContext


async def run(
    ctx: AgentContext,
    case: Case,
    company: ResolvedCompany,
    budget: QueryBudget,
    *,
    today: date | None = None,
    sleep: Sleep = asyncio.sleep,
) -> ModuleResult:
    """Public-web reputation of a resolved company."""
    return ModuleResult(name="reputation")
