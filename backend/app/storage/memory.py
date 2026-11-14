"""In-memory repository: the default for dev and tests."""

from app.contracts import Case


class InMemoryCaseRepo:
    """Keeps deep copies so callers cannot mutate stored state by accident."""

    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}

    async def create(self, case: Case) -> Case:
        """Store a new case (overwrites an existing id) and return it."""
        self._cases[case.case_id] = case.model_copy(deep=True)
        return case

    async def get(self, case_id: str) -> Case | None:
        """A copy of the stored case, or None."""
        stored = self._cases.get(case_id)
        return stored.model_copy(deep=True) if stored else None

    async def save(self, case: Case) -> None:
        """Upsert the case."""
        self._cases[case.case_id] = case.model_copy(deep=True)
