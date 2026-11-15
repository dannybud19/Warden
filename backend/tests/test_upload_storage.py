"""Offline storage checks for the manifest persisted alongside Case."""

from copy import deepcopy
from typing import Any

import pytest

from app.contracts import Case, EvidenceKind
from app.storage.memory import InMemoryCaseRepo
from app.storage.mongo import MongoCaseRepo
from app.storage.repository import InitialUpload


class FakeCollection:
    """Mongo's document semantics without opening any network connection."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.documents[document["_id"]] = deepcopy(document)

    async def find_one(self, query: dict[str, str], projection: Any = None) -> Any:
        return deepcopy(self.documents.get(query["_id"]))

    async def update_one(
        self, query: dict[str, str], update: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert and set(update) == {"$set"}
        document = self.documents.setdefault(query["_id"], dict(query))
        document.update(deepcopy(update["$set"]))


@pytest.mark.parametrize("mongo", [False, True])
async def test_case_saves_preserve_manifest_and_readable_uploads_resolve_atomically(
    fake_agency_case: Case,
    mongo: bool,
) -> None:
    repo = MongoCaseRepo("mongodb://localhost:1") if mongo else InMemoryCaseRepo()
    collection = FakeCollection()
    if isinstance(repo, MongoCaseRepo):
        repo._cases = collection
    try:
        item = InitialUpload(
            request_id="upload-1", filename="email.pdf", kind=EvidenceKind.EMAIL, size=123
        )
        case = fake_agency_case.model_copy(deep=True)
        await repo.create(case, uploads=[item])
        # Ordinary case mutations must not wipe the hold (previous Mongo replace_one would).
        case.student.notes = "An ordinary case update"
        await repo.save(case)
        pending = await repo.get_uploads(case.case_id)
        assert pending[0].state == "pending"
        pending[0].state = "accepted"
        assert (await repo.get_uploads(case.case_id))[0].state == "pending"  # copied, not aliased
        await repo.save(case, uploads=pending)
        assert await repo.get(case.case_id) == case
        assert (await repo.get_uploads(case.case_id))[0].state == "accepted"
        if isinstance(repo, MongoCaseRepo):
            restarted = MongoCaseRepo("mongodb://localhost:1")
            restarted._cases = collection
            try:
                assert (await restarted.get_uploads(case.case_id))[0].state == "accepted"
            finally:
                restarted.close()
        assert await repo.get_uploads("missing") == []
    finally:
        if isinstance(repo, MongoCaseRepo):
            repo.close()
