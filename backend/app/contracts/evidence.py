"""Evidence the student uploads and the messages extracted from it."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class EvidenceKind(StrEnum):
    CHAT_SCREENSHOT = "chat_screenshot"
    CHAT_EXPORT = "chat_export"
    EMAIL = "email"
    CALL_RECORDING = "call_recording"
    VIDEO = "video"
    DOCUMENT = "document"
    CONTRACT = "contract"
    LISTING = "listing"


class Evidence(BaseModel):
    id: str  # "ev_<id>"
    kind: EvidenceKind
    uploaded_at: datetime
    filename: str | None = None
    file_url: str | None = None
    extracted_text: str | None = None  # filled by intake
    note: str | None = None  # student's caption


class Message(BaseModel):
    id: str
    evidence_id: str
    sender: Literal["student", "agent", "unknown"]
    sent_at: datetime | None = None
    channel: Literal["whatsapp", "email", "sms", "call", "platform", "other"]
    text: str
