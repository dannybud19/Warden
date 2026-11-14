"""Shape of the LLM's reply. Local to this agent; converted to Findings before returning."""

from typing import Any

from pydantic import BaseModel, field_validator


class Influence(BaseModel):
    kind: str
    quote: str
    explanation: str = ""


class StatedFact(BaseModel):
    statement: str
    quote: str = ""  # the words in the message the statement rests on


class MessageAnalysis(BaseModel):
    message_id: str
    facts: list[StatedFact] = []
    influence: list[Influence] = []
    reassurance: list[str] = []

    @field_validator("facts", mode="before")
    @classmethod
    def _plain_strings(cls, value: Any) -> Any:
        """A bare string has no quote; it is parsed so the reply stays valid, then dropped."""
        if isinstance(value, list):
            return [{"statement": v} if isinstance(v, str) else v for v in value]
        return value


class EmotionOutput(BaseModel):
    entries: list[MessageAnalysis] = []
