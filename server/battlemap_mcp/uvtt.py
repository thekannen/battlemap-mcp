"""Everything here is offline: parsing, coordinate conversion, joining wall runs
through their doorways, fitting the sight-blocking objects, and preparing the
trace image. server.import_dd2vtt turns the plan into bridge calls.

Format facts, measured on Dungeondraft 1.1/1.2 exports (format 0.3):"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WOXELS_PER_GRID = 256
# Endpoints this close (in grid units) are the same point. Exports round to
# about 1e-6; doorway bounds land exactly on wall ends.
JOIN_TOLERANCE = 0.02
# A wall or light this far outside the region (grid units) still counts, so a
# wall drawn along the map edge is kept.
REGION_MARGIN = 1.0
# The longest side of the trace image handed to Dungeondraft. Larger textures
# load slowly and cost memory for no tracing benefit.
TRACE_MAX_EDGE = 4096
# Decoding is refused above this many pixels (about 1.2 GB as RGBA).
TRACE_MAX_PIXELS = 300_000_000

Point = tuple[float, float]


class UvttError(ValueError):
    """The file is not a Universal VTT export this importer understands."""


@dataclass(frozen=True)
class Uvtt:
    """A parsed export, positions still in the source map's grid units."""

    path: Path
    format: float | None
    origin: Point
    size: Point
    pixels_per_grid: float
    walls: list[list[Point]]
    object_walls: list[list[Point]]
    portals: list[dict[str, Any]]
    lights: list[dict[str, Any]]
    ambient: str | None
    image_span: tuple[int, int] | None

    @property
    def tiles(self) -> tuple[int, int]:
        """The region's size in whole tiles, as set_map_size takes it."""
        return (math.ceil(self.size[0] - 1e-6), math.ceil(self.size[1] - 1e-6))


@dataclass
class Plan:
    """What an import would create, in woxels of the map being built."""

    walls: list[dict[str, Any]] = field(default_factory=list)
    portals: list[dict[str, Any]] = field(default_factory=list)
    lights: list[dict[str, Any]] = field(default_factory=list)
    ambient: str | None = None
    blockers: list[dict[str, Any]] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    joined_doorways: int = 0


