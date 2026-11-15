"""Image format sniffing, size limits and the vision client's media types."""

import pytest

from app.core.llm import _sniff_media_type
from app.intake import images

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8 " + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16
TIFF_LE = b"II*\x00" + b"\x00" * 16
TIFF_BE = b"MM\x00*" + b"\x00" * 16


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (PNG, "png"),
        (JPEG, "jpeg"),
        (WEBP, "webp"),
        (GIF, "gif"),
        (HEIC, "heic"),
        (TIFF_LE, "tiff"),
        (TIFF_BE, "tiff"),
        (b"just some text", "other"),
        (b"", "other"),
        (b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8, "other"),
    ],
)
def test_kind_of(data: bytes, kind: str) -> None:
    assert images.kind_of(data) == kind


def test_is_image_includes_formats_we_cannot_read() -> None:
    assert images.is_image(PNG) and images.is_image(HEIC) and images.is_image(TIFF_LE)
    assert not images.is_image(b"%PDF-1.7") and not images.is_image(b"")


@pytest.mark.parametrize("data", [PNG, JPEG, WEBP, GIF])
def test_check_accepts_supported_formats(data: bytes) -> None:
    assert images.check(data) is None


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", images.EMPTY),
        (HEIC, images.UNSUPPORTED),
        (TIFF_LE, images.UNSUPPORTED),
        (b"random bytes that are not an image", images.UNSUPPORTED),
        (PNG + b"\x00" * images.MAX_IMAGE_BYTES, images.TOO_BIG),
    ],
)
def test_check_rejects_with_reason(data: bytes, reason: str) -> None:
    with pytest.raises(images.ImageError) as caught:
        images.check(data)
    assert caught.value.reason == reason


def test_check_allows_exactly_the_limit() -> None:
    assert images.check(PNG + b"\x00" * (images.MAX_IMAGE_BYTES - len(PNG))) is None


def test_o8_webp_and_gif_reach_the_vision_client() -> None:
    assert _sniff_media_type(WEBP) == "image/webp"
    assert _sniff_media_type(GIF) == "image/gif"
    assert _sniff_media_type(PNG) == "image/png"
    assert _sniff_media_type(JPEG) == "image/jpeg"
    with pytest.raises(ValueError):
        _sniff_media_type(HEIC)
