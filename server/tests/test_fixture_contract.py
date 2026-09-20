"""Fixture contract: recorded live-bridge responses stay in sync with BridgeClient.

This test replays every recorded fixture through the real `fake_bridge`
socket, wrapping the recorded body in the `{\"ok\": true, \"result\": ...}`
envelope the wire protocol actually uses (see `BridgeClient.request()`), and
asserts `request()` returns exactly the recorded body back out. It is
data-driven over the fixtures directory — not a hand-listed set of names — so
a freshly captured fixture is covered automatically with no edit to this
file. If a fixture rots into invalid JSON, or the mod's response shape for
some command drifts from what `request()` parses, or `request()` stops
unwrapping the envelope, this fails loudly. That is the entire point of
paying the capture cost: a re-capture after a Dungeondraft update now makes
the suite fail instead of silently going stale.

This adds a layer; it does not replace the inline-dict tests in
`test_bridge_client.py`, which test client behaviour (framing, error mapping)
where the response body is irrelevant.
"""

import getpass
import json
import re
from pathlib import Path

import pytest

from battlemap_mcp.bridge_client import BridgeClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PATHS = sorted(FIXTURES_DIR.glob("*.json"))


def _client(fake_bridge, **kw):
    return BridgeClient(port=fake_bridge.port, timeout=5.0, token="t", **kw)


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda p: p.stem)
def test_recorded_fixture_round_trips_through_request(fixture_path, fake_bridge):
    # A fixture is exactly what `record()` wrote: the bare `result` payload
    # from a real bridge response, not a full envelope. Loading it with
    # json.loads is itself part of the contract — a fixture that rotted into
    # invalid JSON must fail this test, not be silently skipped.
    expected_result = json.loads(fixture_path.read_text())

    # The fixture filename carries no information about which literal `cmd`
    # produced it (sanitize_fixture_name() is a many-to-one mapping, e.g.
    # "undo/redo" -> "undo_redo"), so the stem is used directly as a synthetic
    # cmd here. That's fine: this test isn't verifying which bridge command
    # returns which shape, only that BridgeClient.request() faithfully
    # unwraps a real recorded envelope and hands back the exact result body.
    cmd = fixture_path.stem
    fake_bridge.responses[cmd] = {"ok": True, "result": expected_result}

    actual_result = _client(fake_bridge).request(cmd)

    assert actual_result == expected_result


def test_fixtures_directory_is_not_empty():
    # A silently-empty parametrize would make the test above vanish instead
    # of failing, defeating the entire point of this file. Pin the count down
    # so an accidental `rm -rf tests/fixtures/*` or a refactor that changes
    # the glob pattern is caught immediately instead of just quietly running
    # zero tests.
    assert len(FIXTURE_PATHS) >= 15


def test_tracked_fixtures_do_not_contain_this_machine_home_or_username():
    """Live capture output must not commit details about the recorder's machine."""
    home = str(Path.home()).replace("\\", "/").casefold()
    username = getpass.getuser().casefold()

    for fixture_path in FIXTURE_PATHS:
        contents = fixture_path.read_text(encoding="utf-8").replace("\\", "/").casefold()
        assert home not in contents, fixture_path
        assert username not in contents, fixture_path


def test_protocol_version_matches_the_doc():
    """PROTOCOL.md's stated version tracks the mod's PROTOCOL_VERSION.

    The version is how a client detects that it is talking to an older mod than
    it expects, so a bump that only lands in one of the two places makes the
    check lie.
    """
    root = Path(__file__).resolve().parents[2]
    mod = (root / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd").read_text()
    doc = (root / "docs" / "PROTOCOL.md").read_text()

    in_mod = re.search(r"const PROTOCOL_VERSION := (\d+)", mod)
    assert in_mod, "PROTOCOL_VERSION not found in the mod"
    in_doc = re.search(r"Current protocol version:\*\* (\d+)", doc)
    assert in_doc, "PROTOCOL.md does not state a current protocol version"

    assert in_mod.group(1) == in_doc.group(1), (
        f"mod is protocol v{in_mod.group(1)} but PROTOCOL.md documents v{in_doc.group(1)}"
    )


def test_bridge_save_filename_validation_matches_windows_safety_rules():
    root = Path(__file__).resolve().parents[2]
    mod = (root / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd").read_text()
    filename_validator = mod.split("func _map_filename", 1)[1].split("func _save_map", 1)[0]

    assert 'var invalid = ["<", ">", ":", "\\"", "/", "\\\\", "|", "?", "*"]' in filename_validator
    assert 'name.ends_with(".") or name.ends_with(" ")' in filename_validator
    assert 'var reserved = ["CON", "PRN", "AUX", "NUL"]' in filename_validator