def read(path: Path) -> Uvtt:
    """Parse an export without decoding (or even copying) its image."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UvttError(f"cannot read {path}: {exc.strerror or exc}") from exc
    span = _image_span(data)
    text = data if span is None else data[: span[0]] + data[span[1] :]
    try:
        raw = json.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise UvttError(f"{path.name} is not a Universal VTT file (not valid JSON)") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("resolution"), dict):
        raise UvttError(f"{path.name} has no 'resolution'; is it a Universal VTT export?")
    resolution = raw["resolution"]
    origin = _point(resolution.get("map_origin", {"x": 0, "y": 0}), "map_origin")
    size = _point(resolution.get("map_size"), "map_size")
    if size[0] <= 0 or size[1] <= 0:
        raise UvttError(f"map_size must be positive, got {size}")
    ppg = resolution.get("pixels_per_grid")
    if isinstance(ppg, bool) or not isinstance(ppg, int | float) or ppg <= 0:
        raise UvttError(f"pixels_per_grid must be a positive number, got {ppg!r}")
    environment = raw.get("environment")
    if not isinstance(environment, dict):
        environment = {}
    fmt = raw.get("format")
    return Uvtt(
        path=path,
        format=float(fmt) if isinstance(fmt, int | float) and not isinstance(fmt, bool) else None,
        origin=origin,
        size=size,
        pixels_per_grid=float(ppg),
        walls=_polylines(raw.get("line_of_sight"), "line_of_sight"),
        object_walls=_polylines(raw.get("objects_line_of_sight"), "objects_line_of_sight"),
        portals=_records(raw.get("portals"), "portals"),
        lights=_records(raw.get("lights"), "lights"),
        ambient=_argb_to_hex(environment.get("ambient_light")),
        image_span=span,
    )


def _image_span(data: bytes) -> tuple[int, int] | None:
    """Byte offsets of the image string's contents, quotes excluded.

    Base64 holds no quotes or backslashes, so the value ends at the next
    quote. Removing the contents leaves `"image": ""`, still valid JSON.
    """
    key = data.rfind(b'"image"')
    if key < 0:
        return None
    colon = data.find(b":", key + 7)
    if colon < 0 or data[key + 7 : colon].strip():
        return None
    start = colon + 1
    while start < len(data) and data[start] in b" \t\r\n":
        start += 1
    if start >= len(data) or data[start] != ord('"'):
        return None
    end = data.find(b'"', start + 1)
    if end < 0:
        return None
    return (start + 1, end)


def _point(value: Any, name: str) -> Point:
    if not isinstance(value, dict):
        raise UvttError(f"{name} must be an {{x, y}} object, got {value!r}")
    x, y = value.get("x"), value.get("y")
    for part in (x, y):
        if isinstance(part, bool) or not isinstance(part, int | float) or not math.isfinite(part):
            raise UvttError(f"{name} must have finite numeric x and y, got {value!r}")
    return (float(x), float(y))  # type: ignore[arg-type]


def _polylines(value: Any, name: str) -> list[list[Point]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise UvttError(f"{name} must be a list of point lists")
    lines = []
    for line in value:
        if not isinstance(line, list):
            raise UvttError(f"{name} must be a list of point lists")
        points = [_point(p, name) for p in line]
        if len(points) >= 2:
            lines.append(points)
    return lines


def _records(value: Any, name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        raise UvttError(f"{name} must be a list of objects")
    return value


def _argb_to_hex(value: Any) -> str | None:
    """'ffd9c3a0' (alpha first) -> '#d9c3a0'; None when absent or malformed."""
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) == 8:
        text = text[2:]
    if len(text) != 6:
        return None
    try:
        int(text, 16)
    except ValueError:
        return None
    return "#" + text.lower()


def _close(a: Point, b: Point, tolerance: float = JOIN_TOLERANCE) -> bool:
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def join_at_portals(
    walls: list[list[Point]], portals: list[dict[str, Any]]
) -> tuple[list[list[Point]], int]:
    """Rejoin wall runs that the export broke at a doorway.

    Each wall-mounted portal's `bounds` becomes a short run of its own, then
    runs are joined wherever exactly two ends meet. Two doors side by side
    leave no wall between them, and chaining their doorway runs is what joins
    the wall across both. Three or more ends at one point (a T-junction) are
    left apart. A run whose ends meet becomes a closed loop. Returns the runs
    and the number of doorways that ended up inside a wall.
    """
    doorways: list[list[Point]] = []
    for portal in portals:
        if portal.get("freestanding"):
            continue
        bounds = portal.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 2:
            continue
        try:
            a, b = _point(bounds[0], "bounds"), _point(bounds[1], "bounds")
        except UvttError:
            continue
        if not _close(a, b, 1e-6):
            doorways.append([a, b])
    # Each run carries how many doorways it contains and whether any wall.
    runs = [(list(run), 0, True) for run in walls] + [(run, 1, False) for run in doorways]

    def open_ends(point: Point) -> list[tuple[int, bool]]:
        found = []
        for index, (run, _, _) in enumerate(runs):
            if _close(run[0], run[-1]):
                continue
            if _close(run[0], point):
                found.append((index, False))
            if _close(run[-1], point):
                found.append((index, True))
        return found

    merged_any = True
    while merged_any:
        merged_any = False
        for run, _, _ in runs:
            if _close(run[0], run[-1]):
                continue
            for end in (run[-1], run[0]):
                meeting = open_ends(end)
                if len(meeting) != 2 or meeting[0][0] == meeting[1][0]:
                    continue
                (i, i_last), (j, j_last) = meeting
                first = runs[i][0] if i_last else runs[i][0][::-1]
                second = runs[j][0][::-1] if j_last else runs[j][0]
                joined = (first + second[1:], runs[i][1] + runs[j][1], runs[i][2] or runs[j][2])
                for gone in sorted((i, j), reverse=True):
                    runs.pop(gone)
                runs.append(joined)
                merged_any = True
                break
            if merged_any:
                break
    # A doorway that joined no wall has nothing to mount on; drop the stub.
    kept = [_without_collinear(run) for run, _, has_wall in runs if has_wall]
    return kept, sum(doors for _, doors, has_wall in runs if has_wall)


def _without_collinear(run: list[Point]) -> list[Point]:
    """Drop points lying on a straight line between their neighbours.

    Joining through doorways leaves each doorway edge as a vertex; without
    them the rebuilt wall has the corners the original had.
    """
    loop = len(run) > 2 and _close(run[0], run[-1])
    points = run[:-1] if loop else list(run)

    def straight(a: Point, b: Point, c: Point) -> bool:
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        return abs(cross) <= 1e-6 and dot > 0

    changed = True
    while changed and len(points) > (3 if loop else 2):
        changed = False
        count = len(points)
        for k in range(count):
            if not loop and k in (0, count - 1):
                continue
            if straight(points[k - 1], points[k], points[(k + 1) % count]):
                points.pop(k)
                changed = True
                break
    return points + [points[0]] if loop else points


def fit_blocker(polygon: list[Point]) -> dict[str, Any]:
    """Centre, long-axis angle and size of a sight-blocking outline, in woxels.

    Enough to drop a matching blocking object (a boulder, a pillar) on it:
    position it at `center`, rotate it to `rotation`, and scale it to
    `length` x `width`.
    """
    points = [(x * WOXELS_PER_GRID, y * WOXELS_PER_GRID) for x, y in polygon]
    if len(points) > 1 and _close(points[0], points[-1], 1e-6):
        points = points[:-1]
    count = len(points)
    cx = sum(p[0] for p in points) / count
    cy = sum(p[1] for p in points) / count
    sxx = sum((p[0] - cx) ** 2 for p in points) / count
    syy = sum((p[1] - cy) ** 2 for p in points) / count
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in points) / count
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(angle), math.sin(angle)
    along = [(p[0] - cx) * ux + (p[1] - cy) * uy for p in points]
    across = [-(p[0] - cx) * uy + (p[1] - cy) * ux for p in points]
    mid_along = (max(along) + min(along)) / 2
    mid_across = (max(across) + min(across)) / 2
    center = (cx + mid_along * ux - mid_across * uy, cy + mid_along * uy + mid_across * ux)
    return {
        "center": [round(center[0], 1), round(center[1], 1)],
        "rotation": round(math.degrees(angle) % 180, 1),
        "length": round(max(along) - min(along), 1),
        "width": round(max(across) - min(across), 1),
        "points": len(points),
    }


def plan(
    uvtt: Uvtt,
    *,
    walls: bool = True,
    portals: bool = True,
    lights: bool = True,
    ambient: bool = True,
) -> Plan:
    """Convert an export into woxel-space items for the map being built."""
    result = Plan(skipped={"walls": 0, "portals": 0, "lights": 0, "blockers": 0})

    def inside(point: Point) -> bool:
        x, y = point[0] - uvtt.origin[0], point[1] - uvtt.origin[1]
        return (
            -REGION_MARGIN <= x <= uvtt.size[0] + REGION_MARGIN
            and -REGION_MARGIN <= y <= uvtt.size[1] + REGION_MARGIN
        )

    def woxels(point: Point) -> list[float]:
        return [
            round((point[0] - uvtt.origin[0]) * WOXELS_PER_GRID, 2),
            round((point[1] - uvtt.origin[1]) * WOXELS_PER_GRID, 2),
        ]

    portal_records = [p for p in uvtt.portals if isinstance(p.get("position"), dict)]
    if walls:
        runs, result.joined_doorways = join_at_portals(uvtt.walls, portal_records)
        for run in runs:
            if not any(inside(p) for p in run):
                result.skipped["walls"] += 1
                continue
            loop = len(run) > 2 and _close(run[0], run[-1])
            points = run[:-1] if loop else run
            result.walls.append({"points": [woxels(p) for p in points], "loop": loop})

    if portals:
        for record in portal_records:
            try:
                position = _point(record["position"], "portal position")
            except UvttError:
                result.skipped["portals"] += 1
                continue
            if not inside(position):
                result.skipped["portals"] += 1
                continue
            result.portals.append(
                {
                    "position": woxels(position),
                    "radius": _portal_radius(record),
                    "closed": bool(record.get("closed", False)),
                    "freestanding": bool(record.get("freestanding", False)),
                    "rotation": round(math.degrees(_number(record.get("rotation"), 0.0)), 2),
                }
            )

    if lights:
        for record in uvtt.lights:
            try:
                position = _point(record.get("position"), "light position")
            except UvttError:
                result.skipped["lights"] += 1
                continue
            if not inside(position):
                result.skipped["lights"] += 1
                continue
            result.lights.append(
                {
                    "position": woxels(position),
                    "range": _number(record.get("range"), 2.0),
                    "energy": _number(record.get("intensity"), 1.0),
                    "color": _argb_to_hex(record.get("color")) or "",
                    "shadows": bool(record.get("shadows", True)),
                }
            )

    if ambient:
        result.ambient = uvtt.ambient

    for outline in uvtt.object_walls:
        local = [(p[0] - uvtt.origin[0], p[1] - uvtt.origin[1]) for p in outline]
        if not any(inside(p) for p in outline):
            result.skipped["blockers"] += 1
            continue
        result.blockers.append(fit_blocker(local))
    return result


def _number(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return default
    return float(value)


def _portal_radius(record: dict[str, Any]) -> float:
    """Half the doorway's width in woxels; a one-tile door is 128."""
    bounds = record.get("bounds")
    if isinstance(bounds, list) and len(bounds) == 2:
        try:
            a, b = _point(bounds[0], "bounds"), _point(bounds[1], "bounds")
        except UvttError:
            return 128.0
        width = math.hypot(b[0] - a[0], b[1] - a[1])
        if width > 0:
            return round(width * WOXELS_PER_GRID / 2, 2)
    return 128.0


