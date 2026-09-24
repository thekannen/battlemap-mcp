"""Placement validation. Pure geometry over synthetic maps — never touches the socket.

The cases here are the three real failures from one inn build, reproduced as
data: a hearth through an exterior wall, a counter overlapping its neighbour,
and a window buried behind a fireplace. Each has a matching case proving the
correct version of the same placement stays quiet.
"""

from battlemap_mcp.placement import Box, box_for, find_intrusions

# A vertical wall at x = 1000, running the height of a small room.
WALL = {"id": 1, "loop": False, "points": [[1000, 0], [1000, 2000]]}


def obj(element_id: int, x: float, y: float, w: float, h: float, **extra) -> dict:
    element = {
        "id": element_id,
        "asset": f"res://textures/objects/test_{element_id}.png",
        "position": [x, y],
        "texture_size": [w, h],
    }
    element.update(extra)
    return element


def ids(findings: list[dict]) -> list[int]:
    return sorted(f["id"] for f in findings)


# --- the defects -----------------------------------------------------------


def test_an_object_straddling_a_wall_is_reported():
    """The hearth pushed through the exterior wall."""
    hearth = obj(7, 1000, 1000, 350, 400)  # centred ON the wall line
    report = find_intrusions([hearth], [WALL], [])
    assert ids(report["crossing_walls"]) == [7]
    assert report["crossing_walls"][0]["wall_ids"] == [1]
    assert report["ok"] is False


def test_an_object_mostly_outside_the_building_is_reported():
    counter = obj(8, 1120, 900, 800, 200)  # 800 wide straddles x=1000
    report = find_intrusions([counter], [WALL], [])
    assert ids(report["crossing_walls"]) == [8]


def test_an_object_over_a_portal_is_reported():
    """The fireplace in front of the window — flush to the wall, on the glass."""
    window = {"id": 20, "position": [1000, 800], "radius": 128}
    hearth = obj(9, 1175, 800, 350, 400)  # flush: its left edge is the wall
    report = find_intrusions([hearth], [WALL], [window])
    assert ids(report["blocking_portals"]) == [9]
    assert report["blocking_portals"][0]["portal_ids"] == [20]
    assert report["ok"] is False


def test_an_object_standing_in_a_doorway_is_reported():
    door = {"id": 21, "position": [1000, 1500], "radius": 96}
    barrel = obj(10, 1040, 1500, 200, 200)
    report = find_intrusions([barrel], [WALL], [door])
    assert ids(report["blocking_portals"]) == [10]


# --- the placements that must stay quiet ------------------------------------


def test_an_object_flush_against_a_wall_is_not_reported():
    """This is what correct furniture placement looks like; flagging it is useless."""
    bench = obj(11, 1100, 600, 200, 400)  # left edge exactly at x=1000
    report = find_intrusions([bench], [WALL], [])
    assert report["crossing_walls"] == []
    assert report["ok"] is True


def test_a_rotated_object_running_along_a_wall_is_not_reported():
    """The case that decides whether this tool is usable at all.

    A 800x200 counter turned 90 degrees is 200 wide and 800 long, and sits
    happily along the wall. Measured without rotation it reads as 800 wide and
    straddles the wall by 300 on each side — so an axis-aligned checker reports
    every correctly-placed counter in the map and gets switched off.
    """
    counter = obj(12, 1100, 1000, 800, 200, rotation=90)
    report = find_intrusions([counter], [WALL], [])
    assert report["crossing_walls"] == []

    # ... and the same asset unrotated in the same spot genuinely does cross it,
    # so the quiet result above is rotation-awareness, not a dead check.
    assert ids(find_intrusions([obj(12, 1100, 1000, 800, 200)], [WALL], [])["crossing_walls"]) == [
        12
    ]


def test_objects_overlapping_each_other_are_never_reported():
    """A tankard on a table is correct placement, not a collision."""
    table = obj(13, 1500, 1000, 512, 512)
    tankard = obj(14, 1500, 1000, 64, 64)
    plate = obj(15, 1560, 1040, 96, 96)
    report = find_intrusions([table, tankard, plate], [WALL], [])
    assert report["ok"] is True
    assert report["crossing_walls"] == []
    assert "tankard" in report["note"]


def test_an_object_beside_a_door_is_not_reported():
    """Furniture next to a doorway is normal; only intruding into it is not."""
    door = {"id": 21, "position": [1000, 1500], "radius": 96}
    chair = obj(16, 1260, 1500, 200, 200)  # nearest edge 160 away, radius is 96
    report = find_intrusions([chair], [WALL], [door])
    assert report["blocking_portals"] == []


