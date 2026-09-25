"""Runtime behavior and validation."""

from __future__ import annotations

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError

HEX = {
    "custom_snap_enabled": True,
    "active_geometry": 2,  # hex_h
    "snap_interval": [128, 128],
    "snap_offset": [0, 0],
    "radial_mode_to_corner": False,
}


@pytest.fixture
def bridge(monkeypatch):
    state = {
        "vanilla_snapping": True,
        "mod_loaded": True,
        "settings": dict(HEX),
        "preset": "Large Horizontal Hex",
    }
    sent: list[tuple[str, dict]] = []

    def request(command, **params):
        if command == "get_snap_settings":
            if "points" in params:
                # The mod's own answers: v1.1.2 returns null for isometric.
                answer = state.get("mod_answer", lambda x, y: None)
                return {**state, "mod_snapped": [answer(*p) for p in params["points"]]}
            return state
        sent.append((command, params))
        return replies.get(command, {"id": 1})

    replies: dict = {}
    state["replies"] = replies
    monkeypatch.setattr(server.bridge, "request", request)
    monkeypatch.setattr(server, "_SCATTERED", set())
    return state, sent


def placed(sent):
    [(_, params)] = sent
    return params


def test_auto_snaps_to_the_mods_grid(bridge):
    _, sent = bridge
    result = server.place_object("res://a.png", x=130, y=70, snap="auto")
    params = placed(sent)
    assert (params["x"], params["y"]) == (128.0, 73.901)
    assert result["snap"]["applied"] is True
    assert result["snap"]["grid"]["geometry"] == "hex_h"


def test_none_is_the_default_and_never_asks_for_settings(bridge):
    _, sent = bridge
    result = server.place_object("res://a.png", x=130, y=70)
    assert (placed(sent)["x"], placed(sent)["y"]) == (130, 70)
    assert "snap" not in result


def test_auto_leaves_points_alone_when_the_user_turned_snapping_off(bridge):
    state, sent = bridge
    state["vanilla_snapping"] = False
    result = server.place_object("res://a.png", x=130, y=70, snap="auto")
    assert (placed(sent)["x"], placed(sent)["y"]) == (130, 70)
    assert result["snap"]["applied"] is False
    assert "S key" in result["snap"]["reason"]


def test_auto_does_nothing_without_the_mod(bridge):
    state, sent = bridge
    state.update(mod_loaded=False, settings=None)
    result = server.place_object("res://a.png", x=130, y=70, snap="auto")
    assert (placed(sent)["x"], placed(sent)["y"]) == (130, 70)
    assert "not loaded or not enabled" in result["snap"]["reason"]


def test_grid_falls_back_to_vanillas_half_tile(bridge):
    state, sent = bridge
    state["settings"]["custom_snap_enabled"] = False
    result = server.place_object("res://a.png", x=200, y=50, snap="grid")
    assert (placed(sent)["x"], placed(sent)["y"]) == (256.0, 0.0)
    assert result["snap"]["grid"]["interval"] == [128.0, 128.0]


def test_isometric_is_reported_and_not_applied_where_the_mod_cannot_snap_it(bridge):
    state, sent = bridge
    state["settings"]["active_geometry"] = 3
    result = server.place_object("res://a.png", x=130, y=70, snap="auto")
    assert (placed(sent)["x"], placed(sent)["y"]) == (130, 70)
    assert "isometric" in result["snap"]["reason"]


def test_walls_paths_lights_and_batches_snap_every_point(bridge):
    state, sent = bridge
    state["settings"].update(active_geometry=0, snap_interval=[64, 64])
    server.draw_wall([[10, 10], [100, 90]], snap="auto")
    server.draw_path([[10, 10], [100, 90]], asset="res://p.png", snap="auto")
    server.add_light(x=100, y=90, snap="auto")
    server.place_objects(
        [{"asset": "res://a.png", "x": 100, "y": 90}, {"asset": "res://a.png"}], snap="auto"
    )
    wall, path, light, batch = (params for _, params in sent)
    assert wall["points"] == [[0.0, 0.0], [128.0, 64.0]]
    assert path["points"] == [[0.0, 0.0], [128.0, 64.0]]
    assert (light["x"], light["y"]) == (128.0, 64.0)
    assert (batch["objects"][0]["x"], batch["objects"][0]["y"]) == (128.0, 64.0)
    assert "x" not in batch["objects"][1]  # no position: the bridge centres it


