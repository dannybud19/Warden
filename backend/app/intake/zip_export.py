"""WhatsApp .zip export: the chat text inside (media files are ignored)."""

import io
import zipfile
from pathlib import PurePosixPath

from app.intake import ocr

MAX_TEXT_BYTES = 5 * 1024 * 1024  # uncompressed; refuses zip bombs


def is_zip(data: bytes) -> bool:
    """Zip magic bytes (a .docx is a zip too: callers check docx first)."""
    return data.startswith(b"PK\x03\x04")


def read_zip_export(data: bytes) -> str:
    """The UTF-8 text of the chat `.txt` inside the zip. Raises `ocr.OCRError(ocr.ZIP)`."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = _pick_member(archive)
            if info.file_size > MAX_TEXT_BYTES:
                raise ocr.OCRError(ocr.ZIP)
            with archive.open(info) as handle:
                raw = handle.read(MAX_TEXT_BYTES + 1)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, OSError) as exc:
        # corrupt, encrypted or exotically compressed archives all read as "not a usable zip"
        raise ocr.OCRError(ocr.ZIP) from exc
    if len(raw) > MAX_TEXT_BYTES:
        raise ocr.OCRError(ocr.ZIP)
    return raw.decode("utf-8", errors="replace").removeprefix("\ufeff")


def _pick_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    """The chat `.txt` member: `_chat.txt` if present, else the only `.txt`."""
    candidates = [
        info
        for info in archive.infolist()
        if not info.is_dir()
        and info.filename.lower().endswith(".txt")
        and not info.filename.startswith("__MACOSX/")
    ]
    named = [i for i in candidates if PurePosixPath(i.filename).name == "_chat.txt"]
    if len(named) == 1:
        return named[0]
    if not named and len(candidates) == 1:
        return candidates[0]
    raise ocr.OCRError(ocr.ZIP)
