"""Runtime behavior and validation."""

from __future__ import annotations

import pytest

from battlemap_mcp import server

FA_WINDOWS = "res://packs/FA35OB01/textures/portals/Windows/Window_Sills"


@pytest.mark.parametrize(
    "asset",
    [
        f"{FA_WINDOWS}/Window_Frames/Window_Frame_Large_Wood_Dark_A_2x1.webp",
        "res://packs/FA35OB01/textures/portals/Doors/Door_Frame_Double_Metal_Gray_A_3x1.webp",
    ],
)
def test_a_frame_only_portal_is_flagged(asset):
    assert "frame-only" in server._frame_only_portal_note(asset)


@pytest.mark.parametrize(
    "asset",
    [
        f"{FA_WINDOWS}/Window_Sill_Large_Wood_Dark_A1_2x1.webp",
        "res://textures/portals/door_00.png",
    ],
)
def test_a_complete_portal_is_not(asset):
    assert server._frame_only_portal_note(asset) == ""
