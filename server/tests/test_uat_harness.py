"""Regression tests for the cross-platform live-UAT harness."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _uat_harness():
    """Load the standalone tools module after making its directory importable."""
    return importlib.import_module("uat_harness")


def test_uat_log_path_honors_a_cross_platform_environment_override(monkeypatch, tmp_path):
    """Windows launch logs must be usable without pretending they are /tmp/dd.log."""
    expected = tmp_path / "dungeondraft.stdout.log"
    monkeypatch.setenv("BATTLEMAP_MCP_LOG_FILE", str(expected))
    try:
        module = importlib.reload(_uat_harness())
        assert module.LOG == expected
    finally:
        monkeypatch.delenv("BATTLEMAP_MCP_LOG_FILE", raising=False)
        importlib.reload(_uat_harness())


def test_vanilla_assets_exclude_custom_matches_that_crowd_a_result_page():
    """A full scan must retain the vanilla match after custom packs fill page one."""
    custom = [f"res://packs/custom/textures/objects/carpet_{n}.png" for n in range(10)]
    vanilla = "res://textures/objects/furniture/carpet_01.png"

    assert _uat_harness().vanilla_assets([*custom, vanilla]) == [vanilla]


def test_vanilla_colourable_assets_ignore_custom_pack_matches():
    """The positive UAT fixture must be a colourable asset shipped by Dungeondraft."""
    custom = [f"res://packs/custom/textures/objects/carpet_{n}.png" for n in range(10)]
    vanilla = "res://textures/objects/furniture/carpet_01.png"

    assert _uat_harness().vanilla_colourable_assets([*custom, vanilla], [vanilla]) == [vanilla]


def test_vanilla_asset_assertions_stay_within_the_bridge_colour_scan_cap():
    """The filtered request must retain bridge-provided colourability metadata."""
    assert _uat_harness().COLORABLE_ASSET_SCAN_LIMIT == 200


class _Bridge:
    def __init__(
        self,
        current_map: Path,
        *,
        opens_maps: bool = True,
        status_available: bool = True,
        status_map_file: object | None = None,
    ):
        self.current_map = current_map
        self.opens_maps = opens_maps
        self.status_available = status_available
        self.status_map_file = status_map_file
        self.opened: list[Path] = []

    def request(self, command: str, **params):
        if command == "get_status":
            if not self.status_available:
                raise RuntimeError("bridge unavailable")
            map_file = self.status_map_file
            if map_file is None:
                map_file = str(self.current_map)
            return {"map_file": map_file}
        if command == "open_map":
            opened = Path(params["path"])
            self.opened.append(opened)
            if self.opens_maps:
                self.current_map = opened
            return {"opening": str(opened)}
        raise AssertionError(f"unexpected command: {command}")


def _harness_for_cleanup(
    original_map: Path | None,
    current_map: Path,
    made_files: list[Path],
    *,
    opens_maps: bool = True,
    status_available: bool = True,
    status_map_file: object | None = None,
):
    harness = object.__new__(_uat_harness().Uat)
    harness.c = _Bridge(
        current_map,
        opens_maps=opens_maps,
        status_available=status_available,
        status_map_file=status_map_file,
    )
    harness.original_map_file = original_map
    harness.made_files = [str(path) for path in made_files]
    harness.cleanup_restore_timeout = 0.0
    return harness


def test_cleanup_restores_original_map_before_removing_the_active_uat_map(tmp_path):
    """A completed UAT must not leave Dungeondraft pointing at a deleted file."""
    original = tmp_path / "original.dungeondraft_map"
    scratch = tmp_path / "uat-scratch.dungeondraft_map"
    original.write_text("original")
    scratch.write_text("scratch")
    harness = _harness_for_cleanup(original, scratch, [scratch])

    harness.cleanup_files()

    assert harness.c.opened == [original]
    assert not scratch.exists()


def test_cleanup_keeps_the_active_uat_map_when_no_original_file_can_be_restored(tmp_path):
    """An unsaved blank map has no safe restore target, so its active scratch map stays."""
    scratch = tmp_path / "uat-scratch.dungeondraft_map"
    other = tmp_path / "uat-other.dungeondraft_map"
    scratch.write_text("scratch")
    other.write_text("other")
    harness = _harness_for_cleanup(None, scratch, [scratch, other])

    result = harness.cleanup_files()

    assert scratch.exists()
    assert not other.exists()
    assert "preserved" in result


def test_cleanup_keeps_active_scratch_when_restoring_the_original_map_does_not_finish(tmp_path):
    """Cleanup must not delete a map until Dungeondraft confirms it changed maps."""
    original = tmp_path / "original.dungeondraft_map"
    scratch = tmp_path / "uat-scratch.dungeondraft_map"
    original.write_text("original")
    scratch.write_text("scratch")
    harness = _harness_for_cleanup(original, scratch, [scratch], opens_maps=False)

    result = harness.cleanup_files()

    assert harness.c.opened == [original]
    assert scratch.exists()
    assert "preserved" in result


def test_cleanup_preserves_every_scratch_map_when_bridge_status_is_unavailable(tmp_path):
    """A lost status channel must never make cleanup guess which map is active."""
    scratch = tmp_path / "uat-scratch.dungeondraft_map"
    other = tmp_path / "uat-other.dungeondraft_map"
    scratch.write_text("scratch")
    other.write_text("other")
    harness = _harness_for_cleanup(None, scratch, [scratch, other], status_available=False)

    result = harness.cleanup_files()

    assert scratch.exists()
    assert other.exists()
    assert "preserved 2" in result


def test_cleanup_preserves_every_scratch_map_when_active_map_cannot_be_identified(tmp_path):
    """A sentinel or stale map path is not proof that no scratch map is active."""
    scratch = tmp_path / "uat-scratch.dungeondraft_map"
    other = tmp_path / "uat-other.dungeondraft_map"
    scratch.write_text("scratch")
    other.write_text("other")
    harness = _harness_for_cleanup(
        None,
        scratch,
        [scratch, other],
        status_map_file="Null",
    )

    result = harness.cleanup_files()

    assert scratch.exists()
    assert other.exists()
    assert "preserved 2" in result


def test_pixel_difference_sees_colour_not_only_alpha():
    """Opaque red and green once compared identical: getbbox() read alpha alone."""
    from PIL import Image

    red = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    green = Image.new("RGBA", (8, 8), (0, 255, 0, 255))
    assert _uat_harness().pixel_difference(red, green) == (0, 0, 8, 8)


def test_pixel_difference_locates_one_changed_pixel_and_accepts_paths(tmp_path):
    from PIL import Image

    base = Image.new("RGB", (16, 16), (40, 40, 40))
    changed = base.copy()
    changed.putpixel((11, 5), (41, 40, 40))
    base.save(tmp_path / "a.png")
    changed.save(tmp_path / "b.png")
    harness = _uat_harness()
    assert harness.pixel_difference(tmp_path / "a.png", tmp_path / "b.png") == (11, 5, 12, 6)
    assert harness.pixel_difference(tmp_path / "a.png", tmp_path / "a.png") is None


def test_pixel_difference_sees_alpha_and_size_changes():
    from PIL import Image

    opaque = Image.new("RGBA", (8, 8), (9, 9, 9, 255))
    clear = Image.new("RGBA", (8, 8), (9, 9, 9, 0))
    harness = _uat_harness()
    assert harness.pixel_difference(opaque, clear) == (0, 0, 8, 8)
    assert harness.pixel_difference(opaque, Image.new("RGBA", (9, 8), (9, 9, 9, 255))) is not None
