"""Shared pytest fixtures: offline context and the synthetic fixture cases."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.contracts import Case
from app.core.agent import AgentContext
from app.core.llm import FakeLLM
from app.core.logging import get_logger
from app.core.search import FakeSearch
from app.core.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings that ignore any local .env and default every agent to its stub."""
    return Settings(_env_file=None, default_agent_mode="stub", storage="memory")  # type: ignore[call-arg]


@pytest.fixture
def fixtures_dir(settings: Settings) -> Path:
    return settings.fixtures_dir


@pytest.fixture
async def ctx(settings: Settings) -> AsyncIterator[AgentContext]:
    """An AgentContext with no network: FakeLLM, FakeSearch and a 404-only HTTP transport."""
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as http:
        yield AgentContext(
            llm=FakeLLM(), search=FakeSearch(), http=http, settings=settings, log=get_logger("test")
        )


def load_case(fixtures_dir: Path, name: str) -> Case:
    return Case.model_validate_json((fixtures_dir / "cases" / f"{name}.json").read_text())


@pytest.fixture
def fake_agency_case(fixtures_dir: Path) -> Case:
    return load_case(fixtures_dir, "fake_agency")


@pytest.fixture
def overseas_landlord_case(fixtures_dir: Path) -> Case:
    return load_case(fixtures_dir, "overseas_landlord")


@pytest.fixture
def genuine_flat_case(fixtures_dir: Path) -> Case:
    return load_case(fixtures_dir, "genuine_flat")
