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
  map. Object-versus-object is deliberately not a defect here.
- an object straddling a wall, or sitting in a doorway or across a window —
  DEFECTS. That is architecture, and furniture does not pass through it.

Footprints are rotation-aware oriented boxes. The bridge's `fit_elements`
bounds are not: a hearth turned -90 degrees reports a 714-wide box for a
350-wide footprint, so a checker built on those would flag every rotated object
on the map and be worth nothing.

The advice checks further down (stacks, adrift fixtures, surface overflow,
lone kit parts) do compare objects with each other, but each one only for a
narrow, named pattern, and none of them changes `ok`.

Everything here is pure geometry over what the bridge already returns. Nothing
is placed, moved or changed.
"""

from __future__ import annotations

import math
import re
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


def opaque_box_for(element: dict) -> Box | None:
    """The footprint of an object's visible pixels, not its whole canvas.

    The bridge reports `opaque_rect` as [x, y, w, h] in texture pixels. Its
    centre is offset from the canvas centre, and that offset turns and scales
    with the object. None when the bridge sent no rect.
    """
    box = box_for(element)
    rect = element.get("opaque_rect")
    size = element.get("texture_size")
    if box is None or not rect or not size or len(rect) < 4:
        return None
    if float(rect[2]) <= 0 or float(rect[3]) <= 0:
        return None
    scale = float(element.get("scale") or 1.0)
    magnitude = abs(scale)
    # A mirrored object (negative scale) carries its art's offset to the other side.
    off_x = (float(rect[0]) + float(rect[2]) / 2.0 - float(size[0]) / 2.0) * scale
    off_y = (float(rect[1]) + float(rect[3]) / 2.0 - float(size[1]) / 2.0) * magnitude
    theta = math.radians(box.rotation_deg)
    return Box(
        cx=box.cx + off_x * math.cos(theta) - off_y * math.sin(theta),
        cy=box.cy + off_x * math.sin(theta) + off_y * math.cos(theta),
        half_w=float(rect[2]) * magnitude / 2.0,
        half_h=float(rect[3]) * magnitude / 2.0,
        rotation_deg=box.rotation_deg,
    )


def add_bounds(element: dict) -> dict:
    """Give an element `bounds` and, when known, `opaque_bounds`: [x0, y0, x1, y1]
    in woxels, after scale and rotation. The opaque ones are what the art
    actually covers, which is what a bed, rug or shadow should be fitted to."""
    box = box_for(element)
    if box is not None:
        element["bounds"] = [round(v, 1) for v in box.bounds()]
    opaque = opaque_box_for(element)
    if opaque is not None:
        element["opaque_bounds"] = [round(v, 1) for v in opaque.bounds()]
    element.pop("opaque_rect", None)
    return element


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


WALL_CAP_LAYER = 700
WALL_CAP_NAMES = ("post", "pillar", "column", "beam")


def _wall_vertices(walls: list[dict]) -> list[tuple[float, float]]:
    """Every wall point: the corners and joins a cap would be set over."""
    return [
        (float(point[0]), float(point[1]))
        for wall in walls
        for point in (wall.get("points") or [])
        if len(point) >= 2
    ]


def _is_wall_cap(element: dict, box: Box, junctions: list[tuple[float, float]]) -> bool:
    """A deliberate cap: on a layer above the walls, and over a join or named as one.

    Layer is required either way. A post on the default layer 100 is drawn
    UNDER the wall it crosses, so it is a placement mistake, not a cap.
    """
    try:
        layer = int(element.get("layer", 0) or 0)
    except (TypeError, ValueError):
        return False
    if layer < WALL_CAP_LAYER:
        return False
    name = str(element.get("asset", "")).rsplit("/", 1)[-1].lower()
    if any(word in name for word in WALL_CAP_NAMES):
        return True
    return any(box.distance_to(x, y) == 0.0 for x, y in junctions)


WALL_MOUNTED_NAMES = (
    "wall_",
    "sconce",
    "torch",
    "tapestry",
    "banner",
    "painting",
    "portrait",
    "mirror",
    "curtain",
    "hanging",
    "chimney",
)

# How far past a wall's centre line a mounted fixture may reach on the far
# side. A wall has thickness and a frame has depth; a hearth pushed clean
# through the wall reaches far beyond this and still counts as crossing.
WALL_MOUNT_DEPTH = 64.0


def _is_wall_mounted(asset: str) -> bool:
    name = asset.rsplit("/", 1)[-1].lower()
    return any(word in name for word in WALL_MOUNTED_NAMES)


def _mounting(box: Box, segment: Segment) -> tuple[float, bool]:
    """How far the box reaches past the wall on its smaller side, and whether
    its front (rotation 0 faces down, +y) points to its larger side."""
    dx, dy = segment.x1 - segment.x0, segment.y1 - segment.y0
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    across = [(cx - segment.x0) * nx + (cy - segment.y0) * ny for cx, cy in box.corners()]
    room_side = 1.0 if max(across) >= -min(across) else -1.0
    far_depth = -min(across) if room_side > 0 else max(across)
    theta = math.radians(box.rotation_deg)
    forward_x, forward_y = -math.sin(theta), math.cos(theta)
    faces_room = (forward_x * nx + forward_y * ny) * room_side > 0.0
    return far_depth, faces_room


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
    junctions = _wall_vertices(walls)
    crossing: list[dict] = []
    caps: list[dict] = []
    mounted: list[dict] = []
    blocking: list[dict] = []
    unmeasurable: list[dict] = []

    for element in objects:
        element_id = int(element.get("id", -1))
        asset = str(element.get("asset", ""))
        box = box_for(element)
        if box is None:
            unmeasurable.append({"id": element_id, "asset": asset})
            continue

        hit = [segment for segment in segments if _straddles(box, segment, tolerance)]
        hit_walls = sorted({segment.wall_id for segment in hit})
        if hit_walls:
            finding = {
                "id": element_id,
                "asset": asset,
                "position": [box.cx, box.cy],
                "asset_size_woxels": [box.half_w * 2, box.half_h * 2],
                "rotation": box.rotation_deg,
                "bounds": box.bounds(),
                "wall_ids": hit_walls,
            }
            mounting = [_mounting(box, segment) for segment in hit]
            far_depth = max(depth for depth, _ in mounting)
            if _is_wall_cap(element, box, junctions):
                caps.append(finding)
            elif _is_wall_mounted(asset) and far_depth <= WALL_MOUNT_DEPTH:
                finding["faces_room"] = all(faces for _, faces in mounting)
                mounted.append(finding)
            else:
                crossing.append(finding)

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
        "wall_caps": caps,
        "wall_mounted": mounted,
        "blocking_portals": blocking,
        "unmeasurable": unmeasurable,
        "ok": not crossing and not blocking,
        "note": (
            "Objects overlapping each other is not reported: a tankard on a "
            "table is correct placement. Only architecture is protected here."
        ),
    }


# --- what a viewer calls "thrown on the map" -------------------------------

# Objects big enough that landing on top of each other reads as a mistake
# rather than as dressing. A tankard is ~32 woxels; a crate or a tent is
# several times that, and two of those overlapping is the defect people name.
LARGE_HALF = 48.0

# How much of the smaller footprint must be covered before it is a stack.
STACK_OVERLAP = 0.5

# Fixtures that belong ON a wall. Name-based, so treat a finding as a prompt to
# look: a free-standing brazier is not here, and an oddly named sconce is missed.
WALL_FIXTURES = (
    "torch",
    "sconce",
    "tapestry",
    "banner",
    "painting",
    "portrait",
    "mirror",
    "hearth",
    "fireplace",
    "chimney",
    "curtain",
    "window",
)

# Name PREFIXES for the same: Wall_Lantern, Wall_Shelf and the like. A prefix,
# not a substring, so a ruin's `broken_wall_03` rubble is not taken for one.
WALL_FIXTURE_PREFIXES = ("wall_",)

# A wall fixture may sit this far from a wall's centre line and still be
# mounted: the wall has thickness and the object has depth.
FIXTURE_REACH = 96.0


def _overlap_fraction(one: Box, two: Box) -> float:
    """Shared area over the smaller footprint, from the rotated extents.

    An approximation: it compares axis-aligned bounds AFTER rotation rather
    than intersecting two oriented rectangles. That is enough for advice —
    a rotated crate reports a slightly generous overlap — and it keeps this a
    few lines instead of a polygon clipper.
    """
    a, b = one.bounds(), two.bounds()
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min(
        (a[2] - a[0]) * (a[3] - a[1]),
        (b[2] - b[0]) * (b[3] - b[1]),
    )
    return 0.0 if smaller <= 0 else min(1.0, width * height / smaller)


def _is_large(box: Box) -> bool:
    return min(box.half_w, box.half_h) >= LARGE_HALF


# Enough to show the habit without burying a reply in pairs.
MAX_STACKS = 20


def find_stacks(
    objects: list[dict], *, overlap: float = STACK_OVERLAP, limit: int = MAX_STACKS
) -> list[dict]:
    """Large objects sitting on top of each other on the SAME layer.

    Dressing a surface is how a map is furnished — a tankard on a table, bread
    on a bench — and that is why object-versus-object overlap is not a defect
    in general. Two crates in the same spot on the same layer is different: it
    reads as assets dropped without looking, which is the complaint a viewer
    actually makes. Layers separate the two cases, because something placed ON
    a surface belongs on a higher layer than the surface.

    Deliberate pairs land here too — a spit roast over a campfire, mushrooms
    growing up a stalagmite — because nothing in the geometry tells them from
    a crate dropped inside another. It is advice: look, then decide.
    """
    measured = []
    for element in objects:
        box = box_for(element)
        if box is not None and _is_large(box):
            measured.append((element, box))
    found: list[dict] = []
    for index, (one, box_one) in enumerate(measured):
        for two, box_two in measured[index + 1 :]:
            if int(one.get("layer", 0) or 0) != int(two.get("layer", 0) or 0):
                continue
            share = _overlap_fraction(box_one, box_two)
            if share >= overlap:
                found.append(
                    {
                        "ids": [int(one.get("id", -1)), int(two.get("id", -1))],
                        "assets": [str(one.get("asset", "")), str(two.get("asset", ""))],
                        "layer": int(one.get("layer", 0) or 0),
                        "overlap": round(share, 2),
                        "position": [round(box_one.cx), round(box_one.cy)],
                    }
                )
    # Worst first, so a truncated list still shows the clearest cases.
    found.sort(key=lambda item: item["overlap"], reverse=True)
    return found[:limit]


def _point_segment_distance(px: float, py: float, segment: Segment) -> float:
    dx, dy = segment.x1 - segment.x0, segment.y1 - segment.y0
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - segment.x0, py - segment.y0)
    t = max(0.0, min(1.0, ((px - segment.x0) * dx + (py - segment.y0) * dy) / length_sq))
    return math.hypot(px - (segment.x0 + t * dx), py - (segment.y0 + t * dy))


def _box_segment_distance(box: Box, segment: Segment) -> float:
    """Shortest distance between an oriented box and a wall segment; 0 if they touch."""
    # Work in the box's own frame, where it is an axis-aligned rectangle.
    theta = math.radians(-box.rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def local(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - box.cx, y - box.cy
        return dx * cos_t - dy * sin_t, dx * sin_t + dy * cos_t

    (ax, ay), (bx, by) = local(segment.x0, segment.y0), local(segment.x1, segment.y1)
    # Liang-Barsky: does the segment enter the rectangle at all?
    t0, t1 = 0.0, 1.0
    crosses = True
    for p, q in (
        (-(bx - ax), ax + box.half_w),
        (bx - ax, box.half_w - ax),
        (-(by - ay), ay + box.half_h),
        (by - ay, box.half_h - ay),
    ):
        if p == 0:
            if q < 0:
                crosses = False
                break
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            crosses = False
            break
    if crosses:
        return 0.0
    # Apart, the closest pair involves an end of the segment or a box corner.
    return min(
        box.distance_to(segment.x0, segment.y0),
        box.distance_to(segment.x1, segment.y1),
        *(_point_segment_distance(cx, cy, segment) for cx, cy in box.corners()),
    )


def find_adrift_fixtures(
    objects: list[dict], walls: list[dict], *, reach: float = FIXTURE_REACH
) -> list[dict]:
    """Wall fixtures standing away from any wall.

    A torch floating a tile from the wall, or a hearth that does not meet the
    wall behind it, is one of the first things a viewer notices. Matching is by
    asset NAME, so this is a prompt to look rather than a verdict: read the
    reported distance and decide.
    """
    segments = _segments(walls)
    if not segments:
        return []
    found: list[dict] = []
    for element in objects:
        asset = str(element.get("asset", ""))
        name = asset.rsplit("/", 1)[-1].lower()
        if not (
            any(fixture in name for fixture in WALL_FIXTURES)
            or name.startswith(WALL_FIXTURE_PREFIXES)
        ):
            continue
        box = box_for(element)
        if box is None:
            continue
        nearest = min(_box_segment_distance(box, segment) for segment in segments)
        if nearest > reach:
            found.append(
                {
                    "id": int(element.get("id", -1)),
                    "asset": asset,
                    "position": [round(box.cx), round(box.cy)],
                    "woxels_from_wall": round(nearest),
                }
            )
    return found


# --- a dressed surface: what sits on a table stays on the table -------------

# Furniture whose top is dressed. Name-based like WALL_FIXTURES, so a finding
# is a prompt to look: an oddly named sideboard is missed.
SURFACE_NAMES = (
    "table",
    "desk",
    "counter",
    "workbench",
    "dresser",
    "nightstand",
    "sideboard",
)

# Dressing sits a layer or two above its surface. Anything far higher is a
# ceiling fixture, a beam or a cap hanging over the table, not standing on it.
SURFACE_DRESSING_LAYERS = 300

# How far an item's corner may pass the surface's edge before it overhangs. A
# plate's rim over a table's edge is drawn that way; a book pile half off it
# is not.
SURFACE_OVERHANG = 16.0


def _name(element: dict) -> str:
    return str(element.get("asset", "")).rsplit("/", 1)[-1].lower()


def _layer(element: dict) -> int:
    try:
        return int(element.get("layer", 0) or 0)
    except (TypeError, ValueError):
        return 0


def find_surface_overflow(objects: list[dict], *, overhang: float = SURFACE_OVERHANG) -> list[dict]:
    """Dressing that hangs off the surface it stands on, or outgrows it.

    An item counts as ON a surface when its centre lies inside the surface's
    footprint and it sits one to three layers above it — which is how the
    skills tell a model to stack a cup on a table. Reported when one of its
    corners reaches past every surface it stands on: a book pile wider than its
    table, a board over the table edge, a candle off the desk. Advice: a cloth
    drawn to drape over the edge is reported too, so look before moving it.
    """
    measured = [(element, box_for(element)) for element in objects]
    surfaces = [
        (element, box)
        for element, box in measured
        if box is not None and any(word in _name(element) for word in SURFACE_NAMES)
    ]
    if not surfaces:
        return []
    found: list[dict] = []
    for item, item_box in measured:
        if item_box is None:
            continue
        item_layer = _layer(item)
        below = [
            (surface, box)
            for surface, box in surfaces
            if surface is not item and 0 < item_layer - _layer(surface) <= SURFACE_DRESSING_LAYERS
        ]
        holders = [
            (surface, box)
            for surface, box in below
            if box.distance_to(item_box.cx, item_box.cy) == 0.0
        ]
        if not holders:
            continue
        # Each corner may rest on any surface below it: two tables pushed
        # together hold a runner laid across the join.
        past = max(min(box.distance_to(x, y) for _, box in below) for x, y in item_box.corners())
        if past <= overhang:
            continue
        surface, box = holders[0]
        found.append(
            {
                "id": int(item.get("id", -1)),
                "asset": str(item.get("asset", "")),
                "surface_id": int(surface.get("id", -1)),
                "surface_asset": str(surface.get("asset", "")),
                "overhang_woxels": round(past),
                "larger_than_surface": item_box.half_w * item_box.half_h >= box.half_w * box.half_h,
            }
        )
    return found


# --- multi-part kits: one part on its own reads as broken -------------------

# Some packs draw one piece of furniture as several assets meant to be stacked:
# bedding over a frame, a chimney breast over a hearth slab, a curtain on its
# rod. Each rule is (what the part is, a pattern for the part, a pattern for
# the sibling it needs nearby). Matched on the file name, lower-cased.
KIT_RULES: tuple[tuple[str, str, str], ...] = (
    ("bedding without a bed frame", r"bed_?blanket", r"^(?!.*blanket).*bed(?!side|roll)"),
    ("hearth base without its chimney", r"fireplace.*base", r"fireplace.*chimney"),
    ("chimney without its hearth base", r"fireplace.*chimney", r"fireplace.*base"),
    ("globe without its stand", r"globe.*(?:metal|ring)", r"globe.*brace"),
    ("curtain without its rod", r"curtain.*cloth", r"curtain.*rod"),
    ("window frame without its sill", r"window_frame", r"window_sill"),
)

# How far the sibling may stand from the part: the pieces of a kit overlap, so
# anything a tile away is not the same piece of furniture.
KIT_REACH = 128.0


def _near(one: dict, two: dict, reach: float) -> bool:
    box_one, box_two = box_for(one), box_for(two)
    if box_one is not None and box_two is not None:
        return (
            min(
                box_one.distance_to(box_two.cx, box_two.cy),
                box_two.distance_to(box_one.cx, box_one.cy),
            )
            <= reach
        )
    first, second = one.get("position") or [], two.get("position") or []
    if len(first) < 2 or len(second) < 2:
        return False
    return (
        math.hypot(float(first[0]) - float(second[0]), float(first[1]) - float(second[1]))
        <= reach + 128.0
    )


def find_lone_kit_parts(objects: list[dict], *, reach: float = KIT_REACH) -> list[dict]:
    """Parts of a multi-piece fixture placed without the piece they belong with.

    Bedding alone looks like a comforter on the floor; a hearth slab alone is a
    pale block off the wall; a curtain without its rod renders as a squiggle.
    Name-based, so it only knows the kits in KIT_RULES: read it as a prompt.
    """
    compiled = [
        (label, re.compile(part), re.compile(sibling)) for label, part, sibling in KIT_RULES
    ]
    named = [(element, _name(element)) for element in objects]
    found: list[dict] = []
    for element, name in named:
        for label, part, sibling in compiled:
            if not part.search(name):
                continue
            if any(
                other is not element and sibling.search(other_name) and _near(element, other, reach)
                for other, other_name in named
            ):
                continue
            found.append(
                {
                    "id": int(element.get("id", -1)),
                    "asset": str(element.get("asset", "")),
                    "missing": label,
                }
            )
            break
    return found
