"""The Custom Snap Mod's grid math, ported. Expected values are worked by hand
from snappy_mod.gd v1.1.2, including its quirks, so a "fix" shows up here."""

import math

import pytest

from battlemap_mcp.snapping import SnapGrid, _gd_round, grid_from_settings, snap, snap_rect

SQUARE_64 = SnapGrid("square", (64.0, 64.0))


def test_square_snaps_to_the_nearest_interval():
    assert snap(SQUARE_64, 100, 90) == (128.0, 64.0)


def test_square_rounds_an_exact_half_down():
    # fmod(96, 64) == 32 is not > 32, so it stays at 64.
    assert snap(SQUARE_64, 96, 96) == (64.0, 64.0)


def test_square_keeps_the_mods_negative_quirk():
    """fmod keeps the dividend's sign, so below the offset nothing rounds up."""
    grid = SnapGrid("square", (64.0, 64.0), offset=(32.0, 32.0))
    # 10 - 32 = -22: floor gives -64 and fmod(-22, 64) = -22 never exceeds 32,
    # so the mod lands on -32 even though +32 is nearer. The port must agree.
    assert snap(grid, 10, 10) == (-32.0, -32.0)


def test_rectangular_intervals_snap_per_axis():
    grid = SnapGrid("square", (100.0, 50.0))
    assert snap(grid, 149, 74) == (100.0, 50.0)


def test_horizontal_hex_lands_on_a_lattice_point():
    grid = SnapGrid("hex_h", (128.0, 128.0), to_corner=False)
    # size = 128 / 1.5; hex (1, 0) is at (1.5 * size, sqrt(3)/2 * size).
    size = 128 / 1.5
    assert snap(grid, 130, 70) == (128.0, round(math.sqrt(3) / 2 * size, 3))


def test_vertical_hex_lands_on_a_lattice_point():
    grid = SnapGrid("hex_v", (128.0, 128.0), to_corner=False)
    size = 128 / 1.5
    # hex (0, 1) is at (sqrt(3)/2 * size, 1.5 * size).
    assert snap(grid, 70, 130) == (round(math.sqrt(3) / 2 * size, 3), 128.0)


@pytest.mark.parametrize("geometry", ["square", "hex_h", "hex_v"])
@pytest.mark.parametrize("to_corner", [True, False])
def test_snapping_a_snapped_point_changes_nothing(geometry, to_corner):
    grid = SnapGrid(geometry, (96.0, 96.0), offset=(10.0, -7.0), to_corner=to_corner)
    for x, y in [(0, 0), (517.3, 911.8), (4480, 2560), (33.3, 12.1)]:
        once = snap(grid, x, y)
        assert once is not None
        assert snap(grid, *once) == pytest.approx(once, abs=1e-3)


@pytest.mark.parametrize("geometry", ["hex_h", "hex_v"])
def test_a_hex_snap_moves_a_point_less_than_one_interval(geometry):
    grid = SnapGrid(geometry, (128.0, 128.0))
    for x, y in [(517.3, 911.8), (4480, 2560), (1000, 1000), (77, 301)]:
        sx, sy = snap(grid, x, y)
        assert math.hypot(sx - x, sy - y) < 128


def test_isometric_is_unimplemented_in_the_mod_and_never_applied():
    assert snap(SnapGrid("isometric", (64.0, 64.0)), 100, 100) is None


def test_godot_rounds_halves_away_from_zero():
    assert [_gd_round(v) for v in (0.5, 1.5, 2.5, -0.5, -2.5)] == [1, 2, 3, -1, -3]


def test_live_settings_become_a_grid():
    grid = grid_from_settings(
        {
            "active_geometry": 2,
            "snap_interval": [150, 150],
            "snap_offset": [0, 0],
            "radial_mode_to_corner": False,
        }
    )
    assert grid is not None
    assert (grid.geometry, grid.interval, grid.to_corner) == ("hex_h", (150.0, 150.0), False)


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"active_geometry": 9, "snap_interval": [64, 64]},
        {"active_geometry": 0, "snap_interval": [0, 64]},
    ],
)
def test_unreadable_settings_are_no_grid(settings):
    assert grid_from_settings(settings) is None


def test_an_offset_rounds_to_the_nearest_step_in_both_directions():
    from battlemap_mcp.snapping import snap_delta

    grid = SnapGrid("square", (100.0, 50.0), offset=(10.0, 20.0))
    # Measured live: the mod's floor rule sent a -61 move to -100.
    assert snap_delta(grid, 137, -61) == (100.0, -50.0)
    assert snap_delta(grid, -10, 10) == (0.0, 0.0)


def _on_grid(grid, x, y):
    again = snap(grid, x, y)
    return abs(again[0] - x) < 0.01 and abs(again[1] - y) < 0.01


@pytest.mark.parametrize(
    "grid",
    [
        SnapGrid("hex_h", (128.0, 128.0), to_corner=False),
        SnapGrid("hex_v", (128.0, 128.0), to_corner=False),
        SnapGrid("hex_h", (64.0, 64.0), to_corner=True),
        SnapGrid("hex_v", (100.0, 60.0), offset=(40.0, 25.0)),
        SnapGrid("square", (100.0, 60.0), offset=(40.0, 25.0)),
    ],
)
@pytest.mark.parametrize(
    "rect",
    [[3277, 1853, 1290, 1016], [10, 10, 500, 300], [-300, 700, 1111, 777], [0, 0, 900, 900]],
)
def test_a_snapped_rect_has_all_four_corners_on_the_grid(grid, rect):
    x0, y0, x1, y1 = snap_rect(grid, rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3])
    assert x1 > x0 and y1 > y0
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        assert _on_grid(grid, x, y), (x, y)
    # Still the rect that was asked for, within about one step per corner.
    step = max(grid.interval) * 1.6
    assert abs(x0 - rect[0]) <= step and abs(y0 - rect[1]) <= step
    assert abs(x1 - rect[0] - rect[2]) <= step and abs(y1 - rect[1] - rect[3]) <= step


def test_a_square_rect_snaps_its_two_corners_as_before():
    assert snap_rect(SQUARE_64, 10, 10, 510, 310) == (0.0, 0.0, 512.0, 320.0)
