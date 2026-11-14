"""Shape of the LLM's reply. Local to this agent; converted to Findings before returning."""

from pydantic import BaseModel


class Influence(BaseModel):
    kind: str
    quote: str
    explanation: str = ""


class MessageAnalysis(BaseModel):
    message_id: str
    facts: list[str] = []
    influence: list[Influence] = []
    reassurance: list[str] = []


class EmotionOutput(BaseModel):
    entries: list[MessageAnalysis] = []
