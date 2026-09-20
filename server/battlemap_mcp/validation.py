"""Pre-flight semantic validation.

FastMCP already rejects wrong types from the tools' annotations, so nothing here
re-checks types. These are the rules annotations cannot express: ranges, enums,
formats, and cross-field exclusivity. Failing here means the socket was never
touched, which is why these raise ValidationError rather than a bridge error.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .errors import ValidationError

# `\Z` (not `$`) so a value like "#ffffff\n" doesn't slip through: `$` matches
# before a trailing newline as well as at true end-of-string.
_HEX = re.compile(r"^#[0-9a-fA-F]{6}\Z")


def require_one_of(*, rect: Any, points: Any) -> None:
    if (rect is None) == (points is None):
        raise ValidationError("provide exactly one of 'rect' or 'points'")


def require_hex_color(value: str, field: str) -> None:
    if value == "":
        return  # empty means "use the default tint"
    if not _HEX.match(value):
        raise ValidationError(f"{field} must be '#rrggbb', got {value!r}")


def require_choice(value: Any, allowed: Sequence[Any], field: str) -> None:
    if value not in allowed:
        raise ValidationError(f"{field} must be one of {list(allowed)}, got {value!r}")


def require_positive(value: float, field: str) -> None:
    if not math.isfinite(value):
        raise ValidationError(f"{field} must be finite, got {value!r}")
    if value <= 0:
        raise ValidationError(f"{field} must be greater than 0, got {value!r}")


def require_finite(value: float | None, field: str) -> None:
    """Reject nan and inf on values that reach the map as coordinates or energy.

    GDScript has no try/catch, so a non-finite number does not raise on the mod
    side — it propagates into a node's position or a light's energy and produces
    an element that cannot be seen, selected or framed. `fit_elements` then
    computes a nan bounding box and the camera goes somewhere unrecoverable.
    None passes: an omitted optional coordinate means "use the default".
    """
    if value is None:
        return
    if not math.isfinite(value):
        raise ValidationError(f"{field} must be a finite number, got {value!r}")


# A polyline long enough to be pathological. Real walls and paths are tens of
# points; this exists so a request cannot hand the editor an unbounded loop.
MAX_POINTS = 4000


def require_points(points: Any, field: str = "points", *, minimum: int = 2) -> None:
    """Every point must be exactly two finite numbers."""
    if not isinstance(points, list):
        raise ValidationError(
            f"{field} must be a list of [x, y] pairs, got {type(points).__name__}"
        )
    if len(points) < minimum:
        raise ValidationError(f"{field} needs at least {minimum} [x, y] pairs, got {len(points)}")
    if len(points) > MAX_POINTS:
        raise ValidationError(f"{field} is capped at {MAX_POINTS} points, got {len(points)}")
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValidationError(f"{field}[{index}] must be exactly [x, y], got {point!r}")
        for axis, value in zip(("x", "y"), point, strict=True):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"{field}[{index}] {axis} must be a number, got {value!r}")
            if not math.isfinite(float(value)):
                raise ValidationError(f"{field}[{index}] {axis} must be finite, got {value!r}")


def require_rect(rect: Any, field: str = "rect") -> None:
    """[x, y, w, h] of finite numbers, with width and height above zero."""
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise ValidationError(f"{field} must be exactly [x, y, w, h], got {rect!r}")
    for name, value in zip(("x", "y", "w", "h"), rect, strict=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"{field} {name} must be a number, got {value!r}")
        if not math.isfinite(float(value)):
            raise ValidationError(f"{field} {name} must be finite, got {value!r}")
    if float(rect[2]) <= 0 or float(rect[3]) <= 0:
        raise ValidationError(
            f"{field} width and height must be greater than 0, got {rect[2]!r} x {rect[3]!r}"
        )


SMART_TILE_CATEGORIES = ("Smart Tiles", "Smart Tiles Double")


# Names Windows reserves for devices, with or without an extension:
# "CON.dungeondraft_map" opens the console, not a file.
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
# Illegal in a Windows filename. ':' is the dangerous one: "C:name" is
# drive-relative, so joining it to a save directory on D: yields a path on C:,
# and "name:stream" addresses an NTFS alternate data stream.
_WINDOWS_ILLEGAL = frozenset('<>:"/\\|?*')
_MAX_FILENAME_BYTES = 255


def require_bare_filename(value: str, field: str = "filename") -> str:
    """A name that is a single file in its directory on every supported OS.

    Rejecting '/' and '\\' is not enough on Windows, where a colon makes a name
    drive-relative or selects a data stream. The rule is the same on every
    platform, so a name that works on the maintainer's Mac cannot escape a save
    directory on a user's Windows machine. Returns the stripped name.
    """
    name = value.strip()
    if not name:
        raise ValidationError(f"{field} is required")
    bad = sorted({ch for ch in name if ch in _WINDOWS_ILLEGAL})
    if bad:
        raise ValidationError(f"{field} must be a bare name; it may not contain {bad}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise ValidationError(f"{field} may not contain control characters")
    if name.startswith("."):
        raise ValidationError(f"{field} may not start with '.'")
    if name.endswith((".", " ")):
        # Windows silently strips these, so "map." and "map" are the same file.
        raise ValidationError(f"{field} may not end with '.' or a space")
    if name.split(".", 1)[0].rstrip(" ").upper() in _WINDOWS_RESERVED:
        raise ValidationError(f"{field} {name!r} is a reserved device name on Windows")
    if len(name.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValidationError(f"{field} is longer than {_MAX_FILENAME_BYTES} bytes")
    return name


def require_within(directory: Path, candidate: Path, field: str = "filename") -> Path:
    """`candidate`, resolved, provided it is a direct child of `directory`.

    The name rule above should make this unreachable. It is here so that a gap
    in that rule — or a symlinked save directory entry — fails closed instead
    of writing somewhere the caller never named.
    """
    root = directory.resolve()
    resolved = candidate.resolve()
    if resolved.parent != root:
        raise ValidationError(f"{field} resolves outside the save directory ({resolved}); refusing")
    return resolved


def reject_smart_tiles(category: str, field: str = "category") -> None:
    """Refuse a smart tileset where a pattern fill is what will actually be drawn."""
    if category in SMART_TILE_CATEGORIES:
        raise ValidationError(
            f"{field}={category!r} cannot be drawn as a pattern. A smart tileset "
            "is an atlas of edge/corner variants that only Dungeondraft's tile "
            "layer can select between, so a pattern fill renders SOLID BLACK "
            "with no error. Use category='Simple Tiles' or 'Materials' instead "
            "— list_assets(category='Simple Tiles') has plank, stone, brick and "
            "cobble equivalents."
        )
