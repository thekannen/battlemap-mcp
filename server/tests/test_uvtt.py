"""The fixtures are built here, in the shape Dungeondraft 1.2 writes (format
0.3), so no real export has to be checked in.
"""

from __future__ import annotations

import base64
import io
import json
import math

import pytest
from PIL import Image

from battlemap_mcp import server, uvtt
from battlemap_mcp.errors import ValidationError


def _png(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (40, 80, 120, 255)).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _pt(x, y):
    return {"x": x, "y": y}


def _export(tmp_path, **overrides):
    """A 10x8-tile export at 64 ppi: one room with a door on its top wall."""
    data = {
        "format": 0.3,
        "resolution": {"map_origin": _pt(0, 0), "map_size": _pt(10, 8), "pixels_per_grid": 64},
        # The room's walls, broken at the doorway 3.5..4.5 on y=2, as exported.
        "line_of_sight": [
            [_pt(3.5, 2), _pt(2, 2), _pt(2, 6), _pt(8, 6), _pt(8, 2), _pt(4.5, 2)],
        ],
        "objects_line_of_sight": [],
        "portals": [
            {
                "position": _pt(4, 2),
                "bounds": [_pt(3.5, 2), _pt(4.5, 2)],
                "rotation": 0,
                "closed": True,
                "freestanding": False,
            }
        ],
        "environment": {"baked_lighting": True, "ambient_light": "ff203040"},
        "lights": [
            {
                "position": _pt(5, 4),
                "range": 6,
                "intensity": 0.8,
                "color": "ffffb060",
                "shadows": True,
            }
        ],
        "image": _png(640, 512),
    }
    data.update(overrides)
    path = tmp_path / "room.dd2vtt"
    path.write_text(json.dumps(data))
    return path


def test_reading_skips_the_image_but_finds_it(tmp_path):
    export = uvtt.read(_export(tmp_path))
    assert export.tiles == (10, 8)
    assert export.ambient == "#203040"
    assert export.image_span is not None
    start, end = export.image_span
    assert export.path.read_bytes()[start : start + 8] == b"iVBORw0K"
    assert export.path.read_bytes()[end : end + 1] == b'"'


def test_a_file_that_is_not_an_export_is_refused(tmp_path):
    bad = tmp_path / "notes.dd2vtt"
    bad.write_text("{not json")
    with pytest.raises(uvtt.UvttError, match="not a Universal VTT"):
        uvtt.read(bad)
    bad.write_text(json.dumps({"format": 0.3}))
    with pytest.raises(uvtt.UvttError, match="resolution"):
        uvtt.read(bad)


def test_the_doorway_is_rejoined_into_a_closed_wall(tmp_path):
    planned = uvtt.plan(uvtt.read(_export(tmp_path)))
    assert planned.joined_doorways == 1
    (wall,) = planned.walls
    assert wall["loop"] is True
    # The doorway edges were straight-line vertices and are gone: 4 corners.
    assert sorted(map(tuple, wall["points"])) == sorted(
        [(512.0, 512.0), (512.0, 1536.0), (2048.0, 1536.0), (2048.0, 512.0)]
    )
    (portal,) = planned.portals
    assert portal == {
        "position": [1024.0, 512.0],
        "radius": 128.0,
        "closed": True,
        "freestanding": False,
        "rotation": 0.0,
    }


def test_two_doors_side_by_side_still_join_the_wall():
    """No wall run is left between adjacent doors; their doorways chain."""
    runs = [[(0, 0), (2, 0)], [(4, 0), (6, 0)]]
    portals = [
        {"position": _pt(2.5, 0), "bounds": [_pt(2, 0), _pt(3, 0)]},
        {"position": _pt(3.5, 0), "bounds": [_pt(3, 0), _pt(4, 0)]},
    ]
    joined, doorways = uvtt.join_at_portals(runs, portals)
    assert joined == [[(0, 0), (6, 0)]]
    assert doorways == 2


def test_a_t_junction_is_not_merged():
    runs = [[(0, 0), (2, 0)], [(2, 0), (4, 0)], [(2, 0), (2, 3)]]
    joined, _ = uvtt.join_at_portals(runs, [])
    assert len(joined) == 3


def test_a_doorway_with_no_wall_is_dropped():
    joined, doorways = uvtt.join_at_portals([], [{"bounds": [_pt(0, 0), _pt(1, 0)]}])
    assert joined == [] and doorways == 0


