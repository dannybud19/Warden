"""MongoDB Atlas repository (motor). One collection `cases`, `_id = case_id`."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.contracts import Case
from app.storage.repository import InitialUpload


class MongoCaseRepo:
    def __init__(self, uri: str, db_name: str = "rss") -> None:
        self._client: Any = AsyncIOMotorClient(uri)
        self._cases: Any = self._client[db_name]["cases"]

    @staticmethod
    def _doc(case: Case) -> dict[str, Any]:
        return {"_id": case.case_id, **case.model_dump(mode="json")}

    async def ping(self) -> None:
        """Fail fast when the cluster is unreachable (motor connects lazily)."""
        await self._client.admin.command("ping")

    async def create(self, case: Case, *, uploads: list[InitialUpload] | None = None) -> Case:
        """Insert a new case and return it."""
        doc = self._doc(case)
        doc["initial_uploads"] = [u.model_dump(mode="json") for u in uploads or []]
        await self._cases.insert_one(doc)
        return case

    async def get(self, case_id: str) -> Case | None:
        """Load a case by id, or None."""
        doc = await self._cases.find_one({"_id": case_id})
        if doc is None:
            return None
        doc.pop("_id", None)
        doc.pop("initial_uploads", None)
        return Case.model_validate(doc)

    async def save(self, case: Case, *, uploads: list[InitialUpload] | None = None) -> None:
        """Save case and optional manifest atomically; ordinary saves preserve intake progress."""
        fields = case.model_dump(mode="json")
        if uploads is not None:
            fields["initial_uploads"] = [u.model_dump(mode="json") for u in uploads]
        await self._cases.update_one({"_id": case.case_id}, {"$set": fields}, upsert=True)

    async def get_uploads(self, case_id: str) -> list[InitialUpload]:
        """Load the initial attachment manifest; old cases have no reservations."""
        doc = await self._cases.find_one({"_id": case_id}, {"initial_uploads": 1})
        return [InitialUpload.model_validate(u) for u in (doc or {}).get("initial_uploads", [])]

    async def drop(self) -> None:
        """Delete the whole collection (used by tests only)."""
        await self._cases.drop()

    def close(self) -> None:
        """Close the connection."""
        self._client.close()
