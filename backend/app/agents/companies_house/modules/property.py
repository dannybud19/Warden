"""Property module: postcode check (plan section 8).

Phase 1 skeleton: returns an empty result. The property subagent fills this in.
"""

import asyncio

from app.agents.companies_house.models import ModuleResult
from app.agents.companies_house.retry import Sleep
from app.contracts import Case
from app.core.agent import AgentContext


async def run(
    ctx: AgentContext,
    case: Case,
    *,
    sleep: Sleep = asyncio.sleep,
) -> ModuleResult:
    """Check that the listing's postcode exists."""
    return ModuleResult(name="property")
