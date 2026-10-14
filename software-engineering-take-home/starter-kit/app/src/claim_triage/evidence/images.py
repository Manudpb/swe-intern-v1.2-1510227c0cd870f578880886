"""Image intake: validate, downscale, encode.

Downscaling is a budget decision as much as a technical one: input tokens scale with pixels,
and the allowance is shared with coding and grading (constitution Principle III). There is
no cap on the NUMBER of images - the contract sets none and no requirement authorizes
refusing a submission for view count (finding U2). The per-image size limit is the bound.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png"}
MAX_EDGE_PX = 1024
JPEG_QUALITY = 80


class ImageRejected(ValueError):
    """The submitted bytes are not a usable image, or are too large."""


@dataclass(frozen=True)
class PreparedImage:
    media_type: str
    data_b64: str

    def to_block(self) -> dict:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": self.media_type, "data": self.data_b64},
        }


def prepare(raw: bytes, filename: str = "", max_bytes: int = 10_485_760) -> PreparedImage:
    if not raw:
        raise ImageRejected("Empty image upload")
    if len(raw) > max_bytes:
        raise ImageRejected(
            f"Image {filename or '<unnamed>'} is larger than the {max_bytes // 1_048_576} MB limit"
        )
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageRejected(f"Unreadable image {filename or '<unnamed>'}") from exc

    return PreparedImage(
        media_type="image/jpeg",
        data_b64=base64.b64encode(buffer.getvalue()).decode("ascii"),
    )
