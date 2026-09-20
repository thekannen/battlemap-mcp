"""Scene-level checks: ground coverage and whether lights have a cause.

Both come from real builds, and both cost several rounds of "looks wrong, try
again" because nothing could answer them except a render and an opinion:

- an inn whose exterior had grass only under the trees
- six lights of which five had nothing emitting them

Pure functions over synthetic data — nothing here touches the socket.
"""

import pytest

from battlemap_mcp.scene import (
    NEW_MAP_TERRAIN,
    find_bare_ground,
    find_unexplained_lights,
    is_emitter,
)

MAP = (4096.0, 3072.0)  # 16 x 12 tiles
ROOM = {"id": 1, "loop": True, "points": [[1024, 1024], [3072, 1024], [3072, 2048], [1024, 2048]]}

LIMESTONE = "res://textures/terrain/terrain_limestone.png"
GRASS = "res://textures/terrain/terrain_grass.png"
GRAVEL = "res://textures/terrain/terrain_gravel.png"

# What a map Dungeondraft has just created holds in its first four slots.
PRISTINE = [LIMESTONE] * 4

BASE = [1, 0, 0, 0]  # all weight in slot 0
SLOT1 = [0, 1, 0, 0]


def grid(value_fn, samples: int):
    """A weights grid in get_terrain's shape: row-major [slot0..slot3]."""
    rows = []
    for j in range(samples):
        row = []
        for i in range(samples):
            wx = MAP[0] * (i / (samples - 1))
            wy = MAP[1] * (j / (samples - 1))
            row.append(value_fn(wx, wy))
        rows.append(row)
    return rows


def test_the_new_map_default_is_what_a_pristine_map_holds():
    assert LIMESTONE in NEW_MAP_TERRAIN


# --- ground -----------------------------------------------------------------


def test_a_pristine_map_is_all_bare_ground():
    """Nobody chose this ground. This is the void the check exists for."""
    report = find_bare_ground(MAP, grid(lambda x, y: BASE, 16), [ROOM], slots=PRISTINE)
    assert report["judged"] is True
    assert report["ok"] is False
    assert report["fraction"] > 0.9
    assert report["points"], "a finding has to say where, or it is not actionable"


def test_a_base_filled_with_a_chosen_material_is_ground():
    """The map was grass edge to edge and this reported 79% bare, because slot-0
    weight reads [1, 0, 0, 0] exactly as untouched ground does. What decides it
    is the slot's texture, not its weight.
    """
    slots = [GRASS, LIMESTONE, LIMESTONE, LIMESTONE]
    report = find_bare_ground(MAP, grid(lambda x, y: BASE, 16), [ROOM], slots=slots)
    assert report["bare"] == 0
    assert report["ok"] is True
    assert report["materials"] == {"terrain_grass.png": 1.0}


def test_grass_only_under_the_trees_is_still_caught():
    """The original defect: chosen material in patches, the default everywhere else."""
    slots = [LIMESTONE, GRASS, LIMESTONE, LIMESTONE]

    def patches(x, y):
        near = (abs(x - 400) < 200 and abs(y - 2600) < 200) or (
            abs(x - 3600) < 200 and abs(y - 500) < 200
        )
        return SLOT1 if near else BASE

    report = find_bare_ground(MAP, grid(patches, 24), [ROOM], slots=slots)
    assert report["ok"] is False
    assert report["fraction"] > 0.8
    assert "limestone" in report["note"]


def test_the_building_interior_is_not_counted_as_bare_ground():
    """An interior is floored with patterns, not terrain, and always reads bare.

    Counting it would report every correctly built map as a failure, which is
    the fastest way to get a check ignored.
    """
    slots = [LIMESTONE, GRASS, LIMESTONE, LIMESTONE]

    def only_outside_painted(x, y):
        return BASE if (1024 < x < 3072 and 1024 < y < 2048) else SLOT1

    report = find_bare_ground(MAP, grid(only_outside_painted, 24), [ROOM], slots=slots)
    assert report["bare"] == 0, "the walled interior must be excluded"
    assert report["ok"] is True


def test_a_blended_edge_counts_as_ground():
    """Only a sample with no chosen material in it at all is bare."""
    slots = [LIMESTONE, GRASS, LIMESTONE, LIMESTONE]
    report = find_bare_ground(MAP, grid(lambda x, y: [0.7, 0.3, 0, 0], 8), [ROOM], slots=slots)
    assert report["bare"] == 0


