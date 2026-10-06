"""Furnishing defects a viewer names at token zoom, and the art-family census.

A wall lantern a tile out from its wall, a book pile wider than its table, a
bed that is only its blanket, and a map drawn from four packs in four styles.
Each looks fine in the element counts. Pure functions over synthetic data.
"""

from __future__ import annotations

from battlemap_mcp.placement import (
    find_adrift_fixtures,
    find_lone_kit_parts,
    find_surface_overflow,
)
from battlemap_mcp.scene import CORE_ASSETS, pack_census, pack_of

PACK = "res://packs/AbC123/textures/objects/"


def obj(id, x, y, size=(128, 128), layer=100, asset="crate_01.png", rotation=0, scale=1.0):
    return {
        "id": id,
        "asset": asset if asset.startswith("res://") else PACK + asset,
        "position": [x, y],
        "texture_size": list(size),
        "scale": scale,
        "rotation": rotation,
        "layer": layer,
    }


NORTH_WALL = [{"id": 9, "points": [[0, 1000], [4000, 1000]]}]


# --- adrift fixtures cover more of what hangs on a wall ----------------------


def test_a_wall_lantern_a_tile_out_is_adrift():
    lantern = obj(1, 2000, 1300, size=(64, 64), asset="Wall_Lantern_Iron_A1_1x1.png")
    found = find_adrift_fixtures([lantern], NORTH_WALL)
    assert [entry["id"] for entry in found] == [1]


def test_a_wall_lantern_on_the_wall_line_is_not():
    lantern = obj(1, 2000, 1032, size=(64, 64), asset="Wall_Lantern_Iron_A1_1x1.png")
    assert find_adrift_fixtures([lantern], NORTH_WALL) == []


def test_curtains_and_chimneys_are_wall_fixtures_too():
    curtain = obj(1, 1000, 1400, size=(200, 40), asset="Curtain_Rod_Brass_A1.png")
    chimney = obj(2, 3000, 1400, size=(256, 128), asset="Fireplace_Rectangle_Chimney_A1.png")
    found = find_adrift_fixtures([curtain, chimney], NORTH_WALL)
    assert sorted(entry["id"] for entry in found) == [1, 2]


def test_rubble_named_after_a_wall_is_not_a_fixture():
    rubble = obj(1, 2000, 2000, asset="broken_wall_03.png")
    assert find_adrift_fixtures([rubble], NORTH_WALL) == []


# --- dressing stays on its surface --------------------------------------------

TABLE = dict(size=(512, 256), asset="Table_Rectangle_Wood_A1.png")


def test_a_book_pile_wider_than_its_table_is_reported():
    table = obj(1, 1000, 1000, **TABLE)
    books = obj(2, 1000, 1000, size=(600, 300), layer=200, asset="Books_Scattered_A_2x2.png")
    found = find_surface_overflow([table, books])
    assert found and found[0]["id"] == 2
    assert found[0]["surface_id"] == 1
    assert found[0]["larger_than_surface"] is True


def test_a_board_over_the_table_edge_is_reported():
    table = obj(1, 1000, 1000, **TABLE)
    board = obj(2, 1220, 1000, size=(120, 80), layer=200, asset="Cutting_Board_A1.png")
    found = find_surface_overflow([table, board])
    # The table's edge is at 1256; the board reaches 1280.
    assert found and found[0]["overhang_woxels"] == 24
    assert found[0]["larger_than_surface"] is False


def test_a_cup_well_inside_the_table_is_fine():
    table = obj(1, 1000, 1000, **TABLE)
    cup = obj(2, 900, 1000, size=(40, 40), layer=200, asset="Cup_Ceramic_A1.png")
    assert find_surface_overflow([table, cup]) == []


def test_a_rotated_table_is_measured_in_its_own_frame():
    table = obj(1, 1000, 1000, rotation=90, **TABLE)
    # Turned, the table runs 256 wide and 512 tall: a cup 200 below centre is on it.
    cup = obj(2, 1000, 1200, size=(40, 40), layer=200, asset="Cup_Ceramic_A1.png")
    assert find_surface_overflow([table, cup]) == []


def test_a_chair_beside_the_table_on_the_same_layer_is_not_dressing():
    table = obj(1, 1000, 1000, **TABLE)
    chair = obj(2, 1200, 1000, size=(160, 160), asset="Chair_Wood_A1.png")
    assert find_surface_overflow([table, chair]) == []


def test_a_chandelier_high_above_is_not_dressing():
    table = obj(1, 1000, 1000, **TABLE)
    chandelier = obj(2, 1000, 1000, size=(700, 700), layer=800, asset="Chandelier_A1.png")
    assert find_surface_overflow([table, chandelier]) == []


def test_an_item_across_two_pushed_together_tables_rests_on_both():
    left = obj(1, 1000, 1000, **TABLE)
    right = obj(2, 1512, 1000, **TABLE)
    # Centred on the left table, its right end over the join and onto the right one.
    runner = obj(3, 1200, 1000, size=(200, 60), layer=200, asset="Runner_Cloth_A1.png")
    assert find_surface_overflow([left, right, runner]) == []
    # Without the second table, the same runner hangs 44 past the edge.
    found = find_surface_overflow([left, runner])
    assert found and found[0]["overhang_woxels"] == 44


