"""Floorplan analysis. Pure geometry over synthetic maps — never touches the socket."""

from battlemap_mcp.floorplan import analyse

MAP = (4096.0, 3072.0)  # 16 x 12 tiles


def room(wall_id: int, x0: float, y0: float, x1: float, y1: float) -> dict:
    """A closed rectangular wall loop."""
    return {
        "id": wall_id,
        "loop": True,
        "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
    }


def door(portal_id: int, x: float, y: float, radius: float = 64.0) -> dict:
    return {"id": portal_id, "position": [x, y], "radius": radius}


def test_a_map_with_no_walls_has_no_rooms():
    """Open ground is all exterior; there is nothing enclosed to report."""
    report = analyse(MAP, [], [])
    assert report["region_count"] == 0
    assert report["ok"] is True


def test_a_room_with_a_door_is_reachable():
    report = analyse(MAP, [room(1, 512, 512, 2560, 2048)], [door(10, 512, 1280)])
    assert report["region_count"] == 1
    region = report["regions"][0]
    assert region["reachable_from_exterior"] is True
    assert 10 in region["portal_ids"]
    assert report["findings"]["sealed_regions"] == []
    assert report["ok"] is True


def test_a_room_with_no_door_is_reported_sealed():
    """The failure that only shows up in a screenshot after furnishing."""
    report = analyse(MAP, [room(1, 512, 512, 2560, 2048)], [])
    assert report["region_count"] == 1
    region = report["regions"][0]
    assert region["reachable_from_exterior"] is False
    assert report["findings"]["sealed_regions"] == [region["id"]]
    assert report["ok"] is False


def test_an_interior_room_reached_only_through_another_room():
    """Two rooms, one exterior door, one connecting door: both reachable."""
    walls = [
        room(1, 512, 512, 2560, 2048),
        # partition splitting the room in two
        {"id": 2, "loop": False, "points": [[1536, 512], [1536, 2048]]},
    ]
    portals = [door(10, 512, 1280), door(11, 1536, 1280)]
    report = analyse(MAP, walls, portals)
    assert report["region_count"] == 2
    assert all(r["reachable_from_exterior"] for r in report["regions"])
    assert report["findings"]["sealed_regions"] == []


def test_removing_the_connecting_door_seals_the_inner_room():
    """The same plan minus one door must flip exactly one region to sealed."""
    walls = [
        room(1, 512, 512, 2560, 2048),
        {"id": 2, "loop": False, "points": [[1536, 512], [1536, 2048]]},
    ]
    report = analyse(MAP, walls, [door(10, 512, 1280)])
    sealed = report["findings"]["sealed_regions"]
    assert len(sealed) == 1, "only the far side of the partition should be cut off"
    reachable = [r for r in report["regions"] if r["reachable_from_exterior"]]
    assert len(reachable) == 1
    assert report["ok"] is False


def test_a_portal_floating_in_open_space_is_flagged():
    """A failed wall-mount leaves a door touching no wall at all."""
    report = analyse(MAP, [room(1, 512, 512, 2560, 2048)], [door(99, 3500, 2800)])
    assert 99 in report["findings"]["portals_not_in_a_wall"]
    assert report["ok"] is False


def test_an_exterior_opening_is_named():
    report = analyse(MAP, [room(1, 512, 512, 2560, 2048)], [door(10, 512, 1280)])
    assert report["findings"]["exterior_openings"] == [10]


def test_a_window_counts_as_an_opening_because_a_portal_is_a_portal():
    """Nothing here can tell a door from a window, and it must not pretend to.

    Both are portals with a position and a radius; only the asset name differs,
    and asset packs name things however they like. So a building whose only
    exterior openings are windows still reports openings — the caller has to
    decide whether any of them is a way in. Naming this "entrances" would have
    made a windows-only building read as enterable.
    """
    windows_only = analyse(MAP, [room(1, 512, 512, 2560, 2048)], [door(20, 1280, 512)])
    assert windows_only["findings"]["exterior_openings"] == [20]
    assert windows_only["ok"] is True


def test_region_bounds_and_area_are_reported_in_sensible_units():
    """A 2048 x 1536 woxel room is 8 x 6 tiles, so ~48 tiles minus its walls."""
    report = analyse(MAP, [room(1, 512, 512, 2560, 2048)], [door(10, 512, 1280)])
    region = report["regions"][0]
    assert 30 < region["area_tiles"] < 48
    x0, y0, x1, y1 = region["bounds"]
    assert 512 <= x0 and x1 <= 2560
    assert 512 <= y0 and y1 <= 2048


def test_tiny_slivers_are_not_reported_as_rooms():
    """Two walls that nearly touch leave a crumb, not a room someone built."""
    walls = [
        {"id": 1, "loop": False, "points": [[1024, 512], [1024, 2048]]},
        {"id": 2, "loop": False, "points": [[1088, 512], [1088, 2048]]},
    ]
    report = analyse(MAP, walls, [], min_room_tiles=2.0)
    assert report["region_count"] == 0