def decoded_image(uvtt: Uvtt):
    """The export's render at full size, loaded, as a PIL image.

    Pixel (0, 0) is the region's origin and one grid square is
    `pixels_per_grid` pixels, so map woxels convert with ppg / 256.
    """
    from PIL import Image

    if uvtt.image_span is None:
        raise UvttError(f"{uvtt.path.name} has no image")
    start, end = uvtt.image_span
    with uvtt.path.open("rb") as stream:
        stream.seek(start)
        encoded = stream.read(end - start)
    try:
        png = base64.b64decode(encoded, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise UvttError("the export's image is not valid base64") from exc
    del encoded
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = TRACE_MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(png))
        width, height = image.size
        if width * height > TRACE_MAX_PIXELS:
            raise UvttError(
                f"the export's image is {width}x{height}, too large to decode safely; "
                "export it again at a lower pixels-per-grid"
            )
        image.load()
        return image
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def write_trace_image(uvtt: Uvtt, directory: Path) -> tuple[Path, float]:
    """Decode the export's render, shrink it and save it as a JPEG trace.

    Returns the file and the set_trace_image scale (woxels per pixel of the
    saved image) that makes it cover the region exactly.
    """
    from PIL import Image

    if uvtt.image_span is None:
        raise UvttError(f"{uvtt.path.name} has no image to trace")
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = TRACE_MAX_PIXELS
    try:
        with decoded_image(uvtt) as image:
            width, height = image.size
            # draft() is a no-op for PNG, so the whole image is decoded once.
            # Shrinking an RGBA image in one go makes a second full-size
            # premultiplied copy; a strip at a time copies only the strip.
            # Measured on a 13312x13312 export: 1.97 GB peak became 1.41 GB.
            whole = max(1, int(max(width, height) / TRACE_MAX_EDGE))
            rgb = Image.new("RGB", (-(-width // whole), -(-height // whole)))
            band = whole * 256
            for top in range(0, height, band):
                strip = image.crop((0, top, width, min(height, top + band))).convert("RGB")
                rgb.paste(strip.reduce(whole) if whole > 1 else strip, (0, top // whole))
                del strip
        factor = max(rgb.width, rgb.height) / TRACE_MAX_EDGE
        if factor > 1.0:
            rgb = rgb.resize(
                (max(1, round(rgb.width / factor)), max(1, round(rgb.height / factor))),
                Image.Resampling.LANCZOS,
            )
    finally:
        Image.MAX_IMAGE_PIXELS = previous
    directory.mkdir(parents=True, exist_ok=True)
    # ASCII only: server._TRACE_NAME must recognise the file to clean it up.
    stem = "".join(
        c if c.isascii() and (c.isalnum() or c in "-_") else "-" for c in uvtt.path.stem
    )[:60]
    target = directory / f"trace-{stem or 'dd2vtt'}-{rgb.width}x{rgb.height}.jpg"
    rgb.save(target, "JPEG", quality=88)
    scale = uvtt.size[0] * WOXELS_PER_GRID / rgb.width
    return target, round(scale, 6)


# A portal is on a wall segment when its centre is this close to it (woxels).
ON_SEGMENT = 2.0


def _grid(point: Any) -> dict[str, float]:
    return {
        "x": round(float(point[0]) / WOXELS_PER_GRID, 6),
        "y": round(float(point[1]) / WOXELS_PER_GRID, 6),
    }


def split_wall(
    points: list[list[float]], loop: bool, portals: list[dict[str, Any]]
) -> list[list[list[float]]]:
    """A wall's runs of sight line, cut at each portal it carries, in woxels.

    Dungeondraft's own export breaks a wall at every door and window: the
    run stops at one edge of the doorway and resumes at the other. A loop
    with no portal comes back closed (its first point repeated).
    """
    pts = [[float(p[0]), float(p[1])] for p in points]
    if loop and len(pts) > 2 and pts[0] != pts[-1]:
        pts.append(list(pts[0]))
    cuts: list[tuple[int, float, float]] = []
    for portal in portals:
        px, py = (float(v) for v in portal["position"])
        radius = float(portal.get("radius", 64.0))
        best = None
        for index in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[index], pts[index + 1]
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            along = ((px - ax) * dx + (py - ay) * dy) / length
            off = abs((px - ax) * dy - (py - ay) * dx) / length
            if -ON_SEGMENT <= along <= length + ON_SEGMENT and off <= ON_SEGMENT:
                if best is None or off < best[0]:
                    best = (off, index, along, length)
        if best is not None:
            _, index, along, length = best
            cuts.append(
                (index, max(0.0, along - radius) / length, min(length, along + radius) / length)
            )
    cuts.sort()
    runs: list[list[list[float]]] = []
    current: list[list[float]] = [pts[0]]
    for index in range(len(pts) - 1):
        a, b = pts[index], pts[index + 1]
        for _, start, end in (c for c in cuts if c[0] == index):
            current.append([a[0] + (b[0] - a[0]) * start, a[1] + (b[1] - a[1]) * start])
            if len(current) >= 2:
                runs.append(current)
            current = [[a[0] + (b[0] - a[0]) * end, a[1] + (b[1] - a[1]) * end]]
        current.append(b)
    if len(current) >= 2:
        runs.append(current)
    # On a loop the last run and the first meet at the first point: one run.
    if loop and cuts and len(runs) > 1 and runs[-1][-1] == runs[0][0]:
        runs[0] = runs.pop()[:-1] + runs[0]
    return [run for run in runs if any(p != run[0] for p in run)]


def build(
    *,
    size_tiles: tuple[float, float],
    pixels_per_grid: int,
    walls: list[dict[str, Any]],
    portals: list[dict[str, Any]],
    lights: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    ambient: str | None,
    image_png: bytes,
) -> dict[str, Any]:
    """A Universal VTT export (format 0.3) from bridge reads, in grid units.

    walls: list_elements walls with points; portals: list_elements portals;
    lights: list_elements lights in editor units; blockers: objects with
    block_light and opaque_bounds.
    """
    by_wall: dict[int, list[dict[str, Any]]] = {}
    for portal in portals:
        if portal.get("kind") == "wall_portal":
            by_wall.setdefault(int(portal.get("wall_id", -1)), []).append(portal)
    line_of_sight = [
        [_grid(p) for p in run]
        for wall in walls
        if isinstance(wall.get("points"), list) and len(wall["points"]) >= 2
        for run in split_wall(
            wall["points"], bool(wall.get("loop")), by_wall.get(int(wall["id"]), [])
        )
    ]
    exported_portals = []
    for portal in portals:
        x, y = (float(v) for v in portal["position"])
        radius = float(portal.get("radius", 64.0))
        if portal.get("kind") == "wall_portal" and isinstance(portal.get("direction"), list):
            tx, ty = (float(v) for v in portal["direction"])
            norm = math.hypot(tx, ty) or 1.0
            tx, ty = tx / norm, ty / norm
        elif portal.get("kind") == "wall_portal":
            # A bridge older than 1.3 reports only the outward normal: the
            # line is right, the hinge side may be reversed.
            nx, ny = (float(v) for v in portal.get("normal", [0, 1]))
            tx, ty = -ny, nx
        else:
            angle = math.radians(float(portal.get("rotation", 0.0)))
            tx, ty = math.cos(angle), math.sin(angle)
        exported_portals.append(
            {
                "position": _grid((x, y)),
                "bounds": [
                    _grid((x - tx * radius, y - ty * radius)),
                    _grid((x + tx * radius, y + ty * radius)),
                ],
                "rotation": round(math.atan2(ty, tx), 6),
                "closed": bool(portal.get("closed", False)),
                "freestanding": portal.get("kind") != "wall_portal",
            }
        )
    exported_lights = [
        {
            "position": _grid(light["position"]),
            "range": float(light.get("range", 2.0)),
            "intensity": float(light.get("energy", 1.0)),
            "color": "ff" + str(light.get("color") or "#ffffff").lstrip("#").lower(),
            "shadows": bool(light.get("shadows", True)),
        }
        for light in lights
    ]
    objects_line_of_sight = []
    for blocker in blockers:
        box = blocker.get("opaque_bounds") or blocker.get("bounds")
        if not (isinstance(box, list) and len(box) == 4):
            continue
        x0, y0, x1, y1 = (float(v) for v in box)
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        objects_line_of_sight.append([_grid(c) for c in corners])
    return {
        "format": 0.3,
        "resolution": {
            "map_origin": {"x": 0, "y": 0},
            "map_size": {"x": size_tiles[0], "y": size_tiles[1]},
            "pixels_per_grid": pixels_per_grid,
        },
        "line_of_sight": line_of_sight,
        "objects_line_of_sight": objects_line_of_sight,
        "portals": exported_portals,
        "environment": {
            "baked_lighting": True,
            "ambient_light": "ff" + (ambient or "#ffffff").lstrip("#").lower(),
        },
        "lights": exported_lights,
        "image": base64.b64encode(image_png).decode("ascii"),
    }
