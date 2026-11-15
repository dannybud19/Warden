"""Shared schemas. FROZEN after Phase 0: see AGENTS.md, "Changing contracts"."""

from app.contracts.case import Case, ChatTurn, Landlord, Listing, StudentContext
from app.contracts.checks import (
    Action,
    ActionKind,
    ActionStatus,
    Check,
    CheckId,
    CheckState,
)
from app.contracts.events import (
    ActionsProposed,
    AgentFinished,
    AgentStarted,
    DecisionMade,
    OrchestratorMessage,
    ScoreUpdated,
    StreamEvent,
)
from app.contracts.evidence import Evidence, EvidenceKind, Message
from app.contracts.findings import (
    Category,
    EvidenceRef,
    Fact,
    FactKey,
    Finding,
    Severity,
)
from app.contracts.reports import AgentReport, AgentStatus, Decision, ScoreResult, Verdict

__all__ = [
    "Action",
    "ActionKind",
    "ActionStatus",
    "ActionsProposed",
    "AgentFinished",
    "AgentReport",
    "AgentStarted",
    "AgentStatus",
    "Case",
    "Category",
    "ChatTurn",
    "Check",
    "CheckId",
    "CheckState",
    "Decision",
    "DecisionMade",
    "Evidence",
    "EvidenceKind",
    "EvidenceRef",
    "Fact",
    "FactKey",
    "Finding",
    "Landlord",
    "Listing",
    "Message",
    "OrchestratorMessage",
    "ScoreResult",
    "ScoreUpdated",
    "Severity",
    "StreamEvent",
    "StudentContext",
    "Verdict",
]