def test_an_unknown_mode_is_refused_before_anything_is_sent(bridge):
    _, sent = bridge
    with pytest.raises(ValidationError, match="snap"):
        server.place_object("res://a.png", x=1, y=1, snap="hex")
    assert sent == []


def test_get_snap_settings_says_whether_auto_would_snap(bridge):
    report = server.get_snap_settings()
    assert report["mod_enabled"] is True and report["auto_snaps"] is True
    assert report["preset"] == "Large Horizontal Hex"


def _square_64(state):
    state["settings"].update(active_geometry=0, snap_interval=[64, 64])


def test_build_room_snaps_both_rect_corners(bridge):
    state, sent = bridge
    _square_64(state)
    server.build_room(rect=[10, 10, 500, 300], floor="none", snap="auto")
    # (10, 10) -> (0, 0); (510, 310) -> (512, 320).
    assert placed(sent)["rect"] == [0.0, 0.0, 512.0, 320.0]


def test_build_room_refuses_a_rect_the_grid_collapses(bridge):
    state, sent = bridge
    _square_64(state)
    with pytest.raises(ValidationError, match="collapses"):
        server.build_room(rect=[10, 10, 20, 20], floor="none", snap="auto")
    assert sent == []


def test_moves_and_duplicates_travel_whole_grid_steps(bridge):
    state, sent = bridge
    _square_64(state)
    server.move_elements([1, 2], dx=100, dy=-90, snap="auto")
    server.duplicate_object(1, dx=70, dy=10, snap="auto")
    moved, duplicated = (params for _, params in sent)
    # Nearest whole steps, both ways: -90 is -64, not the mod's floor of -128.
    assert (moved["dx"], moved["dy"]) == (128.0, -64.0)
    assert (duplicated["dx"], duplicated["dy"]) == (64.0, 0.0)


def test_point_tools_snap_their_position(bridge):
    state, sent = bridge
    _square_64(state)
    server.move_element(5, x=100, y=90, snap="auto")
    server.add_portal("res://door.png", x=100, y=90, snap="auto")
    server.place_prefab("Well", x=100, y=90, snap="auto")
    for _, params in sent:
        assert (params["x"], params["y"]) == (128.0, 64.0)


def test_a_delta_ignores_the_grids_offset(bridge):
    state, sent = bridge
    state["settings"].update(active_geometry=0, snap_interval=[64, 64], snap_offset=[40, 25])
    server.move_elements([1], dx=64, dy=64, snap="auto")
    assert (placed(sent)["dx"], placed(sent)["dy"]) == (64.0, 64.0)


def test_grid_falls_back_to_the_vanilla_grid_of_each_tool(bridge):
    """Measured: walls and lights snap to the tile, objects and paths to the half."""
    state, sent = bridge
    state["settings"]["custom_snap_enabled"] = False
    server.draw_wall([[200, 50], [700, 50]], snap="grid")
    server.add_light(x=200, y=50, snap="grid")
    server.draw_path([[200, 50], [700, 50]], asset="res://p.png", snap="grid")
    wall, light, path = (params for _, params in sent)
    assert wall["points"] == [[256.0, 0.0], [768.0, 0.0]]
    assert (light["x"], light["y"]) == (256.0, 0.0)
    assert path["points"] == [[256.0, 0.0], [640.0, 0.0]]


def test_isometric_snaps_like_horizontal_hex_where_the_mod_does(bridge):
    """Runtime behavior and validation."""
    from battlemap_mcp import snapping

    state, sent = bridge
    state["settings"]["active_geometry"] = 3
    hexh = snapping.SnapGrid("hex_h", (128.0, 128.0), to_corner=False)
    state["mod_answer"] = lambda x, y: list(snapping.snap(hexh, x, y))
    result = server.place_object("res://a.png", x=130, y=70, snap="auto")
    assert (placed(sent)["x"], placed(sent)["y"]) == snapping.snap(hexh, 130, 70)
    assert result["snap"]["applied"] is True
    assert result["snap"]["grid"]["geometry"] == "isometric"
    assert result["snap"]["grid"]["snaps_like"] == "hex_h"


