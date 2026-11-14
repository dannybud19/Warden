"""Shape of the LLM's reply. Local to this agent; converted to Finding/Fact before returning."""

from pydantic import BaseModel


class LLMFlag(BaseModel):
    flag: str
    message_id: str
    quote: str
    explanation: str = ""
    confidence: float = 0.7
    check_id: str | None = None  # only for flag == "other"


class LLMClear(BaseModel):
    clear: str
    message_id: str
    quote: str
    explanation: str = ""
    confidence: float = 0.7


class LLMFact(BaseModel):
    key: str
    value: str
    message_id: str


class LLMOutput(BaseModel):
    flags: list[LLMFlag] = []
    clears: list[LLMClear] = []
    facts: list[LLMFact] = []
    questions: list[str] = []
