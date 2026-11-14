"""Fixtures for the cross-cutting tests: a CaseService on in-memory storage."""

from collections.abc import Callable

import pytest

from app.aggregators.scoring.scoring import load_weights
from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent
from app.core.settings import Settings
from app.orchestrator.events import EventBus
from app.orchestrator.registry import build_agents
from app.orchestrator.service import CaseService
from app.storage.memory import InMemoryCaseRepo


class EmptyAgent(BaseAgent):
    """Needs nothing and reports nothing: lets the consultant drive the loop."""

    name = "empty"

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        return self.report(case)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def make_service(
    settings: Settings, ctx: AgentContext, bus: EventBus
) -> Callable[[list[BaseAgent] | None], CaseService]:
    def _make(agents: list[BaseAgent] | None = None) -> CaseService:
        return CaseService(
            InMemoryCaseRepo(),
            bus,
            agents if agents is not None else build_agents(settings),
            ctx,
            load_weights(),
        )

    return _make