def test_a_region_export_is_moved_to_the_origin_and_cropped(tmp_path):
    """Region exports keep the source map's coordinates and list all of it."""
    path = _export(
        tmp_path,
        resolution={"map_origin": _pt(20, 30), "map_size": _pt(10, 8), "pixels_per_grid": 64},
        line_of_sight=[
            [_pt(22, 32), _pt(28, 32)],
            [_pt(60, 70), _pt(61, 70)],
        ],
        portals=[],
        lights=[
            {"position": _pt(25, 34), "range": 4, "intensity": 1, "color": "ffffffff"},
            {"position": _pt(2, 2), "range": 4, "intensity": 1, "color": "ffffffff"},
        ],
    )
    planned = uvtt.plan(uvtt.read(path))
    assert [w["points"] for w in planned.walls] == [[[512.0, 512.0], [2048.0, 512.0]]]
    assert [light["position"] for light in planned.lights] == [[1280.0, 1024.0]]
    assert planned.skipped == {"walls": 1, "portals": 0, "lights": 1, "blockers": 0}


def test_lights_keep_the_editors_own_values(tmp_path):
    (light,) = uvtt.plan(uvtt.read(_export(tmp_path))).lights
    assert light == {
        "position": [1280.0, 1024.0],
        "range": 6.0,
        "energy": 0.8,
        "color": "#ffb060",
        "shadows": True,
    }


def test_a_blocker_is_fitted_to_its_outline():
    # A 2x1-tile rectangle centred on (3, 3), turned 30 degrees.
    turn = math.radians(30)
    corners = [(-1, -0.5), (1, -0.5), (1, 0.5), (-1, 0.5)]
    outline = [
        (3 + x * math.cos(turn) - y * math.sin(turn), 3 + x * math.sin(turn) + y * math.cos(turn))
        for x, y in corners
    ]
    fit = uvtt.fit_blocker(outline + outline[:1])
    assert fit["center"] == [768.0, 768.0]
    assert fit["rotation"] == pytest.approx(30.0, abs=0.1)
    assert fit["length"] == pytest.approx(512.0, abs=0.5)
    assert fit["width"] == pytest.approx(256.0, abs=0.5)


def test_the_trace_covers_the_region(tmp_path):
    export = uvtt.read(_export(tmp_path))
    image, scale = uvtt.write_trace_image(export, tmp_path / "out")
    with Image.open(image) as saved:
        assert saved.size == (640, 512)
    # 10 tiles of 256 woxels across 640 pixels.
    assert scale == pytest.approx(4.0)


def test_a_large_trace_is_shrunk(tmp_path, monkeypatch):
    monkeypatch.setattr(uvtt, "TRACE_MAX_EDGE", 100)
    image, scale = uvtt.write_trace_image(uvtt.read(_export(tmp_path)), tmp_path / "out")
    with Image.open(image) as saved:
        assert max(saved.size) == 100
    assert scale == pytest.approx(10 * 256 / 100)


class _Map:
    """Stand-in for the bridge: a 10x8-tile map, recording every command."""

    def __init__(self, tiles=(10, 8), counts=None):
        self.tiles = tiles
        self.counts = counts or {}
        self.calls: list[tuple[str, dict]] = []

    def request(self, cmd, **params):
        self.calls.append((cmd, params))
        if cmd == "get_status":
            return {
                "map_open": True,
                "map_size_woxels": [self.tiles[0] * 256, self.tiles[1] * 256],
                "counts": self.counts,
            }
        return {"ok": True, "id": len(self.calls)}

    def sent(self, cmd):
        return [params for name, params in self.calls if name == cmd]


@pytest.fixture
def fake_map(monkeypatch, tmp_path):
    fake = _Map()
    monkeypatch.setattr(server.bridge, "request", fake.request)
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(tmp_path / "captures"))
    return fake


def test_the_preview_changes_nothing(tmp_path, fake_map):
    preview = server.import_dd2vtt(str(_export(tmp_path)))
    assert preview["changed"] is False
    assert preview["size_matches"] is True
    assert (preview["walls"], preview["portals"], preview["lights"]) == (1, 1, 1)
    assert [cmd for cmd, _ in fake_map.calls] == ["get_status"]


def test_confirm_rebuilds_walls_then_doors_then_lights(tmp_path, fake_map):
    result = server.import_dd2vtt(str(_export(tmp_path)), confirm=True)
    order = [cmd for cmd, _ in fake_map.calls if cmd != "get_status"]
    assert order[0] == "checkpoint"
    assert order.index("draw_wall") < order.index("add_portal") < order.index("add_light")
    (wall,) = fake_map.sent("draw_wall")
    assert wall["loop"] is True and len(wall["points"]) == 4
    (door,) = fake_map.sent("add_portal")
    assert (door["x"], door["y"], door["mount"]) == (1024.0, 512.0, "wall")
    assert door["asset"] == server.DD2VTT_DOOR
    assert fake_map.sent("set_ambient_light") == [{"color": "#203040"}]
    (trace,) = fake_map.sent("set_trace_image")
    assert trace["scale"] == pytest.approx(4.0) and trace["center"] is True
    assert result["changed"] is True and result["failures"] == []
    assert result["checkpoint"] == "import_dd2vtt"


