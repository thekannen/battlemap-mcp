"""Pre-flight semantic rules. These never touch the socket."""

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError
from battlemap_mcp.validation import (
    reject_smart_tiles,
    require_choice,
    require_finite,
    require_hex_color,
    require_one_of,
    require_positive,
)


def test_one_of_accepts_exactly_rect():
    require_one_of(rect=[0, 0, 1, 1], points=None)


def test_one_of_accepts_exactly_points():
    require_one_of(rect=None, points=[[0, 0], [1, 1], [2, 2]])


def test_one_of_rejects_both():
    with pytest.raises(ValidationError, match="exactly one"):
        require_one_of(rect=[0, 0, 1, 1], points=[[0, 0]])


def test_one_of_rejects_neither():
    with pytest.raises(ValidationError, match="exactly one"):
        require_one_of(rect=None, points=None)


@pytest.mark.parametrize("value", ["#ffb066", "#000000", "#FFFFFF"])
def test_hex_color_accepts_valid(value):
    require_hex_color(value, "color")


@pytest.mark.parametrize("value", ["ffb066", "#fff", "#gggggg", "red", "#ffb0666"])
def test_hex_color_rejects_invalid(value):
    with pytest.raises(ValidationError, match="color"):
        require_hex_color(value, "color")


def test_hex_color_allows_empty_meaning_default():
    require_hex_color("", "color")


def test_choice_accepts_member():
    require_choice(1, [0, 1, 2], "wall_joint")


def test_choice_rejects_non_member():
    with pytest.raises(ValidationError, match="wall_joint"):
        require_choice(7, [0, 1, 2], "wall_joint")


def test_positive_accepts():
    require_positive(0.5, "scale")


@pytest.mark.parametrize("value", [0, -1.0])
def test_positive_rejects(value):
    with pytest.raises(ValidationError, match="scale"):
        require_positive(value, "scale")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_positive_rejects_non_finite(value):
    with pytest.raises(ValidationError, match="scale"):
        require_positive(value, "scale")


def test_positive_rejects_nan_with_finite_specific_message():
    with pytest.raises(ValidationError, match="must be finite"):
        require_positive(float("nan"), "scale")


def test_positive_rejects_inf_with_finite_specific_message():
    with pytest.raises(ValidationError, match="must be finite"):
        require_positive(float("inf"), "scale")


def test_positive_rejects_zero_with_greater_than_message():
    with pytest.raises(ValidationError, match="greater than 0"):
        require_positive(0, "scale")


@pytest.mark.parametrize("value", ["#ffffff\n", "#ffffff\r", "#ffffff\n\n"])
def test_hex_color_rejects_trailing_newline(value):
    """Runtime behavior and validation."""
    with pytest.raises(ValidationError, match="color"):
        require_hex_color(value, "color")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_require_finite_rejects_nan_and_infinity(bad):
    """These reach the map as a position or an energy and cannot be recovered.

    GDScript has no try/catch, so nothing raises on the mod side: the value
    lands in a node's position, the element cannot be seen or selected, and
    fit_elements then computes a nan bounding box and moves the camera
    somewhere with no way back.
    """
    with pytest.raises(ValidationError):
        require_finite(bad, "x")


def test_require_finite_allows_none():
    """An omitted optional coordinate means 'use the default', not 'invalid'."""
    require_finite(None, "x")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"asset": "a", "x": float("nan")},
        {"asset": "a", "y": float("inf")},
        {"asset": "a", "rotation": float("nan")},
    ],
)
def test_place_object_rejects_non_finite_coordinates(kwargs):
    with pytest.raises(ValidationError):
        server.place_object(**kwargs)


def test_add_light_rejects_non_finite_energy():
    with pytest.raises(ValidationError):
        server.add_light(energy=float("inf"))


@pytest.mark.parametrize("bad_layer", [250, -600, 1000, 1])
def test_place_object_rejects_a_layer_that_is_not_a_real_layer(bad_layer):
    """Layers are VALUES on a 100 step from -500 to 900, not arbitrary ints."""
    with pytest.raises(ValidationError):
        server.place_object(asset="a", layer=bad_layer)


