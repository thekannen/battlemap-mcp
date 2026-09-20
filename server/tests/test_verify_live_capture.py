"""record() must turn check() labels into safe, flat fixture filenames.

Importing tools.verify_live must not require a live Dungeondraft: it builds a
BridgeClient at module scope, but BridgeClient() is lazy (see
test_auth.py::test_construction_does_not_require_token_file), so import alone
never touches the filesystem or a socket. These tests run with Dungeondraft
closed.
"""

import json
from pathlib import Path

import pytest

from tools import verify_live


@pytest.fixture(autouse=True)
def _reset_recorded_labels(monkeypatch):
    """Isolate collision tracking between tests.

    record() tracks which labels it has written *for the process's lifetime*
    (a capture run is one process), so without this the dict would carry
    state from one test into the next and produce order-dependent failures.
    """
    monkeypatch.setattr(verify_live, "_recorded_labels", {}, raising=False)


def test_normal_label_is_unchanged():
    assert verify_live.sanitize_fixture_name("get_status") == "get_status"


def test_slash_label_is_flattened():
    assert verify_live.sanitize_fixture_name("undo/redo") == "undo_redo"


def test_other_hostile_characters_are_replaced():
    assert verify_live.sanitize_fixture_name("list levels?!") == "list_levels"


def test_label_that_sanitizes_to_empty_is_rejected():
    with pytest.raises(ValueError):
        verify_live.sanitize_fixture_name("///")


def test_leading_dot_is_stripped():
    assert verify_live.sanitize_fixture_name(".secret") == "secret"


def test_all_dots_label_is_rejected():
    with pytest.raises(ValueError):
        verify_live.sanitize_fixture_name("...")


def test_scrub_fixture_replaces_identifying_values_with_stable_placeholders():
    response = {
        "map_file": r"C:\\FixtureUsers\\fixture-user\\Maps\\private-map.dungeondraft_map",
        "saving": {
            "path": r"C:\\FixtureUsers\\fixture-user\\Maps\\private-map.dungeondraft_map",
            "last_saved": r"C:\\FixtureUsers\\fixture-user\\Maps\\private-map.dungeondraft_map",
        },
        "username": "fixture-user",
        "asset_packs": {
            "installed": [{"name": "Fixture User's Pack", "author": "fixture-user"}],
        },
        "elements": [{"kind": "text", "text": "Meet Fixture User at home"}],
        "asset": "res://textures/objects/atlas_globe_01.png",
    }

    assert verify_live.scrub_fixture(response, command="get_status") == {
        "map_file": "<MAP_FILE>",
        "saving": {"path": "<PATH>", "last_saved": "<PATH>"},
        "username": "<USERNAME>",
        "asset_packs": {
            "installed": [{"name": "<ASSET_PACK_NAME>", "author": "<USERNAME>"}],
        },
        "elements": [{"kind": "text", "text": "<MAP_TEXT>"}],
        "asset": "res://textures/objects/atlas_globe_01.png",
    }


def test_scrub_fixture_replaces_asset_pack_names():
    assert verify_live.scrub_fixture(
        {"installed": [{"name": "Fixture User's Pack", "author": "fixture-user"}]},
        command="list_asset_packs",
    ) == {"installed": [{"name": "<ASSET_PACK_NAME>", "author": "<USERNAME>"}]}


def test_scrub_fixture_replaces_home_paths_even_when_the_field_name_changes():
    assert verify_live.scrub_fixture(
        {"future_path_field": str(Path.home() / "Maps" / "private-map.dungeondraft_map")},
        command="future_command",
    ) == {"future_path_field": "<PATH>"}


def test_scrub_fixture_replaces_external_save_directory_values():
    assert verify_live.scrub_fixture(
        {"configured": r"D:\\Private Maps", "effective": r"D:\\Private Maps"},
        command="set_save_directory",
    ) == {"configured": "<SAVE_DIRECTORY>", "effective": "<SAVE_DIRECTORY>"}


