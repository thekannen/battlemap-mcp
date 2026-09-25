"""Snap points to the grid the user snaps to: the Custom Snap Mod's, or vanilla.

Lievven's Custom Snap Mod (MIT, v1.1.2) is the most widely used Dungeondraft
mod. It snaps the MOUSE CURSOR each frame, so a bridge that places by explicit
coordinates never passes through it: an object the model puts at (1000, 1000)
lands there even on a hex map. This module applies the same snapping to the
model's coordinates instead.

The math is ported from the mod's `snappy_mod.gd` rather than called through
its script, which would couple the bridge to another mod's internals and load
order. It is ported exactly, quirks included, because the promise is "where
the user's own cursor would have put it":

- square snapping takes `floor` and then compares `fmod` with half the
  interval. `fmod` keeps the dividend's sign, so a negative offset position
  never rounds up — it goes to the interval below.
- hex snapping is redblobgames' pixel-to-hex with cube rounding, on hexes
  turned 90 degrees so that it snaps to the VERTICES of the drawn hexes as
  well as their centres.
- Godot's `round` rounds halves away from zero; Python's `round` does not.
- isometric differs by version. In v1.1.2 it is a TODO
  (`snap_isometric_delta` returns nothing). In v1.2.5, which Dungeondraft 1.2
  bundles on Windows and Linux, it returns the horizontal hex snap. Which one
  a user has is asked of the mod itself (see `isometric_matches_hex`), and
  isometric is applied only when the mod's answers match the hex port.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# The mod's GEOMETRY enum, in declaration order.
GEOMETRIES = ("square", "hex_v", "hex_h", "isometric")

# Vanilla Dungeondraft snaps to the tile (256 woxels) or the half tile (128).
TILE = 256.0
HALF_TILE = 128.0


@dataclass(frozen=True)
class SnapGrid:
    """One snapping lattice, in woxels."""

    geometry: str
    interval: tuple[float, float]
    offset: tuple[float, float] = (0.0, 0.0)
    to_corner: bool = True
    source: str = "vanilla"
    # Set only once the mod itself has answered like horizontal hex on
    # isometric (v1.2.5); v1.1.2 answers nothing there.
    isometric_as_hex: bool = False

    @property
    def snaps_like(self) -> str | None:
        if self.geometry in ("square", "hex_v", "hex_h"):
            return self.geometry
        if self.geometry == "isometric" and self.isometric_as_hex:
            return "hex_h"
        return None

    @property
    def supported(self) -> bool:
        return self.snaps_like is not None

    def describe(self) -> dict:
        out = {
            "geometry": self.geometry,
            "interval": list(self.interval),
            "offset": list(self.offset),
            "source": self.source,
            "supported": self.supported,
        }
        if (self.snaps_like or "").startswith("hex"):
            # How the interval is measured across a hex; meaningless on squares.
            out["radial_mode"] = "corner" if self.to_corner else "edge"
        if self.snaps_like and self.snaps_like != self.geometry:
            out["snaps_like"] = self.snaps_like
        return out


# Dungeondraft's own snapping differs by tool. Measured 2026-09-24 on 1.2 by
# feeding the editor synthetic mouse moves and reading
# WorldUI.SnappedPosition and UseHalfSnap with each tool active: Wall, Light,
# Select, Prefab, FloorShape, PatternShape, Roof and Text snap to the full
# tile; Object, Scatter, Portal and Path to the half tile.
VANILLA_TILE = SnapGrid("square", (TILE, TILE), source="vanilla tile")
VANILLA_HALF = SnapGrid("square", (HALF_TILE, HALF_TILE), source="vanilla half tile")


def _gd_round(value: float) -> float:
    """Godot 3's `round`: halves go away from zero."""
    return math.copysign(math.floor(abs(value) + 0.5), value)


def _round_hex(q: float, r: float) -> tuple[float, float]:
    rq, rr, rs = _gd_round(q), _gd_round(r), _gd_round(-q - r)
    q_diff, r_diff, s_diff = abs(rq - q), abs(rr - r), abs(rs + q + r)
    if q_diff > r_diff and q_diff > s_diff:
        rq = -rr - rs
    elif r_diff > s_diff:
        rr = -rq - rs
    return rq, rr


def _hex_size(grid: SnapGrid) -> tuple[float, float]:
    divisor = math.sqrt(3.0) if grid.to_corner else 1.5
    return grid.interval[0] / divisor, grid.interval[1] / divisor


def _snap_square(grid: SnapGrid, dx: float, dy: float) -> tuple[float, float]:
    out = []
    for value, step in ((dx, grid.interval[0]), (dy, grid.interval[1])):
        snapped = math.floor(value / step) * step
        if math.fmod(value, step) > step / 2:
            snapped += step
        out.append(snapped)
    return out[0], out[1]


def _snap_hex_v(grid: SnapGrid, dx: float, dy: float) -> tuple[float, float]:
    sx, sy = _hex_size(grid)
    nx, ny = dx / sx, dy / sy
    q = math.sqrt(3) / 3 * nx - 1.0 / 3 * ny
    r = 2.0 / 3 * ny
    hq, hr = _round_hex(q, r)
    return (math.sqrt(3) * hq + math.sqrt(3) / 2 * hr) * sx, (3.0 / 2 * hr) * sy


def _snap_hex_h(grid: SnapGrid, dx: float, dy: float) -> tuple[float, float]:
    sx, sy = _hex_size(grid)
    nx, ny = dx / sx, dy / sy
    q = 2.0 / 3 * nx
    r = -1.0 / 3 * nx + math.sqrt(3) / 3 * ny
    hq, hr = _round_hex(q, r)
    return (3.0 / 2 * hq) * sx, (math.sqrt(3) / 2 * hq + math.sqrt(3) * hr) * sy


