"""Same contract for every CaseRepository. Mongo runs only when MONGODB_URI is set."""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from app.contracts import AgentReport, AgentStatus, Case, ChatTurn
from app.storage.memory import InMemoryCaseRepo
from app.storage.mongo import MongoCaseRepo
from app.storage.repository import CaseRepository


@pytest.fixture(params=["memory", "mongo"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[CaseRepository]:
    if request.param == "memory":
        yield InMemoryCaseRepo()
        return
    uri = os.environ.get("MONGODB_URI", "")
    if not uri:
        pytest.skip("MONGODB_URI is not set")
    mongo = MongoCaseRepo(uri, f"rss_test_{uuid.uuid4().hex[:8]}")
    yield mongo
    await mongo.drop()
    mongo.close()


async def test_create_get_roundtrip(repo: CaseRepository, fake_agency_case: Case) -> None:
    await repo.create(fake_agency_case)
    assert await repo.get(fake_agency_case.case_id) == fake_agency_case


async def test_chat_and_recap_roundtrip(repo: CaseRepository, fake_agency_case: Case) -> None:
    at = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
    case = fake_agency_case.model_copy(deep=True)
    case.chat = [
        ChatTurn(role="orchestrator", text="Your risk score is 100/100.", at=at),
        ChatTurn(role="student", text="yes, they did", at=at, action_ids=["act_viewing"]),
    ]
    case.reports["crosscheck"] = AgentReport(
        agent="crosscheck",
        version="0.1.0",
        status=AgentStatus.OK,
        input_hash="",
        summary="Two sources disagree on the rent.",
    )
    await repo.create(case)
    assert await repo.get(case.case_id) == case


def test_a_case_stored_before_chat_existed_still_loads(fake_agency_case: Case) -> None:
    old = fake_agency_case.model_dump(mode="json")
    old.pop("chat")
    for report in old["reports"].values():
        report.pop("summary")
    assert Case.model_validate(old).chat == []


async def test_get_missing_returns_none(repo: CaseRepository) -> None:
    assert await repo.get("case_nope") is None


async def test_save_upserts_and_persists_changes(
    repo: CaseRepository, fake_agency_case: Case
) -> None:
    await repo.save(fake_agency_case)  # upsert as insert
    changed = fake_agency_case.model_copy(update={"status": "decided"})
    await repo.save(changed)
    stored = await repo.get(fake_agency_case.case_id)
    assert stored is not None and stored.status == "decided"


async def test_memory_repo_does_not_alias_stored_cases(fake_agency_case: Case) -> None:
    repo = InMemoryCaseRepo()
    await repo.create(fake_agency_case)
    first = await repo.get(fake_agency_case.case_id)
    assert first is not None
    first.status = "decided"
    again = await repo.get(fake_agency_case.case_id)
    assert again is not None and again.status == "open"
