# Intake: uploads to text and messages

`service.py` turns one upload into an `Evidence` (with `extracted_text`) and the `Message`s parsed
from it. It works in two steps, so the slow part never holds the case lock:

| Step | What it does | Lock |
| --- | --- | --- |
| `extract(kind, filename, data, student_name, llm) -> Extracted` | Reads the bytes: text, messages, or an `error` reason. Needs no case | None |
| `attach(case, kind, filename, data, note, extracted)` | Adds the Evidence and its messages (deduped) to the case; stores the raw file only when there is no text; masks the note | Caller holds the case lock |
| `ingest(...)` | Old one-call API (`extract` then `attach`); `llm=None` by default | Caller decides |

`CaseService.add_evidence` calls `extract` first (no lock), then takes the lock only to reload the
case (409 if it was decided meanwhile), `attach` and save. Replies and other uploads to the same case
are never blocked by a vision call. The HTTP request itself still waits for it (about 5 to 15 s for an
image).

## What happens per kind

Images are recognised by their magic bytes, never by the filename (`images.kind_of`).

| Kind | Image (PNG, JPEG, WebP, GIF) | Anything else |
| --- | --- | --- |
| `chat_screenshot` | `ocr.read_chat`: a transcript in `extracted_text` and one `Message` per bubble | Read as a chat export, as below (students sometimes pick the wrong kind) |
| `chat_export` | `ocr.read_chat` (a screenshot uploaded as "chats"); stored as `chat_screenshot` | WhatsApp `.zip` export: the chat `.txt` inside (`zip_export`); a PDF or Word file: its text; else the WhatsApp `.txt` parser. Text that isn't a WhatsApp export becomes one message |
| `contract`, `document`, `listing` | `ocr.read_document`: the verbatim text, no messages | PDF text, Word `.docx` text, or UTF-8 text |
| `email` | `ocr.read_document`, then one email message (sender `agent`) on that text | UTF-8 text as one email message |
| `call_recording` | Unchanged: `audio.transcribe` (stub) | Same |
| `video` | Unchanged: no text | Same |

With `llm=None` (old callers), an image is stored with no text and a log warning. An empty file of
any kind fails with `empty`; a PDF or Word file that can't be parsed fails with `unreadable`.

### Chat screenshots

One vision call per image (`ctx.llm.describe_image`, works with Anthropic and OpenAI-compatible
providers), prompt `prompts/chat_screenshot.md`, JSON validated with Pydantic (`ChatRead`), one retry
on invalid JSON, 40 s timeout per call.

- Senders: right-hand bubbles are the phone's owner (`student`), left-hand bubbles `agent`. A shown
  name that matches the student's name (first-name rule, `whatsapp.student_senders`) is the student
  wherever it sits. A group chat (two or more names, none matching) gives `unknown` except the
  student's own right-hand bubbles.
- Channel from the app: WhatsApp `whatsapp`; iMessage and SMS `sms`; email `email`; SpareRoom,
  OpenRent, Facebook and Instagram `platform`; anything else `other`.
- `sent_at` only when a full date and time are visible; otherwise `None` (the time shown stays in the
  transcript).
- Transcript line: `[<time>] <label>: <text>`, label `You` for the student. `Message.text` is the same
  verbatim text, so a quote matches both.
- Dedupe: a message whose sender and text (lower case, collapsed spaces) already exist from an
  earlier `chat_screenshot` is not added again, so overlapping screenshots don't double-count. The
  transcript of each screenshot keeps everything. Messages from text exports are never deduped.
  Images uploaded as `chat_export` are stored as `chat_screenshot`, so they are deduped too.

## Limits

- Formats: PNG, JPEG, WebP, GIF. HEIC/HEIF, TIFF and anything else is refused with a message.
- Size: 5 MB per image (vision APIs reject larger). Zip exports: the chat text must be under 5 MB
  uncompressed; media files in the zip are ignored.
- Text from images is stored as transcribed, with bank and card numbers masked (`redact.mask_sensitive`
  runs at the end of `extract`, on the text and every message, so dedupe compares masked text). The
  raw file is kept only when no text was extracted (a failed read, video), so it can be retried later.

## Failures

A failed read (of an image, an empty file, or a corrupt PDF, Word file or zip) never raises and
never gives a 500: the evidence is saved with `extracted_text=None` and
no messages, no analysis is started (nothing new to read), and the orchestrator tells the student
(`failure_message` in `orchestrator/service.py`):

| Reason | Message |
| --- | --- |
| `not a chat` | That image doesn't look like a chat. If it's a document, upload it as a document instead. |
| `not a document` | I couldn't find any text in that image. If it's a chat, upload it as messages. |
| `unreadable` | I couldn't read that screenshot clearly. Try a sharper screenshot, or export the chat as text. (Documents: try a sharper photo, or upload the PDF or Word file.) |
| `unsupported` | I can't open that image type. Please upload a PNG or JPG screenshot. |
| `too_big` | That image is too large. Please upload a smaller screenshot (under 5 MB). |
| `empty` | That file looks empty. Please try uploading it again. |
| `timeout` | Reading that image took too long. Please try again in a moment. |
| `llm_error` (provider error, or an invalid reply twice) | I couldn't read that image right now. Please try again in a moment. |
| `zip` | Couldn't find the chat text in that zip. Export the chat again "Without media". |

## Run it alone

```bash
cd backend && uv run pytest -q tests/test_ocr.py tests/test_images.py tests/test_zip_export.py \
  tests/test_intake_images.py tests/test_service_ocr.py tests/test_ocr_prompts.py
```

Synthetic screenshots for a live check are in `backend/tests/data/screenshots/` (fake names only).
