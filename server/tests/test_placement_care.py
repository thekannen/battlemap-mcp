"""Defects a viewer names first: things stacked anyhow, fixtures off their wall.

Both come from a map review in a map-maker's own words — "crates on crates",
"sword on tents", "the torch isn't attached to a wall, it is parallel to it".
Neither shows in an element count, and neither is a wall intrusion, so the
existing checks passed the maps clean.
"""

from __future__ import annotations

from battlemap_mcp.placement import find_adrift_fixtures, find_stacks

CRATE = [128, 128]
TANKARD = [40, 40]


def obj(id, x, y, size=CRATE, layer=100, asset="res://textures/objects/crate_01.png", **extra):
    return {
        "id": id,
        "asset": asset,
        "position": [x, y],
        "texture_size": size,
        "scale": 1.0,
        "rotation": 0,
        "layer": layer,
        **extra,
    }


def test_two_large_objects_in_one_spot_are_reported():
    found = find_stacks([obj(1, 1000, 1000), obj(2, 1030, 1010)])
    assert len(found) == 1
    assert found[0]["ids"] == [1, 2]
    assert found[0]["overlap"] >= 0.5


def test_dressing_a_surface_is_not_a_stack():
    table = obj(1, 1000, 1000, size=[256, 256])
    # A tankard on the table: small, and on the layer above, which is how a
    # dressed surface is built.
    tankard = obj(2, 1000, 1000, size=TANKARD, layer=200)
    assert find_stacks([table, tankard]) == []


def test_large_objects_on_different_layers_are_left_alone():
    assert find_stacks([obj(1, 500, 500), obj(2, 500, 500, layer=200)]) == []


def test_objects_merely_beside_each_other_are_not_stacked():
    assert find_stacks([obj(1, 500, 500), obj(2, 700, 500)]) == []


WALL = [{"id": 9, "points": [[0, 1000], [4000, 1000]]}]


def torch(x, y):
    return obj(3, x, y, size=[64, 64], asset="res://textures/objects/wall_torch_01.png")


def test_a_torch_away_from_every_wall_is_reported():
    found = find_adrift_fixtures([torch(2000, 1600)], WALL)
    assert found and found[0]["id"] == 3
    assert found[0]["woxels_from_wall"] > 96


def test_a_torch_on_its_wall_is_not():
    assert find_adrift_fixtures([torch(2000, 1040)], WALL) == []


def test_furniture_that_is_not_a_wall_fixture_is_ignored():
    assert find_adrift_fixtures([obj(4, 2000, 2000)], WALL) == []


def test_nothing_is_reported_when_the_map_has_no_walls():
    assert find_adrift_fixtures([torch(10, 10)], []) == []


def test_the_stack_list_is_capped_and_worst_first():
    crowd = [obj(i, 1000 + i, 1000) for i in range(12)]
    found = find_stacks(crowd, limit=5)
    assert len(found) == 5
    assert found == sorted(found, key=lambda item: item["overlap"], reverse=True)


SOUTH_WALL = [
    {
        "id": 1,
        "loop": True,
        "points": [[3200, 1536], [5760, 1536], [5760, 3584], [3200, 3584]],
    }
]


def test_a_torch_beside_a_door_is_on_its_wall():
    """Runtime behavior and validation."""
    torches = [
        obj(3, 4224, 3584, size=[84, 84], asset="res://textures/objects/wall_torch_01.png"),
        obj(4, 4736, 3584, size=[84, 84], asset="res://textures/objects/wall_torch_01.png"),
    ]
    assert find_adrift_fixtures(torches, SOUTH_WALL) == []
    # Nudged flush into the room, as the report also tried.
    flush = [obj(5, 4224, 3529, size=[84, 84], asset="res://textures/objects/wall_torch_01.png")]
    assert find_adrift_fixtures(flush, SOUTH_WALL) == []


def test_distance_is_measured_to_the_nearest_point_of_a_long_wall():
    far = obj(6, 4224, 3900, size=[84, 84], asset="res://textures/objects/wall_torch_01.png")
    found = find_adrift_fixtures([far], SOUTH_WALL)
    # 3900 - 3584 = 316 to the wall line, less the torch's half-depth of 42.
    assert found and found[0]["woxels_from_wall"] == 274
