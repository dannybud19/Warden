"""Screenshot and document images to text (vision model, one call per image)."""

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.contracts import Message
from app.core.ids import new_id
from app.core.llm import LLMClient, _extract_json
from app.core.logging import get_logger
from app.intake import images, whatsapp

log = get_logger("intake")

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


_CHANNELS: dict[str, Literal["whatsapp", "email", "sms", "platform", "other"]] = {
    "whatsapp": "whatsapp",
    "imessage": "sms",
    "sms": "sms",
    "email": "email",
    "spareroom": "platform",
    "openrent": "platform",
    "facebook": "platform",
    "instagram": "platform",
}
# UK day-first "15/11/2026 14:02" (comma optional, seconds optional) or ISO "2026-11-15 14:02".
_UK_TIME = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?")
_ISO_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?")


def _parse_sent_at(shown: str | None) -> datetime | None:
    """A UTC datetime only for a full date and time that reads one way; else None."""
    text = (shown or "").strip().strip("[]()").strip()
    if match := _UK_TIME.fullmatch(text):
        day, month, year, hour, minute, second = match.groups()
    elif match := _ISO_TIME.fullmatch(text):
        year, month, day, hour, minute, second = match.groups()
    else:
        return None
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=UTC
        )
    except ValueError:
        return None


async def _ask(llm: LLMClient, image: bytes, prompt: str) -> str:
    """One vision call under the timeout; failures become OCRError (never the raw text)."""
    try:
        return await asyncio.wait_for(llm.describe_image(image, prompt), VISION_TIMEOUT_S)
    except TimeoutError as exc:
        raise OCRError(TIMEOUT) from exc
    except Exception as exc:
        log.warning("vision call failed: %s", type(exc).__name__)
        raise OCRError(LLM_ERROR) from exc


def _invalid_reply_reason(exc: Exception) -> str:
    """What was wrong with a reply, for the retry prompt: field paths and messages only (the
    model's own output, which may hold personal text, is left out)."""
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}"
            for e in exc.errors(include_input=False)[:5]
        ]
        return "; ".join(parts)[:300]
    return type(exc).__name__


async def _read_model[M: BaseModel](image: bytes, llm: LLMClient, prompt: str, model: type[M]) -> M:
    """Check the image, ask the vision model, parse JSON; one retry on an invalid reply."""
    try:
        images.check(image)
    except images.ImageError as exc:
        raise OCRError(exc.reason) from exc
    raw = await _ask(llm, image, prompt)
    try:
        return model.model_validate_json(_extract_json(raw))
    except (ValidationError, ValueError) as exc:
        reason = _invalid_reply_reason(exc)
        retry_prompt = f"{prompt}\n\nYour previous reply was invalid: {reason}"
    raw = await _ask(llm, image, retry_prompt)
    try:
        return model.model_validate_json(_extract_json(raw))
    except (ValidationError, ValueError) as exc:
        log.warning("vision reply invalid twice: %s", type(exc).__name__)
        raise OCRError(LLM_ERROR) from exc


def _senders(
    read: ChatRead, student_name: str | None
) -> list[Literal["student", "agent", "unknown"]]:
    """The sender of each line: a matched name first, then group rules, then bubble side."""
    names = sorted({ln.name.strip() for ln in read.lines if ln.name and ln.name.strip()})
    matched = whatsapp.student_senders(names, student_name)
    group = len(names) >= 2 and not matched
    side_rule: dict[str, Literal["student", "agent", "unknown"]] = {
        "right": "student",
        "left": "agent",
        "unknown": "unknown",
    }
    result: list[Literal["student", "agent", "unknown"]] = []
    for line in read.lines:
        name = line.name.strip() if line.name else ""
        if name and name in matched:
            result.append("student")
        elif name and matched:
            result.append("agent")
        elif name and group:
            result.append("unknown")
        elif not name and group:
            result.append("student" if line.side == "right" else "unknown")
        else:
            result.append(side_rule[line.side])
    return result


def _label(line: ChatLine, sender: str, other_party: str | None) -> str:
    if sender == "student":
        return "You"
    if line.name and line.name.strip():
        return line.name.strip()
    if sender == "agent":
        return (other_party or "").strip() or "Agent"
    return "Unknown"


async def read_chat(
    image: bytes, llm: LLMClient, student_name: str | None, evidence_id: str
) -> tuple[str, list[Message]]:
    """Transcript text and Messages from one chat screenshot. Raises OCRError."""
    read = await _read_model(image, llm, render_prompt(CHAT_PROMPT, ChatRead), ChatRead)
    if not read.is_chat:
        raise OCRError(NOT_A_CHAT)
    if read.unreadable or not any(ln.text.strip() for ln in read.lines):
        raise OCRError(UNREADABLE)
    channel = _CHANNELS.get(read.app, "other")
    senders = _senders(read, student_name)
    transcript: list[str] = []
    messages: list[Message] = []
    for line, sender in zip(read.lines, senders, strict=True):
        text = line.text.strip()
        if not text:
            continue
        shown = (line.time or "").strip()
        prefix = f"[{shown}] " if shown else ""
        transcript.append(f"{prefix}{_label(line, sender, read.other_party)}: {text}")
        messages.append(
            Message(
                id=new_id("msg"),
                evidence_id=evidence_id,
                sender=sender,
                sent_at=_parse_sent_at(line.time),
                channel=channel,
                text=text,
            )
        )
    return "\n".join(transcript), messages


async def read_document(image: bytes, llm: LLMClient) -> str:
    """Verbatim text of a photographed or screenshotted document. Raises OCRError."""
    read = await _read_model(image, llm, render_prompt(DOCUMENT_PROMPT, DocumentRead), DocumentRead)
    if not read.is_document:
        raise OCRError(NOT_A_DOCUMENT)
    if read.unreadable or not read.text.strip():
        raise OCRError(UNREADABLE)
    return read.text.strip()
