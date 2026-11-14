"""Batched LLM snippet filter with keyword fallback (plan 6.2, App. G).

Phase 1 skeleton: keeps nothing. The reputation subagent fills this in.
"""

from app.agents.companies_house.models import FilterContext, KeptSnippet, Snippet
from app.core.agent import AgentContext


async def filter_snippets(
    ctx: AgentContext, snippets: list[Snippet], context: FilterContext
) -> list[KeptSnippet]:
    """Keep only scam reports and negative reviews that are about this subject."""
    return []