def test_an_object_past_the_end_of_a_wall_is_not_reported():
    """A wall is a segment, not an infinite line.

    The wall stops at y=2000. A table at y=2600 sits on the line's imaginary
    continuation, where there is no wall to cross.
    """
    table = obj(17, 1000, 2600, 512, 512)
    report = find_intrusions([table], [WALL], [])
    assert report["crossing_walls"] == []


def test_a_wall_loop_closes_so_the_last_edge_is_checked_too():
    """build_room stores four corners with the closing edge implicit."""
    room = {
        "id": 2,
        "loop": True,
        "points": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]],
    }
    # sitting on the implicit edge from [0, 2000] back to [0, 0]
    crate = obj(18, 0, 1000, 400, 400)
    assert ids(find_intrusions([crate], [room], [])["crossing_walls"]) == [18]


# --- measurement ------------------------------------------------------------


def test_scale_changes_the_footprint():
    """A half-scale counter fits where a full-size one would not."""
    full = obj(19, 1160, 1000, 400, 200)
    half = obj(19, 1160, 1000, 400, 200, scale=0.5)
    assert ids(find_intrusions([full], [WALL], [])["crossing_walls"]) == [19]
    assert find_intrusions([half], [WALL], [])["crossing_walls"] == []


def test_an_object_with_no_texture_size_is_reported_as_unmeasurable():
    """Not measured and measured-clean are different answers, and it must say which.

    An older bridge returns no texture_size. Silently treating those as fine
    would report a clean map while checking nothing.
    """
    report = find_intrusions([{"id": 30, "asset": "a.png", "position": [1000, 1000]}], [WALL], [])
    assert [u["id"] for u in report["unmeasurable"]] == [30]
    assert report["crossing_walls"] == []


def test_box_for_refuses_a_degenerate_texture():
    assert box_for({"id": 1, "position": [0, 0], "texture_size": [0, 128]}) is None


def test_distance_to_is_measured_in_the_rotated_frame():
    """A point off the long end of a turned box is far; off its side is near."""
    box = Box(cx=0, cy=0, half_w=400, half_h=100, rotation_deg=90)
    assert box.distance_to(0, 0) == 0.0
    assert box.distance_to(150, 0) == 50.0  # 100 half-width once turned
    assert box.distance_to(0, 500) == 100.0  # 400 half-length once turned


def test_nothing_to_check_is_reported_as_ok():
    report = find_intrusions([], [], [])
    assert report["ok"] is True
    assert report["checked"] == 0


def test_a_finding_reports_where_the_object_actually_reaches():
    """ "It crosses this wall" is useless without "and it reaches to here"."""
    counter = obj(40, 1000, 1000, 800, 200, rotation=90)
    finding = find_intrusions([counter], [{"id": 1, "points": [[0, 1000], [2000, 1000]]}], [])[
        "crossing_walls"
    ][0]
    # the asset is 800x200; turned 90 degrees it reaches 200 across and 800 along
    assert finding["asset_size_woxels"] == [800, 200]
    x0, y0, x1, y1 = finding["bounds"]
    assert round(x1 - x0) == 200
    assert round(y1 - y0) == 800


ROOM = {"id": 2, "loop": True, "points": [[3200, 1536], [5760, 1536], [5760, 3584], [3200, 3584]]}


def test_corner_posts_above_the_walls_are_caps_not_crossings():
    """The skills ask for a post over each corner on layer 700; that must not fail."""
    posts = [
        obj(
            20 + i,
            x,
            y,
            96,
            96,
            layer=700,
            asset="res://textures/objects/furniture/pillar_wood_01.png",
        )
        for i, (x, y) in enumerate([(3200, 1536), (5760, 1536), (5760, 3584), (3200, 3584)])
    ]
    report = find_intrusions(posts, [ROOM], [])
    assert report["crossing_walls"] == []
    assert ids(report["wall_caps"]) == [20, 21, 22, 23]
    assert report["ok"] is True


def test_anything_high_over_a_wall_join_is_a_cap():
    bracket = obj(30, 3200, 1536, 96, 96, layer=800)
    report = find_intrusions([bracket], [ROOM], [])
    assert ids(report["wall_caps"]) == [30]
    assert report["ok"] is True


def test_a_post_on_the_default_layer_still_crosses():
    """Below 700 a post is drawn UNDER the wall: a mistake, not a cap."""
    post = obj(40, 3200, 1536, 96, 96, layer=100, asset="res://x/pillar_wood_01.png")
    report = find_intrusions([post], [ROOM], [])
    assert ids(report["crossing_walls"]) == [40]
    assert report["ok"] is False


def test_high_furniture_mid_wall_still_crosses():
    """Layer alone doesn't make a cap: a table through a wall is still a table."""
    table = obj(50, 4480, 1536, 200, 200, layer=700)
    report = find_intrusions([table], [ROOM], [])
    assert ids(report["crossing_walls"]) == [50]
