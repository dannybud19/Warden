"""Image format sniffing (magic bytes, never the filename) and upload limits."""

from typing import Literal

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # vision APIs reject larger images

ImageKind = Literal["png", "jpeg", "webp", "gif", "heic", "tiff", "other"]

UNSUPPORTED = "unsupported"
TOO_BIG = "too_big"
EMPTY = "empty"


class ImageError(Exception):
    """An image the vision model cannot take. `reason` is one of the constants above."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def kind_of(data: bytes) -> ImageKind:
    """The image format from its magic bytes; `other` for anything that is not an image."""
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"GIF8"):
        return "gif"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "heic"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    return "other"


def is_image(data: bytes) -> bool:
    """True for any image format above, including the ones we cannot read (HEIC, TIFF)."""
    return kind_of(data) != "other"


def check(data: bytes) -> None:
    """Raise ImageError unless the vision model can take `data` (format and size)."""
    raise NotImplementedError("WS C: images.check")