def test_imported_points_are_never_grid_snapped(tmp_path, fake_map, monkeypatch):
    """A user's default snap would otherwise move every imported point."""
    seen = []
    real = server._snap_grid

    def spy(snap, *args, **kwargs):
        seen.append(snap)
        return real(snap, *args, **kwargs)

    monkeypatch.setattr(server, "_snap_grid", spy)
    server.import_dd2vtt(str(_export(tmp_path)), confirm=True, trace=False)
    assert seen and set(seen) == {"none"}


def test_a_size_mismatch_is_refused_unless_resizing(tmp_path, fake_map):
    fake_map.tiles = (30, 20)
    refused = server.import_dd2vtt(str(_export(tmp_path)), confirm=True)
    assert "conflict" in refused and refused["changed"] is False
    assert not fake_map.sent("draw_wall")

    resized = server.import_dd2vtt(str(_export(tmp_path)), confirm=True, resize=True, trace=False)
    assert fake_map.sent("set_map_size") == [{"width": 10, "height": 8}]
    assert resized["resized_from"] == [30, 20] and resized["map_tiles"] == [10, 8]


def test_a_failed_item_is_reported_and_the_rest_still_built(tmp_path, fake_map, monkeypatch):
    original = fake_map.request

    def refuse_portals(cmd, **params):
        if cmd == "add_portal":
            raise server.BridgeCommandError("could not mount a portal there")
        return original(cmd, **params)

    monkeypatch.setattr(server.bridge, "request", refuse_portals)
    result = server.import_dd2vtt(str(_export(tmp_path)), confirm=True, trace=False)
    assert result["portal_ids"] == []
    assert result["failures"] == ["portal: could not mount a portal there"]
    assert len(result["light_ids"]) == 1


def test_a_map_with_content_gets_a_warning(tmp_path, fake_map):
    fake_map.counts = {"walls": 3}
    assert "warning" in server.import_dd2vtt(str(_export(tmp_path)))


def test_an_unreadable_path_is_a_validation_error(tmp_path, fake_map):
    with pytest.raises(server.ValidationError, match="cannot read"):
        server.import_dd2vtt(str(tmp_path / "missing.dd2vtt"))


def test_open_portals_come_in_as_windows(tmp_path, fake_map):
    """Runtime behavior and validation."""
    path = _export(
        tmp_path,
        portals=[
            {
                "position": _pt(4, 2),
                "bounds": [_pt(3.5, 2), _pt(4.5, 2)],
                "rotation": 0,
                "closed": False,
                "freestanding": False,
            }
        ],
    )
    server.import_dd2vtt(str(path), confirm=True, trace=False)
    (window,) = fake_map.sent("add_portal")
    assert window["asset"] == server.DD2VTT_WINDOW and window["closed"] is False


def test_light_range_is_the_editors_range_both_ways(monkeypatch):
    """Runtime behavior and validation."""
    sent = []

    def bridge(cmd, **kw):
        sent.append((cmd, kw))
        light = {"id": 7, "kind": "light", "range": 3.0, "energy": 1}
        if cmd == "get_element":
            return dict(light)
        if cmd == "list_elements":
            return {"elements": [dict(light), {"id": 8, "kind": "object", "range": 3.0}]}
        return {"ok": True, "id": 7}

    monkeypatch.setattr(server.bridge, "request", bridge)
    server.add_light(x=0, y=0, range=6, snap="none")
    assert sent[-1][1]["range"] == 3.0
    assert server.get_element(7)["range"] == 6.0
    light, other = server.list_elements(kind="lights")["elements"]
    assert light["range"] == 6.0 and other["range"] == 3.0  # only lights convert


def test_an_imported_light_keeps_the_exported_range(tmp_path, fake_map):
    server.import_dd2vtt(str(_export(tmp_path)), confirm=True, trace=False)
    (light,) = fake_map.sent("add_light")
    # The export's Range 6 reaches the bridge as texture_scale 3.
    assert light["range"] == 3.0


def test_a_trace_from_a_non_ascii_name_is_still_recognised(tmp_path):
    path = _export(tmp_path)
    renamed = path.with_name("Château Noir.dd2vtt")
    path.rename(renamed)
    image, _ = uvtt.write_trace_image(uvtt.read(renamed), tmp_path / "out")
    assert server._TRACE_NAME.fullmatch(image.name), image.name


