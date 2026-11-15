"""Screenshot and document images to text (vision model, one call per image)."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.contracts import Message
from app.core.llm import LLMClient

PROMPTS_DIR = Path(__file__).parent / "prompts"
CHAT_PROMPT = "chat_screenshot.md"
DOCUMENT_PROMPT = "document_image.md"
VISION_TIMEOUT_S = 40.0  # per describe_image call; tests patch it low

# Reasons an OCRError carries; the orchestrator turns each into a message for the student.
NOT_A_CHAT = "not a chat"
NOT_A_DOCUMENT = "not a document"
UNREADABLE = "unreadable"
TIMEOUT = "timeout"
LLM_ERROR = "llm_error"
ZIP = "zip"
# images.ImageError reasons ("unsupported", "too_big", "empty") are passed through unchanged.


class OCRError(Exception):
    """An image could not be read. `reason` is safe to show the student (no secrets)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ChatLine(BaseModel):
    side: Literal["left", "right", "unknown"]
    name: str | None = None  # sender name if shown (group chats, some apps)
    time: str | None = None  # exactly as shown, e.g. "14:02", "Yesterday 09:15"
    text: str  # verbatim, no corrections; emojis kept; "[photo]" for images


class ChatRead(BaseModel):
    is_chat: bool  # false for anything that is not a chat screenshot
    app: Literal[
        "whatsapp",
        "imessage",
        "sms",
        "instagram",
        "spareroom",
        "openrent",
        "facebook",
        "email",
        "other",
    ] = "other"
    other_party: str | None = None  # name in the header, if shown
    lines: list[ChatLine] = []
    unreadable: bool = False  # too blurry or cropped to read reliably


class DocumentRead(BaseModel):
    is_document: bool
    text: str = ""  # verbatim transcription, reading order, line breaks kept
    unreadable: bool = False


def render_prompt(name: str, schema: type[BaseModel]) -> str:
    """The prompt file `name` from `prompts/`, with `{schema}` replaced by the JSON schema."""
    template = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    return template.replace("{schema}", json.dumps(schema.model_json_schema()))


async def read_chat(
    image: bytes, llm: LLMClient, student_name: str | None, evidence_id: str
) -> tuple[str, list[Message]]:
    """Transcript text and Messages from one chat screenshot. Raises OCRError."""
    raise NotImplementedError("WS C: read_chat")


async def read_document(image: bytes, llm: LLMClient) -> str:
    """Verbatim text of a photographed or screenshotted document. Raises OCRError."""
    raise NotImplementedError("WS C: read_document")
