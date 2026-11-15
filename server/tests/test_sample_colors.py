"""sample_colors reads tints by number from a rebuild's source and its export."""

from __future__ import annotations

import base64
import io
import json
import os
import time

import pytest
from PIL import Image

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError

LEFT, RIGHT = (200, 40, 40), (40, 40, 200)


def _halves(width: int, height: int) -> Image.Image:
    """Left half one colour, right half another."""
    image = Image.new("RGB", (width, height), LEFT)
    image.paste(RIGHT, (width // 2, 0, width, height))
    return image


def _dd2vtt(tmp_path, ppg=64, tiles=(10, 8)):
    buffer = io.BytesIO()
    _halves(tiles[0] * ppg, tiles[1] * ppg).save(buffer, "PNG")
    data = {
        "format": 0.3,
        "resolution": {
            "map_origin": {"x": 0, "y": 0},
            "map_size": {"x": tiles[0], "y": tiles[1]},
            "pixels_per_grid": ppg,
        },
        "line_of_sight": [],
        "portals": [],
        "lights": [],
        "image": base64.b64encode(buffer.getvalue()).decode(),
    }
    path = tmp_path / "shop.dd2vtt"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def captures(tmp_path, monkeypatch):
    root = tmp_path / "captures"
    root.mkdir()
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(root))
    monkeypatch.setattr(
        server.bridge,
        "request",
        lambda cmd, **_: {"map_open": True, "map_size_woxels": [2560, 2048]},
    )
    return root


def _export_png(root, image, name="export-" + "a" * 32 + ".png"):
    image.save(root / name)
    return name


def test_the_source_image_maps_from_woxels_at_its_pixels_per_grid(tmp_path, captures):
    path = _dd2vtt(tmp_path, ppg=64)
    # The map is 10 tiles = 2560 woxels wide; the colour changes at 1280.
    result = server.sample_colors([[600, 1000], [2000, 1000]], dd2vtt=str(path), export="")
    left, right = result["samples"]
    assert (left["source"], right["source"]) == ("#c82828", "#2828c8")


def test_an_export_of_any_ppi_maps_to_the_same_points(tmp_path, captures):
    _export_png(captures, _halves(500, 400))  # ~50 ppi, not the source's 64
    result = server.sample_colors([[600, 1000], [2000, 1000]])
    left, right = result["samples"]
    assert (left["export"], right["export"]) == ("#c82828", "#2828c8")
    assert result["export_file"].startswith("export-")


def test_both_sources_give_a_signed_difference(tmp_path, captures):
    path = _dd2vtt(tmp_path)
    # The build's left half is a little lighter and less red-saturated.
    built = _halves(500, 400)
    built.paste((210, 60, 50), (0, 0, 250, 400))
    _export_png(captures, built)
    (row,) = server.sample_colors([[600, 1000]], dd2vtt=str(path))["samples"]
    assert row["diff_rgb"] == [10, 20, 10] and row["max_diff"] == 20


def test_a_point_off_the_image_says_so(tmp_path, captures):
    path = _dd2vtt(tmp_path)
    (row,) = server.sample_colors([[9000, 100]], dd2vtt=str(path), export="")["samples"]
    assert row["source"] == "outside the image"


def test_an_export_of_another_map_size_is_refused(tmp_path, captures):
    _export_png(captures, Image.new("RGB", (400, 400)))
    with pytest.raises(ValidationError, match="export_map again"):
        server.sample_colors([[100, 100]])


def test_no_export_yet_says_what_to_do(tmp_path, captures):
    with pytest.raises(ValidationError, match="export_map first"):
        server.sample_colors([[100, 100]])


@pytest.mark.parametrize(
    "points, radius",
    [([], 32), ([[1, 2, 3]], 32), ([[0, 0]] * 65, 32), ([[0, 0]], -1), ([[0, 0]], 600)],
)
def test_bad_arguments_are_refused(captures, points, radius):
    with pytest.raises(ValidationError):
        server.sample_colors(points, radius=radius)


def test_a_mismatched_export_ppi_says_which_to_use(tmp_path, captures):
    """Two renders of one map read up to 6 levels apart at different ppi, and
    0 at the same ppi with the grid off (measured live, 2026-11-14)."""
    path = _dd2vtt(tmp_path, ppg=64)
    _export_png(captures, _halves(500, 400))  # 50 ppi
    result = server.sample_colors([[600, 1000]], dd2vtt=str(path))
    assert result["source_ppg"] == 64 and result["export_ppi"] == 50
    assert "export_map(ppi=64, grid=False)" in result["note"]
    _export_png(captures, _halves(640, 512), name="export-" + "b" * 32 + ".png")
    os.utime(captures / ("export-" + "b" * 32 + ".png"), (time.time() + 5, time.time() + 5))
    assert "note" not in server.sample_colors([[600, 1000]], dd2vtt=str(path))