_SNAPPERS = {"square": _snap_square, "hex_v": _snap_hex_v, "hex_h": _snap_hex_h}


def snap(grid: SnapGrid, x: float, y: float) -> tuple[float, float] | None:
    """(x, y) moved to the nearest point of `grid`, or None if it can't snap there.

    Mirrors the mod's get_snapped_position: remove the offset, snap the
    remainder, put the offset back.
    """
    snapper = _SNAPPERS.get(grid.snaps_like or "")
    if snapper is None:
        return None
    ox, oy = grid.offset
    sx, sy = snapper(grid, x - ox, y - oy)
    return round(sx + ox, 3), round(sy + oy, 3)


def _on_grid(grid: SnapGrid, x: float, y: float) -> bool:
    again = snap(grid, x, y)
    return again is not None and abs(again[0] - x) < 0.01 and abs(again[1] - y) < 0.01


def snap_rect(
    grid: SnapGrid, x0: float, y0: float, x1: float, y1: float
) -> tuple[float, float, float, float] | None:
    """An axis-aligned rect whose FOUR corners are grid points, or None."""
    near = snap(grid, x0, y0)
    far = snap(grid, x1, y1)
    if near is None or far is None:
        return None
    ax, ay = near

    def fits(bx: float, by: float) -> bool:
        return bx > ax and by > ay and _on_grid(grid, bx, ay) and _on_grid(grid, ax, by)

    if far[0] <= ax or far[1] <= ay:
        return None  # collapsed on the grid: say so rather than grow it
    if fits(*far):
        return ax, ay, far[0], far[1]
    step_x, step_y = grid.interval[0] / 2, grid.interval[1] / 2
    best = None
    for i in range(-4, 5):
        for j in range(-4, 5):
            cand = snap(grid, x1 + i * step_x, y1 + j * step_y)
            if cand is None or not fits(*cand):
                continue
            dist = math.hypot(cand[0] - x1, cand[1] - y1)
            if best is None or dist < best[0]:
                best = (dist, cand)
    if best is None:
        return None
    return ax, ay, best[1][0], best[1][1]


def snap_delta(grid: SnapGrid, dx: float, dy: float) -> tuple[float, float] | None:
    """An OFFSET rounded to the nearest whole grid step, ignoring the grid's offset.

    A moved group then travels by whole intervals, so what was on the grid
    stays on it. Unlike a position, an offset does NOT copy the mod's square
    quirk: measured live, a -61 move on a 50 grid went -100 with it, and a
    -10 nudge would have become a full step. Offsets are not cursor
    positions, so there is no parity to keep, and nearest is what anyone
    asking for "about 60 up" means. Hex offsets use the mod's own rounding,
    which is already symmetric.
    """
    if grid.geometry == "square":
        sx = _gd_round(dx / grid.interval[0]) * grid.interval[0]
        sy = _gd_round(dy / grid.interval[1]) * grid.interval[1]
        return round(sx, 3), round(sy, 3)
    snapper = _SNAPPERS.get(grid.snaps_like or "")
    if snapper is None:
        return None
    sx, sy = snapper(grid, dx, dy)
    return round(sx, 3), round(sy, 3)


def grid_from_settings(settings: dict) -> SnapGrid | None:
    """The grid a bridge `get_snap_settings` reply describes, or None if inactive.

    `settings` holds the mod's own field names, read live off its tool when
    the bridge could reach it: active_geometry (enum index), snap_interval,
    snap_offset ([x, y]) and radial_mode_to_corner.
    """
    try:
        geometry = GEOMETRIES[int(settings["active_geometry"])]
        interval = settings["snap_interval"]
        offset = settings.get("snap_offset") or [0, 0]
        grid = SnapGrid(
            geometry=geometry,
            interval=(float(interval[0]), float(interval[1])),
            offset=(float(offset[0]), float(offset[1])),
            to_corner=bool(settings.get("radial_mode_to_corner", True)),
            source="Custom Snap Mod",
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if grid.interval[0] <= 0 or grid.interval[1] <= 0:
        return None
    return grid


# Points to ask the mod about when its grid is isometric: spread out, and off
# any lattice line, so a different rule cannot agree with hex by accident.
ISOMETRIC_PROBES = [[37.3, 91.9], [517.1, 211.7], [1203.4, 877.6], [-311.2, 455.5]]


def isometric_matches_hex(grid: SnapGrid, mod_snapped: object) -> bool:
    """Whether the mod's answers for ISOMETRIC_PROBES are its horizontal hex snap.

    True on Custom Snap Mod v1.2.5 (measured live 2026-09-24, Windows); False on
    v1.1.2, whose isometric snap returns nothing, and on any version whose
    isometric rule this port does not know.
    """
    if not isinstance(mod_snapped, list) or len(mod_snapped) != len(ISOMETRIC_PROBES):
        return False
    as_hex = SnapGrid("isometric", grid.interval, grid.offset, grid.to_corner, grid.source, True)
    for probe, theirs in zip(ISOMETRIC_PROBES, mod_snapped, strict=True):
        ours = snap(as_hex, *probe)
        if not isinstance(theirs, list) or len(theirs) != 2 or ours is None:
            return False
        if max(abs(ours[0] - theirs[0]), abs(ours[1] - theirs[1])) > 0.01:
            return False
    return True
