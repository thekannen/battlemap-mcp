"""Runtime behavior and validation."""

import json
import os
import struct
from pathlib import Path

import pytest

from battlemap_mcp import installer, pack_contents, server
from battlemap_mcp.bridge_client import BridgeUnavailableError
from battlemap_mcp.errors import ValidationError


def write_pack(path, pack_id, files, info=None, *, tags=None, trailing_comma=False):
    """A Godot 3 PCK laid out as Dungeondraft packs are."""
    prefix = f"res://packs/{pack_id}/"
    meta = {"name": f"Pack {pack_id}", "id": pack_id, "version": "1.0", "author": "Tester"}
    meta.update(info or {})
    contents = {prefix + "pack.json": json.dumps(meta).encode()}
    if tags is not None:
        text = json.dumps({"tags": tags, "sets": {}})
        if trailing_comma:
            text = text[:-1] + ",}"  # {...,} the way pack tools write it
        contents[prefix + "data/default.dungeondraft_tags"] = text.encode()
    for relative, data in files.items():
        contents[prefix + relative] = data
    index = b""
    body = b""
    names = [name.encode() for name in contents]
    header_size = 20 + 64 + 4 + sum(4 + len(n) + 16 + 16 for n in names)
    for name, data in zip(names, contents.values(), strict=True):
        index += struct.pack("<I", len(name)) + name
        index += struct.pack("<QQ", header_size + len(body), len(data)) + b"\0" * 16
        body += data
    header = struct.pack("<5I", pack_contents.PCK_MAGIC, 1, 3, 4, 2) + b"\0" * 64
    path.write_bytes(header + struct.pack("<I", len(contents)) + index + body)
    return path


ART = b"\x89PNG not really"


@pytest.fixture(autouse=True)
def fresh_cache():
    pack_contents._cache.clear()
    yield
    pack_contents._cache.clear()


def furniture(tmp_path, **kwargs):
    return write_pack(
        tmp_path / "Furniture.dungeondraft_pack",
        "FURN0001",
        {
            "textures/objects/Bed - Oak.webp": ART,
            "textures/objects/Table - Round.webp": ART,
            "textures/objects/Garden/Arbour_A.webp": ART,
            "textures/walls/Stone.png": ART,
            "textures/walls/Stone_end.png": ART,
            "textures/patterns/normal/Planks.png": ART,
            "textures/tilesets/simple/Cobble.png": ART,
            "thumbnails/0123abcd.png": ART,
            "preview.png": ART,
        },
        tags={"Outdoor Structures": ["textures/objects/Garden/Arbour_A.webp"]},
        **kwargs,
    )


def test_a_pack_lists_its_assets_by_category(tmp_path):
    pack = pack_contents.read_pack(furniture(tmp_path))
    assert pack.id == "FURN0001" and not pack.restricted
    objects = [path for path, _tags in pack.assets["Objects"]]
    assert objects == [
        "res://packs/FURN0001/textures/objects/Bed - Oak.webp",
        "res://packs/FURN0001/textures/objects/Table - Round.webp",
        "res://packs/FURN0001/textures/objects/Garden/Arbour_A.webp",
    ]
    # A wall's end cap travels with its wall; thumbnails and the cover are
    # not assets at all.
    assert [p for p, _ in pack.assets["Walls"]] == ["res://packs/FURN0001/textures/walls/Stone.png"]
    assert [p for p, _ in pack.assets["Patterns"]][0].endswith("patterns/normal/Planks.png")
    assert [p for p, _ in pack.assets["Simple Tiles"]][0].endswith("tilesets/simple/Cobble.png")
    assert dict(pack.assets["Objects"])[objects[2]] == ("Outdoor Structures",)


def test_tags_with_trailing_commas_still_load(tmp_path):
    pack = pack_contents.read_pack(furniture(tmp_path, trailing_comma=True))
    assert any(tags for _path, tags in pack.assets["Objects"])


def test_no_art_is_ever_read(tmp_path, monkeypatch):
    """Only pack.json and the tags file are read past the index."""
    read = []
    original = pack_contents._read_text

    def recording(handle, offset, size):
        text = original(handle, offset, size)
        read.append(text[:1])
        return text

    monkeypatch.setattr(pack_contents, "_read_text", recording)
    pack_contents.read_pack(furniture(tmp_path))
    assert read == ["{", "{"]


def test_a_pack_whose_author_opted_out_is_not_indexed(tmp_path, monkeypatch):
    file = furniture(tmp_path, info={pack_contents.OPT_OUT: False})
    read = []
    original = pack_contents._read_text
    monkeypatch.setattr(
        pack_contents,
        "_read_text",
        lambda *args: read.append(1) or original(*args),
    )
    pack = pack_contents.read_pack(file)
    assert pack.restricted and pack.assets == {}
    assert len(read) == 1  # pack.json, to learn the author's choice; not the tags


def test_opting_in_or_saying_nothing_is_searched(tmp_path):
    assert not pack_contents.read_pack(
        furniture(tmp_path, info={pack_contents.OPT_OUT: True})
    ).restricted


def test_a_file_that_is_not_a_pack_is_reported_not_raised(tmp_path):
    (tmp_path / "broken.dungeondraft_pack").write_bytes(b"not a pack at all, honestly")
    furniture(tmp_path)
    found = pack_contents.discover(tmp_path)
    assert list(found["packs"]) == ["FURN0001"]
    assert found["unreadable"][0]["file"] == "broken.dungeondraft_pack"


def test_a_changed_pack_is_read_again(tmp_path):
    file = furniture(tmp_path)
    first = pack_contents.load_pack(file)
    assert pack_contents.load_pack(file) is first
    write_pack(file, "FURN0001", {"textures/objects/Chair.webp": ART})
    os.utime(file, ns=(1, 1))
    assert [p for p, _ in pack_contents.load_pack(file).assets["Objects"]] == [
        "res://packs/FURN0001/textures/objects/Chair.webp"
    ]


