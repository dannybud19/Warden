"""Library entries and the LLM's reply. Local to the consultant."""

from pydantic import BaseModel

from app.contracts import ActionKind, CheckId


class LibraryAction(BaseModel):
    """One candidate from `action_library.yaml`."""

    id: str
    check_id: CheckId
    kind: ActionKind
    lead: str
    ask: str
    why: str

    @property
    def text(self) -> str:
        return f"{self.lead.strip()} {self.ask.strip()}"


class RewordedAction(BaseModel):
    id: str
    lead: str


class RewordOutput(BaseModel):
    actions: list[RewordedAction] = []
