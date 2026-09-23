"""Two layout habits that a render shows and no element count does.

Rigid placement: objects all at their default size and squared to the grid.
A room arranged that way reads as a showroom rather than a place in use, and
every placement call reports success, so nothing says so until someone looks.

A small footprint: a building in the middle of a mostly untouched map. At play
scale the eye lands on the empty ground first.

Both are advice, never failures. A shelf squared to its wall is correct, and a
lone ruin on an open plain can be the point. So neither changes an `ok`, and
each note says what to do rather than what went wrong.

Pure functions over what the bridge already returns; nothing here touches the map.
"""

from __future__ import annotations

WOXELS_PER_TILE = 256
SCALE_TOLERANCE = 0.01
ANGLE_TOLERANCE = 1.0

BATCH_MINIMUM = 6
BATCH_RIGID_SHARE = 0.9
SCENE_MINIMUM = 10
SCENE_RIGID_SHARE = 0.75
FOOTPRINT_SHARE = 0.4


def is_rigid(scale: float | None, rotation: float | None) -> bool:
    """Default size and a quarter-turn rotation, within rounding."""
    scale = 1.0 if scale is None else float(scale)
    rotation = 0.0 if rotation is None else float(rotation)
    off_quarter = abs(((rotation + 45.0) % 90.0) - 45.0)
    return abs(scale - 1.0) <= SCALE_TOLERANCE and off_quarter <= ANGLE_TOLERANCE


def rigid_share(entries: list[dict]) -> float:
    if not entries:
        return 0.0
    rigid = sum(is_rigid(e.get("scale"), e.get("rotation")) for e in entries)
    return rigid / len(entries)


def batch_note(entries: list[dict]) -> str | None:
    """A note for a place_objects result, or None when the batch varies enough."""
    if len(entries) < BATCH_MINIMUM or rigid_share(entries) < BATCH_RIGID_SHARE:
        return None
    return (
        f"All {len(entries)} objects in this batch sit at scale 1.0 and on quarter "
        "turns, which reads as a showroom rather than a place in use. Keep "
        "wall-hugging fixtures square, and give the rest a slightly different "
        "scale (about 0.85-1.15) and a few degrees of turn; modify_object "
        "adjusts placed objects."
    )


def _extent(objects: list[dict], walls: list[dict], lights: list[dict]) -> tuple | None:
    points: list[tuple[float, float]] = []
    for element in [*objects, *lights]:
        position = element.get("position")
        if position:
            points.append((float(position[0]), float(position[1])))
    for wall in walls:
        points += [(float(p[0]), float(p[1])) for p in wall.get("points") or []]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def review(
    map_size: tuple[float, float],
    objects: list[dict],
    walls: list[dict],
    lights: list[dict],
) -> dict:
    """validate_scene's arrangement section: two measures and any advice."""
    notes: list[str] = []
    share = rigid_share(objects)
    if len(objects) >= SCENE_MINIMUM and share >= SCENE_RIGID_SHARE:
        notes.append(
            f"{round(share * 100)}% of objects sit at scale 1.0 on quarter turns. "
            "Beyond fixtures that belong squared to a wall, vary scale slightly "
            "and turn pieces a few degrees so the space reads as used."
        )
    extent = _extent(objects, walls, lights)
    map_area = float(map_size[0]) * float(map_size[1])
    coverage = None
    if extent and map_area > 0:
        width = max(extent[2] - extent[0], WOXELS_PER_TILE)
        height = max(extent[3] - extent[1], WOXELS_PER_TILE)
        coverage = min(1.0, width * height / map_area)
        if coverage < FOOTPRINT_SHARE:
            notes.append(
                f"What is built covers about {round(coverage * 100)}% of the map. "
                "Extend the scene's surroundings toward the edges, or plan the "
                "map size before laying out: set_map_size keeps the top-left "
                "origin and does not move what is already placed."
            )
    return {
        "rigid_share": round(share, 3),
        "objects": len(objects),
        "footprint_share": None if coverage is None else round(coverage, 3),
        "notes": notes,
    }
