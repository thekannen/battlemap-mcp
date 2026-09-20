"""Find objects that intrude on architecture, before anyone sees it in a render.

Three placement failures in one build motivated this, and every one of them
looked fine in the element counts and in the response to the call that made it:
a hearth pushed clean through an exterior wall, a counter overlapped with its
own neighbour, and a window buried behind a chimney breast.

What counts as a defect here is much narrower than "things overlap", and that
distinction is the whole design:

- a tankard on a table, bread on a bench, a lantern on a post — LEGITIMATE.
  Objects overlapping each other is how dressing a surface works, and reporting
  it would bury the real findings under every correctly-dressed table in the
  map. Object-versus-object is deliberately not checked at all.
- an object straddling a wall, or sitting in a doorway or across a window —
  DEFECTS. That is architecture, and furniture does not pass through it.

Footprints are rotation-aware oriented boxes. The bridge's `fit_elements`
bounds are not: a hearth turned -90 degrees reports a 714-wide box for a
350-wide footprint, so a checker built on those would flag every rotated object
on the map and be worth nothing.

Everything here is pure geometry over what the bridge already returns. Nothing
is placed, moved or changed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# How far an object may cross a wall's centre line before it counts as
# intruding. Furniture is *supposed* to sit flush against walls, and a wall has
# real thickness, so only genuine penetration well past the line on BOTH sides
# is a defect.
DEFAULT_TOLERANCE = 24.0

# A portal is an opening of width 2*radius. An object is treated as blocking it
# once its footprint reaches this fraction of the radius from the portal's
# centre. Zero would report only dead-centre hits; 1.0 would flag a chair
# standing politely beside a door.
PORTAL_COVERAGE = 0.5


@dataclass(frozen=True)
class Box:
    """An object's footprint as an oriented rectangle, in woxels."""

    cx: float
    cy: float
    half_w: float
    half_h: float
    rotation_deg: float

    def corners(self) -> list[tuple[float, float]]:
        theta = math.radians(self.rotation_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        return [
            (self.cx + dx * cos_t - dy * sin_t, self.cy + dx * sin_t + dy * cos_t)
            for dx, dy in (
                (-self.half_w, -self.half_h),
                (self.half_w, -self.half_h),
                (self.half_w, self.half_h),
                (-self.half_w, self.half_h),
            )
        ]

    def bounds(self) -> list[float]:
        """Axis-aligned extent AFTER rotation: where the object actually reaches.

        Reported alongside a finding because "it crosses this wall" leaves the
        caller asking how far, and the asset's own size does not answer that
        once it is turned.
        """
        corners = self.corners()
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return [min(xs), min(ys), max(xs), max(ys)]

    def distance_to(self, px: float, py: float) -> float:
        """Distance from a point to the nearest part of the box; 0.0 inside it.

        Done in the box's own frame, which is what makes rotation free.
        """
        theta = math.radians(-self.rotation_deg)
        dx, dy = px - self.cx, py - self.cy
        local_x = dx * math.cos(theta) - dy * math.sin(theta)
        local_y = dx * math.sin(theta) + dy * math.cos(theta)
        outside_x = max(0.0, abs(local_x) - self.half_w)
        outside_y = max(0.0, abs(local_y) - self.half_h)
        return math.hypot(outside_x, outside_y)


def box_for(element: dict) -> Box | None:
    """Footprint from an element's position, texture size, scale and rotation.

    Returns None when the bridge gave no `texture_size` — an older mod, or an
    element whose texture could not be resolved. The caller reports those
    separately rather than treating them as clean, because "not measured" and
    "measured and fine" are different answers.
    """
    position = element.get("position")
    size = element.get("texture_size")
    if not position or not size or len(size) < 2 or len(position) < 2:
        return None
    scale = abs(float(element.get("scale") or 1.0))
    width = float(size[0]) * scale
    height = float(size[1]) * scale
    if width <= 0 or height <= 0:
        return None
    return Box(
        cx=float(position[0]),
        cy=float(position[1]),
        half_w=width / 2.0,
        half_h=height / 2.0,
        rotation_deg=float(element.get("rotation") or 0.0),
    )


@dataclass(frozen=True)
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float
    wall_id: int


def _segments(walls: list[dict]) -> list[Segment]:
    out: list[Segment] = []
    for wall in walls:
        points = wall.get("points") or []
        wall_id = int(wall.get("id", -1))
        if len(points) < 2:
            continue
        for index in range(len(points) - 1):
            (x0, y0), (x1, y1) = points[index], points[index + 1]
            out.append(Segment(float(x0), float(y0), float(x1), float(y1), wall_id))
        if wall.get("loop"):
            (x0, y0), (x1, y1) = points[-1], points[0]
            out.append(Segment(float(x0), float(y0), float(x1), float(y1), wall_id))
    return out


def _straddles(box: Box, segment: Segment, tolerance: float) -> bool:
    """True when the box has real area on BOTH sides of a wall, alongside it.

    Two conditions, and both matter:

    - across the wall, corners must fall beyond `tolerance` on either side.
      Furniture placed correctly sits entirely on one side, flush; that is not
      a defect and must never be reported as one.
    - along the wall, the footprint must actually overlap the segment's span.
      Without this the test uses the wall's infinite line, so a table sitting
      well past the end of a wall stub — on the imaginary continuation of it —
      reads as crossing a wall that is not there.
    """
    dx, dy = segment.x1 - segment.x0, segment.y1 - segment.y0
    length = math.hypot(dx, dy)
    if length == 0:
        return False
    ux, uy = dx / length, dy / length

    corners = box.corners()
    across = [((cx - segment.x0) * -uy + (cy - segment.y0) * ux) for cx, cy in corners]
    if not (min(across) < -tolerance and max(across) > tolerance):
        return False

    along = [((cx - segment.x0) * ux + (cy - segment.y0) * uy) for cx, cy in corners]
    return max(along) > 0.0 and min(along) < length


def find_intrusions(
    objects: list[dict],
    walls: list[dict],
    portals: list[dict],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    portal_coverage: float = PORTAL_COVERAGE,
) -> dict:
    """Report objects that cross a wall or block a portal. Read-only."""
    segments = _segments(walls)
    crossing: list[dict] = []
    blocking: list[dict] = []
    unmeasurable: list[dict] = []

    for element in objects:
        element_id = int(element.get("id", -1))
        asset = str(element.get("asset", ""))
        box = box_for(element)
        if box is None:
            unmeasurable.append({"id": element_id, "asset": asset})
            continue

        hit_walls = sorted(
            {segment.wall_id for segment in segments if _straddles(box, segment, tolerance)}
        )
        if hit_walls:
            crossing.append(
                {
                    "id": element_id,
                    "asset": asset,
                    "position": [box.cx, box.cy],
                    "asset_size_woxels": [box.half_w * 2, box.half_h * 2],
                    "rotation": box.rotation_deg,
                    "bounds": box.bounds(),
                    "wall_ids": hit_walls,
                }
            )

        covered = []
        for portal in portals:
            position = portal.get("position")
            if not position or len(position) < 2:
                continue
            radius = float(portal.get("radius") or 64.0)
            distance = box.distance_to(float(position[0]), float(position[1]))
            if distance <= radius * portal_coverage:
                covered.append(int(portal.get("id", -1)))
        if covered:
            blocking.append(
                {
                    "id": element_id,
                    "asset": asset,
                    "position": [box.cx, box.cy],
                    "portal_ids": sorted(covered),
                }
            )

    return {
        "checked": len(objects),
        "tolerance_woxels": tolerance,
        "crossing_walls": crossing,
        "blocking_portals": blocking,
        "unmeasurable": unmeasurable,
        "ok": not crossing and not blocking,
        "note": (
            "Objects overlapping each other is not reported: a tankard on a "
            "table is correct placement. Only architecture is protected here."
        ),
    }
