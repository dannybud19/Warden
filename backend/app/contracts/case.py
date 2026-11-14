"""The Case: the single object every agent reads."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.contracts.checks import Action, Check
from app.contracts.evidence import Evidence, Message
from app.contracts.reports import AgentReport, Decision, ScoreResult


class StudentContext(BaseModel):
    budget_pcm: int | None = None
    move_in_date: date | None = None
    university: str | None = None
    notes: str | None = None


class Listing(BaseModel):
    url: str | None = None
    platform: str | None = None
    address: str | None = None
    postcode: str | None = None
    rent_pcm: int | None = None
    deposit: int | None = None
    description: str | None = None


class Landlord(BaseModel):
    name: str | None = None
    company_name: str | None = None
    company_number: str | None = None
    email: str | None = None
    phone: str | None = None


class ChatTurn(BaseModel):
    """One message in the chat between the student and the orchestrator."""

    role: Literal["student", "orchestrator"]
    text: str
    at: datetime
    action_ids: list[str] = []  # actions this turn answered (student turns only)


class Case(BaseModel):
    case_id: str
    created_at: datetime
    status: Literal["open", "decided"] = "open"
    student: StudentContext = StudentContext()
    listing: Listing | None = None
    landlord: Landlord | None = None
    evidence: list[Evidence] = []
    messages: list[Message] = []
    checks: list[Check] = []  # initialised with all 8 CheckIds, UNVERIFIED
    actions: list[Action] = []
    reports: dict[str, AgentReport] = {}  # latest report per agent
    score_history: list[ScoreResult] = []
    decision: Decision | None = None
    chat: list[ChatTurn] = []  # student replies and orchestrator messages, oldest first
