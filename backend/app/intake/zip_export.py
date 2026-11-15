"""WhatsApp .zip export: the chat text inside (media files are ignored)."""

MAX_TEXT_BYTES = 5 * 1024 * 1024  # uncompressed; refuses zip bombs


def is_zip(data: bytes) -> bool:
    """Zip magic bytes (a .docx is a zip too: callers check docx first)."""
    return data.startswith(b"PK\x03\x04")


def read_zip_export(data: bytes) -> str:
    """The UTF-8 text of the chat `.txt` inside the zip. Raises `ocr.OCRError(ocr.ZIP)`."""
    raise NotImplementedError("WS C: read_zip_export")
