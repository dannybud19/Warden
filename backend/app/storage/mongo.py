"""MongoDB Atlas repository (motor). One collection `cases`, `_id = case_id`."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.contracts import Case


class MongoCaseRepo:
    def __init__(self, uri: str, db_name: str = "rss") -> None:
        self._client: Any = AsyncIOMotorClient(uri)
        self._cases: Any = self._client[db_name]["cases"]

    @staticmethod
    def _doc(case: Case) -> dict[str, Any]:
        return {"_id": case.case_id, **case.model_dump(mode="json")}

    async def create(self, case: Case) -> Case:
        """Insert a new case and return it."""
        await self._cases.insert_one(self._doc(case))
        return case

    async def get(self, case_id: str) -> Case | None:
        """Load a case by id, or None."""
        doc = await self._cases.find_one({"_id": case_id})
        if doc is None:
            return None
        doc.pop("_id", None)
        return Case.model_validate(doc)

    async def save(self, case: Case) -> None:
        """Upsert the case."""
        await self._cases.replace_one({"_id": case.case_id}, self._doc(case), upsert=True)

    async def drop(self) -> None:
        """Delete the whole collection (used by tests only)."""
        await self._cases.drop()

    def close(self) -> None:
        """Close the connection."""
        self._client.close()
