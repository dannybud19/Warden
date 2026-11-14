"""Storage interface. Implementations: memory (default) and MongoDB Atlas."""

from typing import Protocol

from app.contracts import Case


class CaseRepository(Protocol):
    async def create(self, case: Case) -> Case: ...

    async def get(self, case_id: str) -> Case | None: ...

    async def save(self, case: Case) -> None: ...