def test_the_report_names_what_the_ground_is():
    """A verdict alone invites being ignored; the materials make it checkable."""
    slots = [GRASS, GRAVEL, LIMESTONE, LIMESTONE]
    report = find_bare_ground(
        MAP, grid(lambda x, y: SLOT1 if y > 2600 else BASE, 16), [], slots=slots
    )
    assert set(report["materials"]) == {"terrain_grass.png", "terrain_gravel.png"}
    assert abs(sum(report["materials"].values()) - 1.0) < 0.01


def test_without_slot_textures_it_says_it_cannot_judge():
    """Not judged and judged-clean are different answers, and it must say which."""
    report = find_bare_ground(MAP, grid(lambda x, y: BASE, 8), [ROOM])
    assert report["judged"] is False
    assert report["bare"] == 0
    assert "slot" in report["note"]


def test_a_map_with_no_walls_checks_the_whole_surface():
    report = find_bare_ground(MAP, grid(lambda x, y: BASE, 8), [], slots=PRISTINE)
    assert report["ok"] is False


# --- which assets can emit light --------------------------------------------

# Real file names from Dungeondraft's library. The heuristic was measured against
# all 1792 of them; these are the cases that decided its shape.
REAL_SOURCES = [
    "stove_01.png",
    "stove_02_roman.png",
    "funeral_pyre_01.png",
    "mana_orb_01.png",
    "wall_torch_01.png",
    "candle_holder_02.png",
    "fireplace_03.png",
    "campfire_01.png",
    "dwarven_forge.png",
    "forge_fire.png",
    "bowl_lamp_01.png",
    "magical_brazier_01.png",
    "cave_crystals_04.png",
    "magic_portal_01.png",
    "arcane_summoning_circle_glow_01.png",
    "alchemy_furnace_01.png",
    "chandelier_01.png",
    "lantern_01.png",
]

REAL_NON_SOURCES = [
    "sundial_01.png",  # `sun` credited five of these
    "stairs_wood.png",  # `star` would have
    "magic_mushrooms_01.png",  # `magic` credited eight
    "forge_lever.png",  # shares `forge` with a forge
    "forge_hammer_mold.png",
    "coal_bag.png",
    "runed_podium.png",
    "log_pile_01.png",
    "bar_table.png",
]


@pytest.mark.parametrize("name", REAL_SOURCES)
def test_real_light_sources_are_recognised(name):
    assert is_emitter(f"res://textures/objects/x/{name}")


@pytest.mark.parametrize("name", REAL_NON_SOURCES)
def test_real_non_sources_are_not(name):
    assert not is_emitter(f"res://textures/objects/x/{name}")


# --- lights -----------------------------------------------------------------


def light(lid, x, y):
    return {"id": lid, "position": [x, y]}


def obj(oid, asset, x, y):
    return {"id": oid, "asset": f"res://textures/objects/{asset}", "position": [x, y]}


def test_a_light_over_a_hearth_is_explained():
    report = find_unexplained_lights(
        [light(1, 1200, 1200)], [obj(2, "environment/fire_02.png", 1250, 1220)]
    )
    assert report["unexplained"] == []
    assert report["ok"] is True


def test_a_light_over_a_stove_is_explained():
    """Runtime behavior and validation."""
    report = find_unexplained_lights(
        [light(1, 900, 900)], [obj(2, "activities/cooking/stove_01.png", 930, 910)]
    )
    assert report["ok"] is True


def test_a_light_with_nothing_emitting_it_is_reported():
    """A pool of warm light on bare boards has no cause a viewer can name."""
    report = find_unexplained_lights(
        [light(1, 1200, 1200)], [obj(2, "furniture/tables/round_table_01.png", 1210, 1210)]
    )
    assert [f["id"] for f in report["unexplained"]] == [1]
    assert report["ok"] is False


def test_an_emitter_across_the_map_does_not_explain_a_light():
    report = find_unexplained_lights(
        [light(1, 1200, 1200)], [obj(2, "decor/lighting/lantern_01.png", 3900, 2900)]
    )
    assert [f["id"] for f in report["unexplained"]] == [1]


def test_the_named_emitter_is_reported_so_the_match_can_be_judged():
    """The match is a guess from an asset name; say which name, so it can be checked."""
    report = find_unexplained_lights(
        [light(1, 1200, 1200)], [obj(2, "decor/lighting/wall_torch_01.png", 1240, 1180)]
    )
    assert report["ok"] is True
    assert "wall_torch_01" in report["explained"][0]["by"]


def test_no_lights_is_clean_rather_than_an_error():
    assert find_unexplained_lights([], [])["ok"] is True