def test_scrub_fixture_redacts_external_output_paths_without_redacting_node_paths():
    assert verify_live.scrub_fixture(
        {"path": r"D:\\Dungeondraft Output\\asset_preview.png"}, command="preview_assets"
    ) == {"path": "<PATH>"}


def test_record_writes_scrubbed_response_data(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_live, "CAPTURE", True)
    monkeypatch.setattr(verify_live, "FIXTURES", tmp_path)

    verify_live.record(
        "get_status",
        {
            "map_file": r"C:\\FixtureUsers\\fixture-user\\Maps\\private-map.dungeondraft_map",
            "saving": {
                "path": r"C:\\FixtureUsers\\fixture-user\\Maps\\private-map.dungeondraft_map"
            },
            "username": "fixture-user",
        },
    )

    assert json.loads((tmp_path / "get_status.json").read_text()) == {
        "map_file": "<MAP_FILE>",
        "saving": {"path": "<PATH>"},
        "username": "<USERNAME>",
    }


def test_record_writes_a_single_flat_file_for_a_slash_label(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_live, "CAPTURE", True)
    monkeypatch.setattr(verify_live, "FIXTURES", tmp_path)

    verify_live.record("undo/redo", {"ok": True})

    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert written == ["undo_redo.json"]
    assert json.loads((tmp_path / "undo_redo.json").read_text()) == {"ok": True}


def test_record_leaves_a_normal_label_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_live, "CAPTURE", True)
    monkeypatch.setattr(verify_live, "FIXTURES", tmp_path)

    verify_live.record("get_status", {"map_center": [6400, 6400]})

    assert (tmp_path / "get_status.json").exists()


def test_colliding_labels_raise_instead_of_overwriting(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_live, "CAPTURE", True)
    monkeypatch.setattr(verify_live, "FIXTURES", tmp_path)

    verify_live.record("foo bar", {"from": "first"})

    with pytest.raises(ValueError) as exc_info:
        verify_live.record("foo/bar", {"from": "second"})

    message = str(exc_info.value)
    assert "foo bar" in message
    assert "foo/bar" in message
    assert "foo_bar.json" in message
    # the fixture written under the first label must survive untouched
    assert json.loads((tmp_path / "foo_bar.json").read_text()) == {"from": "first"}


def test_same_label_recorded_twice_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_live, "CAPTURE", True)
    monkeypatch.setattr(verify_live, "FIXTURES", tmp_path)

    verify_live.record("get_status", {"attempt": 1})
    verify_live.record("get_status", {"attempt": 2})

    assert json.loads((tmp_path / "get_status.json").read_text()) == {"attempt": 2}


def test_leading_dot_label_does_not_produce_hidden_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(verify_live, "CAPTURE", True)
    monkeypatch.setattr(verify_live, "FIXTURES", tmp_path)

    verify_live.record(".secret", {"ok": True})

    written = [p.name for p in tmp_path.iterdir()]
    assert written == ["secret.json"]
    assert not any(name.startswith(".") for name in written)


def test_capture_scrubs_paths_in_lists_and_diagnostics(tmp_path, monkeypatch):
    home = tmp_path / "synthetic-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(verify_live, "CAPTURE", True)
    monkeypatch.setattr(verify_live, "FIXTURES", tmp_path)
    verify_live.record(
        "get_status",
        {
            "recent": [str(home / "private.map"), r"D:\private\map.dungeondraft_map"],
            "note": f"Failed reading {home / 'private.map'} during save",
            "asset_packs": {"included": [{"name": "Synthetic private pack"}]},
        },
    )
    assert json.loads((tmp_path / "get_status.json").read_text()) == {
        "recent": ["<PATH>", "<PATH>"],
        "note": "<PATH>",
        "asset_packs": {"included": [{"name": "<ASSET_PACK_NAME>"}]},
    }
