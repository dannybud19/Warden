"""Offline checks for the OCR prompt files and their routing keys."""

import json

from app.intake.ocr import (
    CHAT_PROMPT,
    DOCUMENT_PROMPT,
    PROMPTS_DIR,
    ChatRead,
    DocumentRead,
    render_prompt,
)


def _raw(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def test_prompt_files_exist_and_load() -> None:
    for name in (CHAT_PROMPT, DOCUMENT_PROMPT):
        assert (PROMPTS_DIR / name).is_file()
        text = _raw(name)
        assert "{schema}" in text
        assert text.endswith("\n") and not text.endswith("\n\n")


def test_chat_prompt_renders_schema() -> None:
    out = render_prompt(CHAT_PROMPT, ChatRead)
    assert json.dumps(ChatRead.model_json_schema()) in out
    assert "{schema}" not in out


def test_document_prompt_renders_schema() -> None:
    out = render_prompt(DOCUMENT_PROMPT, DocumentRead)
    assert json.dumps(DocumentRead.model_json_schema()) in out
    assert "{schema}" not in out


def test_chat_prompt_rules() -> None:
    text = render_prompt(CHAT_PROMPT, ChatRead)
    low = text.lower()
    assert '"right"' in text and "phone's owner" in low
    assert "exactly as written" in low
    assert "do not correct spelling" in low
    assert "do not guess" in low
    for field in ("is_chat", "other_party", "unreadable"):
        assert field in text


def test_document_prompt_rules() -> None:
    text = render_prompt(DOCUMENT_PROMPT, DocumentRead)
    low = text.lower()
    assert "exactly as written" in low
    assert "guess" in low
    assert "is_document" in text
    assert "unreadable" in text


def test_routing_keys_are_distinct() -> None:
    chat = render_prompt(CHAT_PROMPT, ChatRead)
    doc = render_prompt(DOCUMENT_PROMPT, DocumentRead)
    assert "chat conversation" in chat and "chat conversation" not in doc
    assert "of a document" in doc and "of a document" not in chat
