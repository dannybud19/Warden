"""Storage interface. Implementations: memory (default) and MongoDB Atlas."""

from typing import Literal, Protocol

from pydantic import BaseModel

from app.contracts import Case, EvidenceKind


class InitialUpload(BaseModel):
    """Durable intake progress, stored beside the shared Case rather than inside its schema."""

    request_id: str
    filename: str
    kind: EvidenceKind
    size: int
    note: str | None = None
    state: Literal["pending", "accepted", "skipped"] = "pending"
    evidence_id: str | None = None
    read_error: str | None = None


class CaseRepository(Protocol):
    async def create(self, case: Case, *, uploads: list[InitialUpload] | None = None) -> Case: ...

    async def get(self, case_id: str) -> Case | None: ...

    async def save(self, case: Case, *, uploads: list[InitialUpload] | None = None) -> None: ...

    async def get_uploads(self, case_id: str) -> list[InitialUpload]: ...
