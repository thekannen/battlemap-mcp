"""Check a local PNG before the bridge embeds it in the map (import_image)."""

from __future__ import annotations

import io
from pathlib import Path

from .errors import ValidationError

# The bridge refuses the same limits before it decodes anything.
MAX_BYTES = 32 * 1024 * 1024
MAX_SIDE = 8192
MAX_PIXELS = 16_000_000


def read_png(path: str) -> bytes:
    """The file's bytes, if it is a PNG that decodes within the limits."""
    from PIL import Image

    source = Path(path).expanduser()
    if not source.is_absolute() or not source.is_file() or source.suffix.lower() != ".png":
        raise ValidationError("path must be an absolute path to a local PNG file")
    with source.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValidationError("PNG must not exceed 32 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError("not PNG")
            w, h = image.size
            if max(w, h) > MAX_SIDE or w * h > MAX_PIXELS:
                raise ValueError("exceeds 8192 pixels per side or 16 million pixels")
            image.verify()
        # verify() checks chunks and CRCs but does not decompress the pixels.
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(f"invalid or oversized PNG: {exc}") from exc
    return data
