"""Structural analysis of a floorplan, before anything is furnished.

The bridge is good at placing things and poor at telling you whether what you
placed makes architectural sense. A room sealed behind no door, a door that
missed its wall, a workshop reachable only by walking through the exterior —
all of these look fine in the element counts and only surface in a screenshot,
by which point the furniture is already in.

Everything here is derived from data the bridge already returns: wall
polylines, portals, and the map size. Nothing is placed or changed.

The method is deliberately a raster rather than exact polygon work. Wall
geometry is arbitrary polylines that may overlap, double back, or stop just
short of meeting; recovering faces from that exactly is fiddly and fails badly
on the near-misses that matter most. Painting walls onto a grid and flooding
the gaps degrades gracefully instead: a wall that misses its neighbour by less
than a cell reads as joined, which is also how it renders.

Two floods do the work:

- doors SHUT  -> the enclosed regions, i.e. the rooms
- doors OPEN  -> what can actually be walked between

Comparing them is what exposes a sealed room, because a region that is its own
island in the second flood has no way in.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

# Analysis cell size in woxels. A quarter tile: fine enough that a doorway is
# several cells wide and cannot be sealed by rounding, coarse enough that a
# large map stays a few tens of thousands of cells.
CELL_WOXELS = 64
WOXELS_PER_TILE = 256

# Regions smaller than this are rasterisation crumbs — the sliver between two
# nearly-touching walls — not rooms anyone built.
MIN_ROOM_TILES = 1.0


@dataclass(frozen=True)
class Region:
    """One enclosed area, in tiles."""

    id: int
    area_tiles: float
    bounds: tuple[float, float, float, float]  # x0, y0, x1, y1 in woxels
    reachable_from_exterior: bool
    portal_ids: tuple[int, ...]


@dataclass
class Findings:
    """Structural problems, most severe first when rendered."""

    sealed_regions: list[int] = field(default_factory=list)
    portals_not_in_a_wall: list[int] = field(default_factory=list)
    portals_to_nowhere: list[int] = field(default_factory=list)
    exterior_openings: list[int] = field(default_factory=list)


def _segments(walls: list[dict]) -> list[tuple[float, float, float, float]]:
    """Flatten wall polylines into segments, closing the ones marked as loops."""
    out = []
    for wall in walls:
        points = wall.get("points") or []
        if len(points) < 2:
            continue
        for index in range(len(points) - 1):
            (x0, y0), (x1, y1) = points[index], points[index + 1]
            out.append((float(x0), float(y0), float(x1), float(y1)))
        if wall.get("loop"):
            (x0, y0), (x1, y1) = points[-1], points[0]
            out.append((float(x0), float(y0), float(x1), float(y1)))
    return out


def _paint_segment(
    blocked: set[tuple[int, int]],
    segment: tuple[float, float, float, float],
    cell: int,
    columns: int,
    rows: int,
) -> None:
    """Mark every cell a segment passes through.

    Sampled at half a cell so no cell is stepped over on a diagonal, which
    would leave a one-cell hole that the flood pours through and silently
    merges two rooms.
    """
    x0, y0, x1, y1 = segment
    length = max(abs(x1 - x0), abs(y1 - y0))
    steps = max(1, int(length / (cell / 2)) + 1)
    for step in range(steps + 1):
        t = step / steps
        cx = int((x0 + (x1 - x0) * t) // cell)
        cy = int((y0 + (y1 - y0) * t) // cell)
        if 0 <= cx < columns and 0 <= cy < rows:
            blocked.add((cx, cy))


def _portal_cells(portal: dict, cell: int, columns: int, rows: int) -> set[tuple[int, int]]:
    """Cells a portal opens, from its position and radius."""
    position = portal.get("position") or [0, 0]
    radius = float(portal.get("radius") or 64.0)
    px, py = float(position[0]), float(position[1])
    # A little generous: the opening must actually break the wall it sits in,
    # and a portal exactly on a cell boundary would otherwise clear nothing.
    reach = max(1, int((radius + cell) // cell))
    cx0, cy0 = int(px // cell), int(py // cell)
    cells = set()
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            cx, cy = cx0 + dx, cy0 + dy
            if 0 <= cx < columns and 0 <= cy < rows:
                cells.add((cx, cy))
    return cells


def _flood(
    columns: int, rows: int, blocked: set[tuple[int, int]]
) -> tuple[dict[tuple[int, int], int], int]:
    """Label every open cell with a component id. 4-connected."""
    labels: dict[tuple[int, int], int] = {}
    component = 0
    for start_y in range(rows):
        for start_x in range(columns):
            start = (start_x, start_y)
            if start in blocked or start in labels:
                continue
            component += 1
            queue = deque([start])
            labels[start] = component
            while queue:
                x, y = queue.popleft()
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    neighbour = (nx, ny)
                    if not (0 <= nx < columns and 0 <= ny < rows):
                        continue
                    if neighbour in blocked or neighbour in labels:
                        continue
                    labels[neighbour] = component
                    queue.append(neighbour)
    return labels, component


def _bounds(cells: list[tuple[int, int]], cell: int) -> tuple[float, float, float, float]:
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return (
        float(min(xs) * cell),
        float(min(ys) * cell),
        float((max(xs) + 1) * cell),
        float((max(ys) + 1) * cell),
    )


def structure_cells(
    map_size_woxels: tuple[float, float],
    walls: list[dict],
    *,
    cell: int = CELL_WOXELS,
    min_room_tiles: float = MIN_ROOM_TILES,
) -> tuple[set[tuple[int, int]], int, int]:
    """Cells a building occupies: its walls, plus everything enclosed by them.

    The complement is the open ground, which is what a terrain-coverage check
    needs. An interior is floored with patterns or floor shapes rather than
    terrain, so it reads as unpainted no matter how finished it is — counting it
    would report every correctly built map as a failure.
    """
    width, height = float(map_size_woxels[0]), float(map_size_woxels[1])
    columns = max(1, int(width // cell))
    rows = max(1, int(height // cell))

    blocked: set[tuple[int, int]] = set()
    for segment in _segments(walls):
        _paint_segment(blocked, segment, cell, columns, rows)

    labels, _ = _flood(columns, rows, blocked)

    exterior: set[int] = set()
    for x in range(columns):
        for y in (0, rows - 1):
            if (x, y) in labels:
                exterior.add(labels[(x, y)])
    for y in range(rows):
        for x in (0, columns - 1):
            if (x, y) in labels:
                exterior.add(labels[(x, y)])

    by_component: dict[int, list[tuple[int, int]]] = {}
    for position, label in labels.items():
        by_component.setdefault(label, []).append(position)

    cell_area_tiles = (cell / WOXELS_PER_TILE) ** 2
    inside = set(blocked)
    for component, cells in by_component.items():
        if component in exterior:
            continue
        if len(cells) * cell_area_tiles < min_room_tiles:
            continue
        inside.update(cells)
    return inside, columns, rows


def analyse(
    map_size_woxels: tuple[float, float],
    walls: list[dict],
    portals: list[dict],
    *,
    cell: int = CELL_WOXELS,
    min_room_tiles: float = MIN_ROOM_TILES,
) -> dict:
    """Return a structural report for one level. Read-only, pure geometry."""
    width, height = float(map_size_woxels[0]), float(map_size_woxels[1])
    columns = max(1, int(width // cell))
    rows = max(1, int(height // cell))

    blocked: set[tuple[int, int]] = set()
    for segment in _segments(walls):
        _paint_segment(blocked, segment, cell, columns, rows)

    # Doors shut: the enclosed regions.
    shut_labels, _ = _flood(columns, rows, blocked)

    # Doors open: what is actually walkable.
    opened = set(blocked)
    portal_opening: dict[int, set[tuple[int, int]]] = {}
    for portal in portals:
        opening_cells = _portal_cells(portal, cell, columns, rows)
        portal_opening[int(portal.get("id", -1))] = opening_cells
        opened -= opening_cells
    open_labels, _ = _flood(columns, rows, opened)

    # The exterior is whatever the map border sits in. Taken from the shut
    # flood, since a door should not change what counts as outside.
    exterior_components = set()
    for x in range(columns):
        for y in (0, rows - 1):
            if (x, y) in shut_labels:
                exterior_components.add(shut_labels[(x, y)])
    for y in range(rows):
        for x in (0, columns - 1):
            if (x, y) in shut_labels:
                exterior_components.add(shut_labels[(x, y)])

    by_component: dict[int, list[tuple[int, int]]] = {}
    for position, label in shut_labels.items():
        by_component.setdefault(label, []).append(position)

    # Which open-flood components the exterior occupies. Anything sharing one
    # of these can be walked to from outside.
    exterior_open: set[int] = set()
    for component in exterior_components:
        for position in by_component.get(component, []):
            if position in open_labels:
                exterior_open.add(open_labels[position])

    cell_area_tiles = (cell / WOXELS_PER_TILE) ** 2
    findings = Findings()
    regions: list[Region] = []

    for component, cells in sorted(by_component.items()):
        if component in exterior_components:
            continue
        area = len(cells) * cell_area_tiles
        if area < min_room_tiles:
            continue
        touching = tuple(
            sorted(
                portal_id for portal_id, opening in portal_opening.items() if opening & set(cells)
            )
        )
        reachable = any(open_labels.get(position) in exterior_open for position in cells)
        regions.append(
            Region(
                id=component,
                area_tiles=round(area, 2),
                bounds=_bounds(cells, cell),
                reachable_from_exterior=reachable,
                portal_ids=touching,
            )
        )
        if not reachable:
            findings.sealed_regions.append(component)

    # A portal that touches no wall cell never cut an opening in anything: it is
    # floating in open space, which is what a failed wall-mount looks like.
    for portal in portals:
        portal_id = int(portal.get("id", -1))
        opening = portal_opening.get(portal_id, set())
        if not (opening & blocked):
            findings.portals_not_in_a_wall.append(portal_id)
            continue
        # A door whose two sides are the same region connects nothing. Compare
        # the shut-flood labels around the opening.
        sides = {shut_labels[c] for c in opening if c in shut_labels}
        if len(sides) < 2:
            findings.portals_to_nowhere.append(portal_id)
        elif sides & exterior_components:
            findings.exterior_openings.append(portal_id)

    return {
        "cell_woxels": cell,
        "grid": {"columns": columns, "rows": rows},
        "regions": [
            {
                "id": region.id,
                "area_tiles": region.area_tiles,
                "bounds": list(region.bounds),
                "reachable_from_exterior": region.reachable_from_exterior,
                "portal_ids": list(region.portal_ids),
            }
            for region in regions
        ],
        "region_count": len(regions),
        "findings": {
            "sealed_regions": findings.sealed_regions,
            "portals_not_in_a_wall": findings.portals_not_in_a_wall,
            "portals_to_nowhere": findings.portals_to_nowhere,
            "exterior_openings": findings.exterior_openings,
        },
        "ok": not (
            findings.sealed_regions or findings.portals_not_in_a_wall or findings.portals_to_nowhere
        ),
    }