# --- multi-part kits ------------------------------------------------------------


def test_bedding_alone_is_reported():
    blanket = obj(1, 1000, 1000, size=(256, 512), layer=200, asset="Double_Bed_Blankets_A1.png")
    found = find_lone_kit_parts([blanket])
    assert found == [
        {
            "id": 1,
            "asset": PACK + "Double_Bed_Blankets_A1.png",
            "missing": "bedding without a bed frame",
        }
    ]


def test_bedding_on_its_frame_is_fine():
    frame = obj(1, 1000, 1000, size=(256, 512), asset="Double_Bed_Dark_A1.png")
    blanket = obj(2, 1000, 1020, size=(256, 480), layer=200, asset="Double_Bed_Blankets_A1.png")
    assert find_lone_kit_parts([frame, blanket]) == []


def test_a_bedside_table_is_not_a_bed_frame():
    blanket = obj(1, 1000, 1000, size=(256, 512), layer=200, asset="Single_Bed_Blankets_A1.png")
    side = obj(2, 1180, 800, size=(96, 96), asset="Bedside_Table_A1.png")
    assert len(find_lone_kit_parts([blanket, side])) == 1


def test_a_hearth_base_needs_its_chimney_nearby_not_across_the_map():
    base = obj(1, 1000, 1000, size=(384, 128), asset="Fireplace_Rectangle_Base_A1.png")
    far_chimney = obj(2, 3000, 3000, size=(384, 192), asset="Fireplace_Rectangle_Chimney_A1.png")
    found = find_lone_kit_parts([base, far_chimney])
    assert {entry["missing"] for entry in found} == {
        "hearth base without its chimney",
        "chimney without its hearth base",
    }
    near_chimney = obj(3, 1000, 940, size=(384, 192), asset="Fireplace_Rectangle_Chimney_A1.png")
    assert find_lone_kit_parts([base, near_chimney]) == []


def test_a_curtain_needs_its_rod():
    cloth = obj(1, 1000, 1000, size=(256, 64), asset="Curtain_Cloth_Green_A1.png")
    assert find_lone_kit_parts([cloth])[0]["missing"] == "curtain without its rod"
    rod = obj(2, 1000, 980, size=(280, 24), layer=200, asset="Curtain_Rod_Brass_A1.png")
    assert find_lone_kit_parts([cloth, rod]) == []


def test_ordinary_furniture_is_not_a_kit():
    assert find_lone_kit_parts([obj(1, 0, 0, asset="Chair_Wood_A1.png")]) == []


# --- art-family census ------------------------------------------------------------


def test_pack_of_reads_the_pack_id_and_calls_the_rest_core():
    assert pack_of("res://packs/AbC123/textures/objects/x.png") == "AbC123"
    assert pack_of("res://textures/objects/crate_01.png") == CORE_ASSETS
    assert pack_of("") == CORE_ASSETS


def test_the_census_counts_each_kind_per_pack_largest_first():
    census = pack_census(
        {
            "objects": [
                "res://packs/AbC123/a.png",
                "res://packs/AbC123/b.png",
                "res://textures/objects/horse_01.png",
            ],
            "terrain": ["res://textures/terrain/terrain_grass.png", ""],
            "patterns": ["res://packs/Zz9/p.png"],
        }
    )
    assert census["pack_count"] == 3
    assert census["packs"][0] == {"pack": "AbC123", "counts": {"objects": 2}}
    core = next(entry for entry in census["packs"] if entry["pack"] == CORE_ASSETS)
    assert core["counts"] == {"objects": 1, "terrain": 1}


def test_the_validators_report_the_furnishing_checks(monkeypatch):
    """The checks only help once a tool returns them."""
    from battlemap_mcp import server

    bed = "res://packs/FA35OB01/textures/objects/Beds/Bed_Blankets_Blue_A1_2x3.webp"
    objects = [
        {
            "id": 1,
            "asset": bed,
            "position": [500, 500],
            "texture_size": [256, 384],
            "scale": 1,
            "rotation": 0,
            "layer": 200,
        },
        {
            "id": 2,
            "asset": "res://textures/objects/furniture/table_01.png",
            "position": [2000, 2000],
            "texture_size": [256, 256],
            "scale": 1,
            "rotation": 0,
            "layer": 100,
        },
    ]
    elements = {"objects": objects, "walls": [], "portals": [], "lights": []}

    def read_all(kind, **_):
        found = elements[kind]
        return found, {"kind": kind, "total": len(found), "read": len(found), "complete": True}

    def request(cmd, **params):
        if cmd == "get_status":
            return {"map_open": True, "level_id": 0, "map_size_woxels": [4096, 4096]}
        if cmd == "get_terrain":
            return {"weights": [], "slots": ["res://textures/terrain/terrain_grass.png"]}
        raise AssertionError(cmd)

    monkeypatch.setattr(server, "_read_all", read_all)
    monkeypatch.setattr(server.bridge, "request", request)
    placements = server.validate_placements()
    assert "surface_overflow" in placements
    assert [part["id"] for part in placements["lone_kit_parts"]] == [1]
    families = server.validate_scene(samples=4)["art_families"]
    assert {entry["pack"]: entry["counts"] for entry in families["packs"]} == {
        "FA35OB01": {"objects": 1},
        "core": {"objects": 1, "terrain": 1},
    }
