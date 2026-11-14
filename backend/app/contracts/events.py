"""WebSocket payloads: a discriminated union on `type`."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.contracts.checks import Action
from app.contracts.reports import AgentReport, Decision, ScoreResult


class AgentStarted(BaseModel):
    type: Literal["agent_started"] = "agent_started"
    agent: str


class AgentFinished(BaseModel):
    type: Literal["agent_finished"] = "agent_finished"
    report: AgentReport


class ScoreUpdated(BaseModel):
    type: Literal["score_updated"] = "score_updated"
    score: ScoreResult


class ActionsProposed(BaseModel):
    type: Literal["actions_proposed"] = "actions_proposed"
    actions: list[Action]


class OrchestratorMessage(BaseModel):
    type: Literal["orchestrator_message"] = "orchestrator_message"
    text: str


class DecisionMade(BaseModel):
    type: Literal["decision_made"] = "decision_made"
    decision: Decision


StreamEvent = Annotated[
    AgentStarted
    | AgentFinished
    | ScoreUpdated
    | ActionsProposed
    | OrchestratorMessage
    | DecisionMade,
    Field(discriminator="type"),
]