def test_scatter_objects_rejects_an_invalid_layer():
    with pytest.raises(ValidationError):
        server.scatter_objects(assets=["a"], rect=[0, 0, 10, 10], layer=42)


@pytest.mark.parametrize("category", ["Smart Tiles", "Smart Tiles Double"])
def test_place_pattern_refuses_smart_tilesets(category):
    """A smart tileset drawn as a pattern renders solid black and reports success."""
    with pytest.raises(ValidationError, match="SOLID BLACK"):
        server.place_pattern(asset="a.png", category=category, rect=[0, 0, 10, 10])


def test_build_room_refuses_a_smart_tileset_floor():
    with pytest.raises(ValidationError, match="floor_category"):
        server.build_room(
            rect=[0, 0, 10, 10],
            floor="pattern",
            floor_asset="a.png",
            floor_category="Smart Tiles",
        )


def test_simple_tiles_are_still_accepted():
    """The guard must not catch the banks that actually work."""
    reject_smart_tiles("Simple Tiles")
    reject_smart_tiles("Materials")
    reject_smart_tiles("Patterns")


def test_a_point_that_is_not_a_pair_is_rejected():
    """`list[list[float]]` does not constrain the INNER length, so [[], [], []]
    type-checks, reaches the mod, and is indexed at p[0] without looking."""
    from battlemap_mcp.validation import require_points

    with pytest.raises(ValidationError) as excinfo:
        require_points([[], [], []])
    assert "exactly [x, y]" in str(excinfo.value)

    with pytest.raises(ValidationError):
        require_points([[1, 2, 3], [4, 5, 6]])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_coordinate_is_rejected(bad):
    from battlemap_mcp.validation import require_points

    with pytest.raises(ValidationError) as excinfo:
        require_points([[0, 0], [bad, 10]])
    assert "finite" in str(excinfo.value)


def test_points_are_capped_so_a_polyline_cannot_be_unbounded():
    from battlemap_mcp.validation import MAX_POINTS, require_points

    with pytest.raises(ValidationError) as excinfo:
        require_points([[0, 0]] * (MAX_POINTS + 1))
    assert "capped" in str(excinfo.value)


def test_a_well_formed_polyline_passes():
    from battlemap_mcp.validation import require_points

    require_points([[0, 0], [256.5, -12]])


@pytest.mark.parametrize(
    "bad", [[0, 0, 10], [0, 0, 10, 10, 10], [0, 0, 0, 10], [0, 0, 10, -1], [0, 0, float("inf"), 10]]
)
def test_a_malformed_rect_is_rejected(bad):
    from battlemap_mcp.validation import require_rect

    with pytest.raises(ValidationError):
        require_rect(bad)


def test_draw_wall_rejects_malformed_points_before_the_socket(monkeypatch):
    """The validators only help if the tools actually call them."""
    from battlemap_mcp import server

    def explode(command, **params):  # pragma: no cover - must never run
        raise AssertionError(f"{command} reached the bridge with malformed points")

    monkeypatch.setattr(server.bridge, "request", explode)
    with pytest.raises(ValidationError):
        server.draw_wall(points=[[], []])


def test_validate_floorplan_refuses_an_unbounded_cell_count(monkeypatch):
    """cell_woxels=1 on an ordinary map is tens of millions of flood-fill
    entries â€” not a slow answer but an unbounded one."""
    from battlemap_mcp import server

    monkeypatch.setattr(
        server.bridge,
        "request",
        lambda command, **p: {"map_open": True, "map_size_woxels": [8960, 5120]},
    )
    with pytest.raises(ValidationError) as excinfo:
        server.validate_floorplan(cell_woxels=1)
    assert "cells" in str(excinfo.value)


@pytest.mark.parametrize("z", [-501, -150, 1000])
def test_pattern_rejects_layers_that_cannot_persist(z, monkeypatch):
    monkeypatch.setattr(
        server.bridge, "request", lambda *a, **kw: pytest.fail("invalid layer dispatched")
    )
    with pytest.raises(ValidationError, match="z"):
        server.place_pattern(asset="floor.png", category="Simple Tiles", rect=[0, 0, 256, 256], z=z)
