"""In-memory repository: the default for dev and tests."""

from app.contracts import Case
from app.storage.repository import InitialUpload


class InMemoryCaseRepo:
    """Keeps deep copies so callers cannot mutate stored state by accident."""

    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._uploads: dict[str, list[InitialUpload]] = {}

    async def create(self, case: Case, *, uploads: list[InitialUpload] | None = None) -> Case:
        """Store a new case (overwrites an existing id) and return it."""
        self._cases[case.case_id] = case.model_copy(deep=True)
        self._uploads[case.case_id] = [u.model_copy(deep=True) for u in uploads or []]
        return case

    async def get(self, case_id: str) -> Case | None:
        """A copy of the stored case, or None."""
        stored = self._cases.get(case_id)
        return stored.model_copy(deep=True) if stored else None

    async def save(self, case: Case, *, uploads: list[InitialUpload] | None = None) -> None:
        """Upsert the case."""
        self._cases[case.case_id] = case.model_copy(deep=True)
        if uploads is not None:
            self._uploads[case.case_id] = [u.model_copy(deep=True) for u in uploads]

    async def get_uploads(self, case_id: str) -> list[InitialUpload]:
        """Copy the initial attachment manifest, including resolved entries."""
        return [u.model_copy(deep=True) for u in self._uploads.get(case_id, [])]
