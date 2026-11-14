"""Fixtures for the cross-cutting tests: a CaseService on in-memory storage."""

from collections.abc import Callable
from typing import Any

import pytest

from app.aggregators.scoring.scoring import load_weights
from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent
from app.core.settings import Settings
from app.orchestrator.events import EventBus
from app.orchestrator.registry import build_agents
from app.orchestrator.service import CaseService, Upload
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


async def settled(service: CaseService, case_id: str) -> Case:
    """The stored case once every background analysis has finished."""
    await service.wait_idle()
    return await service.get_case(case_id)


async def add_evidence_and_settle(service: CaseService, case_id: str, upload: Upload) -> Case:
    """`add_evidence` (which saves, then analyses in the background), awaited to the end."""
    await service.add_evidence(case_id, upload)
    return await settled(service, case_id)


async def reply_and_settle(service: CaseService, case_id: str, text: str, **kwargs: Any) -> Case:
    """`reply` (which saves, then analyses in the background), awaited to the end."""
    await service.reply(case_id, text, **kwargs)
    return await settled(service, case_id)
