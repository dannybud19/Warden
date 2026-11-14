"""Contact module: email, phone and domain checks (plan section 7).

Phase 1 skeleton: returns an empty result. The contact subagent fills this in.
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
    company: ResolvedCompany | None,
    budget: QueryBudget,
    *,
    today: date | None = None,
    sleep: Sleep = asyncio.sleep,
) -> ModuleResult:
    """Checks on the landlord's email domain and phone. `company` is None when unresolved."""
    return ModuleResult(name="contact")
