"""Sample colours from a rebuild's source image and from an export of the map."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError

MAX_POINTS = 64
MAX_RADIUS = 512.0


def hex_of(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def mean_color(image: Any, x: float, y: float, radius: float) -> tuple[int, int, int] | None:
    """Mean RGB of the square of half-width `radius` pixels around (x, y).

    None when the point lies outside the image. The square is clipped to the
    image and is at least one pixel, so a tiny radius still samples.
    """
    from PIL import ImageStat

    width, height = image.size
    if not (0 <= x < width and 0 <= y < height):
        return None
    half = max(0.5, radius)
    box = (
        max(0, int(x - half)),
        max(0, int(y - half)),
        min(width, max(int(x - half) + 1, int(x + half))),
        min(height, max(int(y - half) + 1, int(y + half))),
    )
    stat = ImageStat.Stat(image.crop(box).convert("RGB"))
    r, g, b = (round(v) for v in stat.mean[:3])
    return (r, g, b)


def validate(points: list[list[float]], radius: float) -> None:
    if not points or len(points) > MAX_POINTS:
        raise ValidationError(f"give 1-{MAX_POINTS} points")
    for point in points:
        if len(point) != 2 or not all(isinstance(v, int | float) for v in point):
            raise ValidationError(f"each point is [x, y] in woxels, got {point!r}")
    if not 0 <= radius <= MAX_RADIUS:
        raise ValidationError(f"radius must be 0-{MAX_RADIUS:g} woxels")


def sample(
    points: list[list[float]],
    radius: float,
    sources: dict[str, tuple[Any, float]],
) -> list[dict[str, Any]]:
    """For each point, each source's mean colour, and the difference of the
    second source from the first (per channel, signed) when there are two.

    sources: label -> (image, pixels per woxel).
    """
    rows = []
    labels = list(sources)
    for x, y in points:
        row: dict[str, Any] = {"at": [x, y]}
        found: dict[str, tuple[int, int, int]] = {}
        for label, (image, scale) in sources.items():
            color = mean_color(image, x * scale, y * scale, radius * scale)
            if color is None:
                row[label] = "outside the image"
            else:
                row[label] = hex_of(color)
                found[label] = color
        if len(labels) == 2 and all(label in found for label in labels):
            first, second = found[labels[0]], found[labels[1]]
            diff = [second[i] - first[i] for i in range(3)]
            row["diff_rgb"] = diff
            row["max_diff"] = max(abs(v) for v in diff)
        rows.append(row)
    return rows
