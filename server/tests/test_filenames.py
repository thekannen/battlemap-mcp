"""Bare filenames must stay inside their directory on every supported OS."""

from pathlib import PureWindowsPath

import pytest

from battlemap_mcp.errors import ValidationError
from battlemap_mcp.validation import require_bare_filename, require_within


def test_the_windows_escape_is_real():
    """Why ':' matters: this is the join the save path performs on Windows."""
    joined = PureWindowsPath("D:/SharedMaps") / "C:escaped.dungeondraft_map"
    assert not str(joined).startswith("D:"), joined


@pytest.mark.parametrize(
    "name",
    [
        "C:escaped.dungeondraft_map",  # drive-relative on Windows
        "map.dungeondraft_map:hidden",  # NTFS alternate data stream
        "../up",
        "sub/map",
        "sub\\map",
        ".hidden",
        "map.",  # Windows strips it: aliases "map"
        "map .",  # trailing dot survives the strip
        "CON",
        "con.dungeondraft_map",
        "LPT1.txt",
        "a|b",
        "a?b",
        "a*b",
        'a"b',
        "a<b",
        "tab\there",
        "nul\x00byte",
        "",
        "   ",
        "x" * 256,
    ],
)
def test_names_that_are_not_one_file_are_refused(name):
    with pytest.raises(ValidationError):
        require_bare_filename(name)


@pytest.mark.parametrize("name", ["inn", "The Rusty Anchor.dungeondraft_map", "café-2", "CONsole"])
def test_ordinary_names_pass(name):
    assert require_bare_filename(f"  {name} ") == name


def test_a_symlinked_entry_pointing_outside_is_refused(tmp_path, create_file_symlink_or_skip):
    save = tmp_path / "save"
    save.mkdir()
    outside = tmp_path / "elsewhere.dungeondraft_map"
    create_file_symlink_or_skip(save / "trap.dungeondraft_map", outside)  # dangling is enough
    with pytest.raises(ValidationError, match="outside the save directory"):
        require_within(save, save / "trap.dungeondraft_map")


def test_a_plain_child_is_accepted(tmp_path):
    assert require_within(tmp_path, tmp_path / "inn.dungeondraft_map") == (
        tmp_path.resolve() / "inn.dungeondraft_map"
    )


def test_prepare_map_with_packs_refuses_a_drive_relative_name_before_the_socket(monkeypatch):
    from battlemap_mcp import server

    def request(command, **params):
        raise AssertionError(f"reached the bridge with {command}")

    monkeypatch.setattr(server.bridge, "request", request)
    with pytest.raises(ValidationError, match=r"\[':'\]"):
        server.prepare_map_with_packs("C:escaped", packs=["x"])


def test_save_map_refuses_windows_illegal_names_before_the_socket(monkeypatch):
    from battlemap_mcp import server

    def request(command, **params):
        raise AssertionError(f"reached the bridge with {command}")

    monkeypatch.setattr(server.bridge, "request", request)
    with pytest.raises(ValidationError, match=r"\['\?'\]"):
        server.save_map("review?map")
