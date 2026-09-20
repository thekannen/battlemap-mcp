"""Two questions a render can raise but not answer: is there ground, and why is it lit.

Both come from one build, and both cost several rounds of "that looks wrong,
try again" because the only instrument was an opinion about a picture.

- **Ground.** An inn had grass painted only under the spots its trees touched.
  Every element count was correct and every call had succeeded; the building
  simply stood on ground nobody had chosen. Terrain is the one part of a map
  that has no element count at all, so nothing in the usual reporting could
  have shown it.
- **Light.** The same map had six lights and five of them had nothing emitting
  them — a bar glowing with no candle on it, an oven throwing light with no
  fire in it, a doorway lit by nothing. A viewer reads that instantly as wrong
  without being able to say why.

Neither check is clever. They are here because the expensive part was noticing,
not fixing.
"""

from __future__ import annotations

import math
import re

from .floorplan import CELL_WOXELS, structure_cells

# How close an emitter has to be for a light to count as coming from it. One
# tile: a light is meant to sit ON its source, and anything further apart is
# worth a second look even when it turns out to be deliberate.
DEFAULT_EMITTER_REACH = 256.0

NEW_MAP_TERRAIN = frozenset({"res://textures/terrain/terrain_limestone.png"})

EMITTER_STEMS = (
    "fire",  # fire_02, fireplace_03, forge_fire
    "campfire",
    "bonfire",
    "flame",
    "candle",
    "lantern",
    "lamp",
    "torch",
    "brazier",
    "sconce",
    "hearth",
    "chandelier",
    "oven",
    "furnace",
    "stove",
    "kiln",
    "forge",
    "pyre",
    "coals",
    "ember",
    "glow",
    "portal",
    "crystal",
    "lava",
    "orb",
)

# Tokens that mean "this is a part or an accessory, not the source itself".
# forge_lever and the forge's hammer and sword molds share the word `forge`
# with the forge; firewood shares `fire` with a fire.
NOT_A_SOURCE = frozenset({"mold", "lever", "firewood"})

# A sample is ground when a CHOSEN texture carries more than this much of its
# weight. A blended edge between a chosen material and the default is ground.
PAINTED_EPSILON = 0.02


def _asset_name(element: dict) -> str:
    return str(element.get("asset", "")).rsplit("/", 1)[-1]


def _tokens(name: str) -> list[str]:
    stem = name.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    return re.findall(r"[a-z]+", stem)


def is_emitter(asset: str) -> bool:
    """Whether an asset's name marks it as something that could give off light."""
    tokens = _tokens(asset)
    if NOT_A_SOURCE.intersection(tokens):
        return False
    return any(token.startswith(stem) for token in tokens for stem in EMITTER_STEMS)


def find_bare_ground(
    map_size_woxels: tuple[float, float],
    weights: list[list[list[float]]],
    walls: list[dict],
    *,
    slots: list[str] | None = None,
    cell: int = CELL_WOXELS,
    max_points: int = 12,
) -> dict:
    """Report open ground still covered by the new-map default terrain.

    `weights` is get_terrain's grid, row-major from the map's top-left, each
    point [slot0, slot1, slot2, slot3]. `slots` is get_terrain's texture for
    each of those four slots. Without it nothing can be judged: the weights say
    how much of each slot is present, not what the slot is.

    Cells occupied or enclosed by walls are skipped. An interior is floored
    with patterns, not terrain, and would read as bare on a finished map.
    """
    rows = len(weights)
    columns = len(weights[0]) if rows else 0
    if rows < 2 or columns < 2:
        return {
            "judged": True,
            "sampled": 0,
            "bare": 0,
            "fraction": 0.0,
            "points": [],
            "materials": {},
            "ok": True,
        }

    if slots is None:
        return {
            "judged": False,
            "sampled": 0,
            "bare": 0,
            "fraction": 0.0,
            "points": [],
            "materials": {},
            "ok": True,
            "note": (
                "not judged: the bridge did not report which texture each slot "
                "holds, and without that painted ground and untouched ground "
                "read identically. Update the bridge."
            ),
        }

    textures = [str(s or "") for s in list(slots)[:4]]
    textures += [""] * (4 - len(textures))
    chosen = [bool(t) and t not in NEW_MAP_TERRAIN for t in textures]

    inside, _, _ = structure_cells(map_size_woxels, walls, cell=cell)
    width, height = float(map_size_woxels[0]), float(map_size_woxels[1])

    sampled = 0
    bare_points: list[list[float]] = []
    dominant: dict[str, int] = {}
    for j, row in enumerate(weights):
        for i, point in enumerate(row):
            wx = width * (i / (columns - 1))
            wy = height * (j / (rows - 1))
            if (int(wx // cell), int(wy // cell)) in inside:
                continue
            sampled += 1
            values = [float(v) for v in list(point)[:4]] + [0.0] * max(0, 4 - len(point))
            top = max(range(4), key=lambda s: values[s])
            name = textures[top].rsplit("/", 1)[-1] or f"slot {top} (no texture)"
            dominant[name] = dominant.get(name, 0) + 1
            if sum(v for v, keep in zip(values, chosen, strict=True) if keep) <= PAINTED_EPSILON:
                bare_points.append([round(wx), round(wy)])

    bare = len(bare_points)
    # Spread the reported points across the findings rather than returning the
    # first dozen, which would all sit in the same corner and read as one spot.
    step = max(1, bare // max_points)
    report = {
        "judged": True,
        "sampled": sampled,
        "bare": bare,
        "fraction": round(bare / sampled, 3) if sampled else 0.0,
        "points": bare_points[::step][:max_points],
        "materials": {
            name: round(count / sampled, 3)
            for name, count in sorted(dominant.items(), key=lambda kv: -kv[1])
        }
        if sampled
        else {},
        "ok": bare == 0,
    }
    if bare:
        report["note"] = (
            "these points are still the terrain Dungeondraft gives a new map "
            f"({', '.join(sorted(n.rsplit('/', 1)[-1] for n in NEW_MAP_TERRAIN))}). "
            "If that material is a deliberate choice for this ground, ignore this."
        )
    return report


def find_unexplained_lights(
    lights: list[dict],
    objects: list[dict],
    *,
    reach: float = DEFAULT_EMITTER_REACH,
) -> dict:
    """Report lights with nothing nearby that could be emitting them."""
    emitters = [(o, _asset_name(o)) for o in objects if is_emitter(_asset_name(o))]

    explained: list[dict] = []
    unexplained: list[dict] = []
    for source in lights:
        position = source.get("position") or [0, 0]
        lx, ly = float(position[0]), float(position[1])
        best = None
        for element, name in emitters:
            pos = element.get("position") or [0, 0]
            distance = math.hypot(float(pos[0]) - lx, float(pos[1]) - ly)
            if distance <= reach and (best is None or distance < best[0]):
                best = (distance, name)
        entry = {"id": int(source.get("id", -1)), "position": [lx, ly]}
        if best is None:
            unexplained.append(entry)
        else:
            explained.append({**entry, "by": best[1], "distance": round(best[0])})

    return {
        "lights": len(lights),
        "explained": explained,
        "unexplained": unexplained,
        "ok": not unexplained,
        "note": (
            "Emitters are matched on asset NAME, so this is a prompt to look, "
            "not a verdict: an unusually named source reads as unexplained, and "
            "an unlit lantern sitting as decor reads as an explanation. Judge "
            "each finding."
        ),
    }
