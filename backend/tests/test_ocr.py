"""Screenshot and document OCR (FakeLLM only, no network)."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.llm import FakeLLM
from app.intake import images, ocr

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
CHAT_KEY = "chat screenshot"  # appears in the chat prompt


def chat(lines: list[dict[str, Any]], **fields: Any) -> str:
    return json.dumps({"is_chat": True, "app": "whatsapp", "lines": lines, **fields})


def line(side: str, text: str, **fields: Any) -> dict[str, Any]:
    return {"side": side, "text": text, **fields}


class QueueLLM(FakeLLM):
    """Returns queued replies in order and records every call."""

    def __init__(self, replies: list[str]) -> None:
        super().__init__()
        self.replies = list(replies)

    async def describe_image(self, image: bytes, prompt: str) -> str:
        await super().describe_image(image, prompt)
        return self.replies.pop(0)


class SlowLLM(FakeLLM):
    async def describe_image(self, image: bytes, prompt: str) -> str:
        await asyncio.sleep(1)
        return "{}"


class BrokenLLM(FakeLLM):
    async def describe_image(self, image: bytes, prompt: str) -> str:
        await super().describe_image(image, prompt)
        raise RuntimeError("secret-key-123 leaked in message")


async def read(llm: FakeLLM, student: str | None = "Sam") -> tuple[str, list[Any]]:
    return await ocr.read_chat(PNG, llm, student, "ev_1")


def vision_calls(llm: FakeLLM) -> list[dict[str, Any]]:
    return [c for c in llm.calls if c["method"] == "describe_image"]


def test_prompts_render_with_schema() -> None:
    assert "is_chat" in ocr.render_prompt(ocr.CHAT_PROMPT, ocr.ChatRead)
    assert "is_document" in ocr.render_prompt(ocr.DOCUMENT_PROMPT, ocr.DocumentRead)


async def test_o1_right_is_student_left_is_agent() -> None:
    llm = FakeLLM(
        default=chat(
            [
                line("left", "Hi, the flat is ready  ", time="14:02"),
                line("right", "Can I view it first?"),
            ],
            other_party="Lettings Team",
        )
    )
    transcript, messages = await read(llm)
    assert [m.sender for m in messages] == ["agent", "student"]
    assert [m.text for m in messages] == ["Hi, the flat is ready", "Can I view it first?"]
    assert {m.channel for m in messages} == {"whatsapp"}
    assert {m.evidence_id for m in messages} == {"ev_1"}
    assert len({m.id for m in messages}) == 2
    assert transcript.splitlines() == [
        "[14:02] Lettings Team: Hi, the flat is ready",
        "You: Can I view it first?",
    ]
    assert all(m.text in transcript for m in messages)


async def test_agent_label_defaults_to_agent() -> None:
    llm = FakeLLM(default=chat([line("left", "Hello")]))
    transcript, _ = await read(llm)
    assert transcript == "Agent: Hello"


async def test_o2_shown_name_matching_student_wins_even_on_the_left() -> None:
    llm = FakeLLM(
        default=chat(
            [
                line("left", "Sent the deposit", name="Sam Reed"),
                line("right", "Please pay today", name="Mark Evans"),
            ]
        )
    )
    transcript, messages = await read(llm, student="Sam")
    assert [m.sender for m in messages] == ["student", "agent"]
    assert transcript.splitlines() == ["You: Sent the deposit", "Mark Evans: Please pay today"]


async def test_o3_group_with_no_match_is_unknown() -> None:
    llm = FakeLLM(
        default=chat(
            [
                line("left", "Who is viewing?", name="Priya"),
                line("left", "Me", name="Mark Evans"),
                line("right", "My bubble, no name"),
                line("left", "Nameless on the left"),
            ]
        )
    )
    transcript, messages = await read(llm, student="Sam")
    assert [m.sender for m in messages] == ["unknown", "unknown", "student", "unknown"]
    assert transcript.splitlines()[0] == "Priya: Who is viewing?"
    assert transcript.splitlines()[3] == "Unknown: Nameless on the left"


async def test_single_name_uses_side_rule() -> None:
    llm = FakeLLM(
        default=chat(
            [line("left", "Hi", name="Mark Evans"), line("right", "Hello", name="Mark Evans")]
        )
    )
    _, messages = await read(llm, student=None)
    assert [m.sender for m in messages] == ["agent", "student"]


async def test_unknown_side_is_unknown() -> None:
    llm = FakeLLM(default=chat([line("unknown", "Hmm")]))
    _, messages = await read(llm)
    assert messages[0].sender == "unknown"


async def test_blank_lines_are_skipped() -> None:
    llm = FakeLLM(default=chat([line("left", "   "), line("left", "Real text")]))
    transcript, messages = await read(llm)
    assert [m.text for m in messages] == ["Real text"]
    assert transcript == "Agent: Real text"


async def test_not_a_chat() -> None:
    llm = FakeLLM(default=json.dumps({"is_chat": False}))
    with pytest.raises(ocr.OCRError) as caught:
        await read(llm)
    assert caught.value.reason == ocr.NOT_A_CHAT


@pytest.mark.parametrize(
    "reply",
    [
        chat([line("left", "blurry")], unreadable=True),
        chat([]),
        chat([line("left", "   ")]),
    ],
)
async def test_unreadable(reply: str) -> None:
    with pytest.raises(ocr.OCRError) as caught:
        await read(FakeLLM(default=reply))
    assert caught.value.reason == ocr.UNREADABLE


async def test_o5_invalid_then_valid_retries_once() -> None:
    llm = QueueLLM(["this is not json", chat([line("left", "Hello")])])
    _, messages = await read(llm)
    assert [m.text for m in messages] == ["Hello"]
    calls = vision_calls(llm)
    assert len(calls) == 2
    assert "Your previous reply was invalid" in calls[1]["prompt"]
    assert "Your previous reply was invalid" not in calls[0]["prompt"]


async def test_o5_schema_invalid_json_also_retries() -> None:
    llm = QueueLLM([json.dumps({"is_chat": "maybe"}), chat([line("left", "Hello")])])
    await read(llm)
    calls = vision_calls(llm)
    assert len(calls) == 2
    # The hint names the bad field, and never echoes the model's own reply back.
    hint = calls[1]["prompt"].split("Your previous reply was invalid:")[1]
    assert "is_chat" in hint
    assert "maybe" not in hint


async def test_o6_invalid_twice_is_an_error_not_a_crash() -> None:
    llm = QueueLLM(["nope", "still nope"])
    with pytest.raises(ocr.OCRError) as caught:
        await read(llm)
    assert caught.value.reason == ocr.LLM_ERROR
    assert len(vision_calls(llm)) == 2


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16, images.UNSUPPORTED),
        (b"random bytes, not an image", images.UNSUPPORTED),
        (b"", images.EMPTY),
        (PNG + b"\x00" * images.MAX_IMAGE_BYTES, images.TOO_BIG),
    ],
)
async def test_o7_bad_images_never_reach_the_llm(data: bytes, reason: str) -> None:
    llm = FakeLLM(default=chat([line("left", "Hello")]))
    with pytest.raises(ocr.OCRError) as chat_error:
        await ocr.read_chat(data, llm, "Sam", "ev_1")
    with pytest.raises(ocr.OCRError) as doc_error:
        await ocr.read_document(data, llm)
    assert chat_error.value.reason == reason == doc_error.value.reason
    assert llm.calls == []


async def test_o15_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "VISION_TIMEOUT_S", 0.01)
    with pytest.raises(ocr.OCRError) as caught:
        await read(SlowLLM())
    assert caught.value.reason == ocr.TIMEOUT
    with pytest.raises(ocr.OCRError) as doc_caught:
        await ocr.read_document(PNG, SlowLLM())
    assert doc_caught.value.reason == ocr.TIMEOUT


async def test_timeout_on_the_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "VISION_TIMEOUT_S", 0.05)

    class SecondSlow(QueueLLM):
        async def describe_image(self, image: bytes, prompt: str) -> str:
            if self.replies:
                return await super().describe_image(image, prompt)
            await asyncio.sleep(1)
            return "{}"

    with pytest.raises(ocr.OCRError) as caught:
        await read(SecondSlow(["not json"]))
    assert caught.value.reason == ocr.TIMEOUT


async def test_llm_exception_is_llm_error_without_leaking(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"), pytest.raises(ocr.OCRError) as caught:
        await read(BrokenLLM())
    assert caught.value.reason == ocr.LLM_ERROR
    assert "secret-key-123" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize(
    ("app", "channel"),
    [
        ("whatsapp", "whatsapp"),
        ("imessage", "sms"),
        ("sms", "sms"),
        ("email", "email"),
        ("spareroom", "platform"),
        ("openrent", "platform"),
        ("facebook", "platform"),
        ("instagram", "platform"),
        ("other", "other"),
    ],
)
async def test_channel_mapping(app: str, channel: str) -> None:
    llm = FakeLLM(default=chat([line("left", "Hi")], app=app))
    _, messages = await read(llm)
    assert messages[0].channel == channel


@pytest.mark.parametrize(
    ("shown", "expected"),
    [
        ("15/11/2026 14:02", datetime(2026, 11, 15, 14, 2, tzinfo=UTC)),
        ("15/11/2026, 14:02", datetime(2026, 11, 15, 14, 2, tzinfo=UTC)),
        ("[15/11/2026, 14:02:09]", datetime(2026, 11, 15, 14, 2, 9, tzinfo=UTC)),
        ("2026-11-15 14:02", datetime(2026, 11, 15, 14, 2, tzinfo=UTC)),
        ("02/03/2026 09:00", datetime(2026, 3, 2, 9, 0, tzinfo=UTC)),  # day first
        ("14:02", None),
        ("Yesterday 09:15", None),
        ("15/11/2026", None),
        ("31/02/2026 10:00", None),
        ("15/11/26 14:02", None),
        ("", None),
        (None, None),
    ],
)
async def test_sent_at_only_for_full_date_and_time(shown: str | None, expected: Any) -> None:
    llm = FakeLLM(default=chat([line("left", "Hi", time=shown)]))
    transcript, messages = await read(llm)
    assert messages[0].sent_at == expected
    if shown:
        assert transcript.startswith(f"[{shown}] ")  # the raw time stays in the transcript


async def test_read_document_returns_stripped_text() -> None:
    reply = json.dumps({"is_document": True, "text": "\n  TENANCY AGREEMENT\nRent: £850\n "})
    text = await ocr.read_document(PNG, FakeLLM(default=reply))
    assert text == "TENANCY AGREEMENT\nRent: £850"


async def test_read_document_not_a_document() -> None:
    with pytest.raises(ocr.OCRError) as caught:
        await ocr.read_document(PNG, FakeLLM(default=json.dumps({"is_document": False})))
    assert caught.value.reason == ocr.NOT_A_DOCUMENT


@pytest.mark.parametrize(
    "reply",
    [
        json.dumps({"is_document": True, "text": "blur", "unreadable": True}),
        json.dumps({"is_document": True, "text": "  \n "}),
    ],
)
async def test_read_document_unreadable(reply: str) -> None:
    with pytest.raises(ocr.OCRError) as caught:
        await ocr.read_document(PNG, FakeLLM(default=reply))
    assert caught.value.reason == ocr.UNREADABLE


async def test_read_document_retries_once() -> None:
    llm = QueueLLM(["garbage", json.dumps({"is_document": True, "text": "Hello"})])
    assert await ocr.read_document(PNG, llm) == "Hello"
    assert len(vision_calls(llm)) == 2