def test_a_wall_is_cut_at_its_doorway_like_dungeondrafts_export():
    """A loop with one door: one run, from one edge of the doorway round to the other."""
    square = [[0, 0], [1024, 0], [1024, 1024], [0, 1024]]
    door = {"position": [512, 0], "radius": 128}
    (run,) = uvtt.split_wall(square, True, [door])
    assert run[0] == [640.0, 0.0] and run[-1] == [384.0, 0.0]
    assert [1024.0, 0.0] in run and [0.0, 0.0] in run
    # Without a portal the loop comes back closed.
    (closed,) = uvtt.split_wall(square, True, [])
    assert closed[0] == closed[-1]


def test_two_doors_on_an_open_wall_make_three_runs():
    runs = uvtt.split_wall(
        [[0, 0], [2048, 0]],
        False,
        [{"position": [512, 0], "radius": 128}, {"position": [1536, 0], "radius": 128}],
    )
    assert runs == [
        [[0.0, 0.0], [384.0, 0.0]],
        [[640.0, 0.0], [1408.0, 0.0]],
        [[1664.0, 0.0], [2048.0, 0.0]],
    ]


def test_an_export_round_trips_through_the_importer(tmp_path):
    document = uvtt.build(
        size_tiles=(4, 4),
        pixels_per_grid=10,
        walls=[{"id": 1, "points": [[0, 0], [1024, 0], [1024, 1024], [0, 1024]], "loop": True}],
        portals=[
            {
                "kind": "wall_portal",
                "wall_id": 1,
                "position": [512, 0],
                "radius": 128,
                "direction": [-1, 0],
                "closed": True,
            },
            {
                "kind": "wall_portal",
                "wall_id": 1,
                "position": [1024, 512],
                "radius": 128,
                "direction": [0, 1],
                "closed": False,
            },
        ],
        lights=[
            {
                "position": [512, 512],
                "range": 6.0,
                "energy": 0.8,
                "color": "#ffb060",
                "shadows": True,
            }
        ],
        blockers=[{"opaque_bounds": [100, 100, 356, 228], "block_light": True}],
        ambient="#203040",
        image_png=base64.b64decode(_png(40, 40)),
    )
    door, window = document["portals"]
    assert door["rotation"] == pytest.approx(math.pi) and door["closed"] is True
    assert {(b["x"], b["y"]) for b in door["bounds"]} == {(1.5, 0.0), (2.5, 0.0)}
    assert window["closed"] is False and window["freestanding"] is False
    assert document["lights"][0]["color"] == "ffffb060" and document["lights"][0]["range"] == 6.0
    assert document["environment"]["ambient_light"] == "ff203040"
    assert len(document["objects_line_of_sight"]) == 1
    path = tmp_path / "out.dd2vtt"
    path.write_text(json.dumps(document))
    planned = uvtt.plan(uvtt.read(path))
    (wall,) = planned.walls
    assert wall["loop"] and len(wall["points"]) == 4 and planned.joined_doorways == 2
    assert [p["closed"] for p in planned.portals] == [True, False]
    assert planned.lights[0]["range"] == 6.0 and planned.ambient == "#203040"
    assert len(planned.blockers) == 1


def test_light_blockers_get_outlines_from_what_the_bridge_reports():
    """The bridge lists objects without bounds, so the export must derive them."""
    listed = [
        {
            "id": 1,
            "position": [1000, 1000],
            "rotation": 0,
            "scale": 2.0,
            "texture_size": [300, 300],
            "block_light": True,
        },
        {"id": 2, "position": [0, 0], "texture_size": [100, 100], "block_light": False},
    ]
    blockers = server._light_blockers(listed)
    assert [b["id"] for b in blockers] == [1]
    assert blockers[0]["bounds"] == [700.0, 700.0, 1300.0, 1300.0]
    assert "bounds" not in listed[0]
    document = uvtt.build(
        size_tiles=(10, 10),
        pixels_per_grid=100,
        walls=[],
        portals=[],
        lights=[],
        blockers=blockers,
        ambient=None,
        image_png=base64.b64decode(_png(40, 40)),
    )
    assert len(document["objects_line_of_sight"]) == 1


def test_wall_color_tints_every_imported_wall(tmp_path, fake_map):
    """Runtime behavior and validation."""
    preview = server.import_dd2vtt(str(_export(tmp_path)), wall_color="#d8c49a")
    assert preview["wall_color"] == "#d8c49a"
    server.import_dd2vtt(str(_export(tmp_path)), confirm=True, trace=False, wall_color="#d8c49a")
    assert [w["color"] for w in fake_map.sent("draw_wall")] == ["#d8c49a"]


def test_a_bad_wall_color_is_refused_before_anything_is_read(tmp_path, fake_map):
    with pytest.raises(ValidationError):
        server.import_dd2vtt(str(_export(tmp_path)), wall_color="sandstone")
    assert fake_map.calls == []