def two_versions(tmp_path):
    old = write_pack(tmp_path / "A_v1.dungeondraft_pack", "SAME", {}, {"version": "3.9"})
    new = write_pack(tmp_path / "A_v2.dungeondraft_pack", "SAME", {}, {"version": "3.10"})
    return old, new


def test_the_newest_of_two_files_with_one_id_is_searched(tmp_path):
    two_versions(tmp_path)
    found = pack_contents.discover(tmp_path)
    assert found["packs"]["SAME"].info["version"] == "3.10"  # numerically, not as text
    assert found["duplicates"]["SAME"] == {
        "searched": "A_v2.dungeondraft_pack",
        "also_found": ["A_v1.dungeondraft_pack"],
    }


def test_the_version_dungeondraft_mounted_wins(tmp_path):
    two_versions(tmp_path)
    found = pack_contents.discover(tmp_path, {"SAME": "3.9"})
    assert found["packs"]["SAME"].info["version"] == "3.9"


def test_search_matches_paths_and_tags_and_counts_every_match(tmp_path):
    furniture(tmp_path)
    found = pack_contents.discover(tmp_path)
    results = pack_contents.search(
        found["packs"], ["outdoor", "round table", "bed"], "Objects", limit=1
    )
    # "outdoor" is only in the arbour's TAG, never its path.
    assert results["outdoor"]["best"] == {
        "FURN0001": ["res://packs/FURN0001/textures/objects/Garden/Arbour_A.webp"]
    }
    assert results["round table"]["matched_by_pack"] == {"FURN0001": 1}
    assert results["bed"]["matched_by_pack"] == {"FURN0001": 1}
    substring = pack_contents.search(found["packs"], ["d - oak"], "Objects", mode="substring")
    assert substring["d - oak"]["matched_by_pack"] == {"FURN0001": 1}


def test_config_reads_the_asset_folder(tmp_path):
    config = tmp_path / "config.ini"
    config.write_text(
        '[Mods]\n\nmods_directory="C:\\\\Games\\\\DD Mods"\n\n'
        "[Assets]\n\n"
        'active_asset_packs=[ "8XXbciV2", "FA30DDXY" ]\n'
        'custom_assets_directory="/opt/fixture/Dungeondraft Assets/Assets"\n',
        encoding="utf-8",
    )
    assert installer.config_path_value(config, "Assets", "custom_assets_directory") == Path(
        "/opt/fixture/Dungeondraft Assets/Assets"
    )
    assert installer.config_path_value(config, "Assets", "missing") is None
    assert installer.configured_mods_dir(config) is not None


@pytest.fixture
def library(tmp_path, monkeypatch):
    furniture(tmp_path)
    write_pack(
        tmp_path / "Closed.dungeondraft_pack",
        "CLOSED01",
        {"textures/objects/Bed - Secret.webp": ART},
        {"name": "Closed Pack", pack_contents.OPT_OUT: False},
    )
    monkeypatch.setattr(pack_contents, "assets_directory", lambda: tmp_path)
    return tmp_path


def test_the_tool_says_which_packs_the_map_includes(library, monkeypatch):
    def request(cmd, **params):
        assert cmd == "list_asset_packs"
        return {
            "installed": [{"id": "FURN0001", "version": "1.0"}],
            "included_in_this_map": [],
        }

    monkeypatch.setattr(server.bridge, "request", request)
    result = server.search_pack_contents(searches=["bed", "bed"])
    assert list(result["results"]) == ["bed"]
    assert result["packs_found"] == {
        "FURN0001": {
            "name": "Pack FURN0001",
            "author": "Tester",
            "version": "1.0",
            "included_in_this_map": False,
            "loaded_in_dungeondraft": True,
        }
    }
    # The opted-out pack has a bed too; it is named, never searched.
    assert result["not_searched"] == [
        {
            "id": "CLOSED01",
            "name": "Closed Pack",
            "reason": "its author opted out of third-party tools reading the pack",
        }
    ]
    assert "CLOSED01" not in result["results"]["bed"]["matched_by_pack"]


def test_the_tool_works_with_dungeondraft_closed(library, monkeypatch):
    def unavailable(cmd, **params):
        raise BridgeUnavailableError("not running")

    monkeypatch.setattr(server.bridge, "request", unavailable)
    result = server.search_pack_contents(searches=["table"])
    assert result["packs_found"]["FURN0001"]["included_in_this_map"] is None
    assert result["packs_found"]["FURN0001"]["loaded_in_dungeondraft"] is None
    assert "not reachable" in result["note"]


def test_the_tool_refuses_unknown_packs_and_categories(library, monkeypatch):
    monkeypatch.setattr(server.bridge, "request", lambda *a, **k: {"installed": []})
    with pytest.raises(ValidationError, match="NOPE"):
        server.search_pack_contents(searches=["bed"], packs=["NOPE"])
    with pytest.raises(ValidationError):
        server.search_pack_contents(searches=["bed"], category="Furniture")
    with pytest.raises(ValidationError):
        server.search_pack_contents(searches=["bed"], match_mode="fuzzy")


def test_a_missing_asset_folder_is_explained(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "dungeondraft_data_dir", lambda: tmp_path)
    monkeypatch.delenv(pack_contents.ASSETS_DIR_ENV, raising=False)
    with pytest.raises(ValidationError, match="no asset pack folder"):
        pack_contents.assets_directory()
    monkeypatch.setenv(pack_contents.ASSETS_DIR_ENV, str(tmp_path))
    assert pack_contents.assets_directory() == tmp_path
