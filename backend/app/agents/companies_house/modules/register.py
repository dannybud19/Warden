"""Register module: resolve the company and run the Companies House rules (plan section 5).

Phase 1 skeleton: returns an empty result. The register subagent fills this in.
"""

import asyncio
from datetime import date

from app.agents.companies_house.models import RegisterResult
from app.agents.companies_house.retry import Sleep
from app.contracts import Case
from app.core.agent import AgentContext


async def run(
    ctx: AgentContext,
    case: Case,
    *,
    today: date | None = None,
    sleep: Sleep = asyncio.sleep,
) -> RegisterResult:
    """Resolve the landlord's company, fetch officers, apply the 5.3 rules."""
    return RegisterResult(name="register")