def test_isometric_the_port_does_not_know_is_not_applied(bridge):
    state, sent = bridge
    state["settings"]["active_geometry"] = 3
    state["mod_answer"] = lambda x, y: [x + 1, y + 1]
    result = server.place_object("res://a.png", x=130, y=70, snap="auto")
    assert (placed(sent)["x"], placed(sent)["y"]) == (130, 70)
    assert result["snap"]["applied"] is False


def _panel_placements(value):
    import json

    from battlemap_mcp import user_settings

    user_settings.path().write_text(json.dumps({"snap_default": value}), encoding="utf-8")


def test_get_snap_settings_reports_the_users_placements_choice(bridge):
    """Runtime behavior and validation."""
    _panel_placements("auto")
    report = server.get_snap_settings()
    assert report["placements"] == {"value": "auto", "source": "panel"}
    assert "leave snap out" in report["placements_note"]
    assert "only" in report["placements_note"] and "'none'" in report["placements_note"]


def test_get_snap_settings_says_exact_placements_need_auto(bridge):
    report = server.get_snap_settings()
    assert report["placements"] == {"value": "none", "source": "default"}
    assert "snap='auto'" in report["placements_note"]


def test_the_none_option_is_described_as_opt_out_not_the_norm():
    doc = " ".join((server.get_snap_settings.__doc__ or "").split())
    assert "only when the user asks for exact" in doc
    assert "only when the user asks for exact" in server.SNAP_HELP


def _scatter(state, ids):
    state["replies"]["scatter_objects"] = {"placed": len(ids), "ids": ids}
    server.scatter_objects(["res://rubble.png"], rect=[0, 0, 500, 500], count=len(ids))


def test_moving_scattered_detail_ignores_the_panels_snap_default(bridge):
    """With 'Snap to my grid', a session nudged a scattered rubble piece and it
    landed on a hex point (Windows, 2026-09-24): scatter should stay loose."""
    state, sent = bridge
    _panel_placements("auto")
    _scatter(state, [40, 41])
    sent.clear()
    result = server.move_element(40, x=130, y=70)
    assert (sent[-1][1]["x"], sent[-1][1]["y"]) == (130, 70)
    assert result["snap"]["applied"] is False
    assert "scatter" in result["snap"]["reason"]
    server.move_elements([40, 41], dx=37, dy=-11)
    assert (sent[-1][1]["dx"], sent[-1][1]["dy"]) == (37, -11)


def test_an_explicit_snap_still_snaps_scattered_detail(bridge):
    state, sent = bridge
    _panel_placements("auto")
    _scatter(state, [40])
    sent.clear()
    server.move_element(40, x=130, y=70, snap="auto")
    assert (sent[-1][1]["x"], sent[-1][1]["y"]) != (130, 70)


def test_other_elements_still_follow_the_panels_default(bridge):
    state, sent = bridge
    _panel_placements("auto")
    _scatter(state, [40])
    sent.clear()
    server.move_element(7, x=130, y=70)
    assert (sent[-1][1]["x"], sent[-1][1]["y"]) != (130, 70)
    # A group with anything placed deliberately moves by whole grid steps.
    server.move_elements([7, 40], dx=37, dy=-11)
    assert (sent[-1][1]["dx"], sent[-1][1]["dy"]) != (37, -11)


def test_opening_a_map_forgets_what_was_scattered(bridge, monkeypatch):
    state, sent = bridge
    _panel_placements("auto")
    _scatter(state, [40])
    server.open_map("C:/maps/other.dungeondraft_map", wait=False)
    sent.clear()
    server.move_element(40, x=130, y=70)
    assert (sent[-1][1]["x"], sent[-1][1]["y"]) != (130, 70)
