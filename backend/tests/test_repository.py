"""Same contract for every CaseRepository. Mongo runs only when MONGODB_URI is set."""

import os
import uuid
from collections.abc import AsyncIterator

import pytest

from app.contracts import Case
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
