"""save_map and open_map wait for the thing they started, and say so honestly.

Both used to hand the model a polling loop: "poll get_status until
saving.in_flight is false". That costs round trips and gets the answer wrong in
both directions — an autosave raises saves_seen without writing this file, and
`map_open` stays true for the PREVIOUS map while a new one loads.

The rule these encode: an unconfirmed operation must never read as a failure
the caller can retry, because retrying a save or an open is the one thing that
cannot help.
"""

from __future__ import annotations

import itertools

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import BridgeUnavailableError, ValidationError

SAVED = "/maps/keep.dungeondraft_map"


@pytest.fixture
def fast_clock(monkeypatch):
    """Run the wait loops without spending their timeout in real seconds."""
    clock = itertools.count(0.0, 5.0)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server.time, "time", lambda: next(clock))


def status(saves_seen=0, in_flight=False, last_saved="", tracked=True, **extra):
    return {
        "map_open": True,
        "map_file": SAVED,
        "saving": {
            "in_flight": in_flight,
            "saves_seen": saves_seen,
            "last_saved": last_saved,
            "tracked": tracked,
        },
        **extra,
    }


@pytest.fixture
def bridge(monkeypatch):
    """A scripted bridge: queue replies per command, and record what was sent."""
    script: dict[str, list] = {}
    sent: list[tuple[str, dict]] = []

    def request(command, **params):
        sent.append((command, params))
        replies = script.get(command)
        if replies is None:
            raise AssertionError(f"unscripted command {command}")
        return replies[0] if len(replies) == 1 else replies.pop(0)

    monkeypatch.setattr(server.bridge, "request", request)
    return type("Bridge", (), {"script": script, "sent": sent})


def test_save_map_waits_for_this_path_and_reports_completion(bridge, fast_clock):
    bridge.script["get_status"] = [
        status(saves_seen=3),  # read before saving
        status(saves_seen=3, in_flight=True),
        status(saves_seen=4, last_saved="/maps/backup.dungeondraft_map"),  # an autosave
        status(saves_seen=5, last_saved=SAVED),
    ]
    bridge.script["save_map"] = [{"started": True, "path": SAVED}]

    result = server.save_map()

    assert result["completed"] is True
    assert result["last_saved"] == SAVED
    assert [command for command, _ in bridge.sent].count("save_map") == 1


def test_an_autosave_alone_never_settles_the_wait(bridge, fast_clock):
    """saves_seen rising proves a save happened, not that it was THIS one."""
    bridge.script["get_status"] = [
        status(saves_seen=0),
        *[status(saves_seen=9, last_saved="/maps/backups/auto.dungeondraft_map")] * 40,
    ]
    bridge.script["save_map"] = [{"started": True, "path": SAVED}]

    result = server.save_map()

    assert result["completed"] is False
    assert result["reason"] == "still_saving"


def test_an_unconfirmed_save_tells_the_caller_not_to_save_again(bridge, fast_clock):
    bridge.script["get_status"] = [
        status(saves_seen=0),
        *[status(saves_seen=0, in_flight=True)] * 40,
    ]
    bridge.script["save_map"] = [{"started": True, "path": SAVED}]

    result = server.save_map()

    assert result["completed"] is False
    assert "do NOT call save_map again" in result["note"]
    assert [command for command, _ in bridge.sent].count("save_map") == 1


def test_a_save_that_never_started_is_returned_unchanged(bridge):
    bridge.script["get_status"] = [status()]
    bridge.script["save_map"] = [{"started": False, "reason": "busy"}]

    assert server.save_map()["started"] is False


def test_wait_false_keeps_the_old_asynchronous_contract(bridge):
    bridge.script["save_map"] = [{"started": True, "path": SAVED, "async": True}]

    result = server.save_map(wait=False)

    assert result == {"started": True, "path": SAVED, "async": True}
    assert [command for command, _ in bridge.sent] == ["save_map"]


def test_a_stale_save_still_raises_for_a_caller_about_to_copy_the_file(bridge, fast_clock):
    """prepare_map_with_packs copies the file: a maybe must stop it."""
    bridge.script["get_status"] = [
        {"saving": {"in_flight": False, "last_result": "stale", "stale_path": SAVED}}
    ]
    with pytest.raises(ValidationError, match="never reported finishing"):
        server._wait_for_save(expected_path=SAVED, saves_before=0)


def test_an_untracked_save_is_uncertain_not_failed(bridge, fast_clock):
    bridge.script["get_status"] = [status(saves_seen=0), status(saves_seen=0, tracked=False)]
    bridge.script["save_map"] = [{"started": True, "path": SAVED}]

    result = server.save_map()

    assert result["completed"] is False
    assert result["reason"] == "untracked"
    assert "do not assume it was not written" in result["note"]


def test_open_map_waits_for_the_requested_map_not_merely_for_map_open(bridge, fast_clock):
    other = "/maps/previous.dungeondraft_map"
    bridge.script["open_map"] = [{"opening": True}]
    bridge.script["get_status"] = [
        {"map_open": True, "map_file": other},  # the map being replaced
        {"map_open": False, "map_file": ""},
        {"map_open": True, "map_file": SAVED, "map_size_woxels": [8960, 5120], "level_id": 0},
    ]

    result = server.open_map(SAVED)

    assert result["opened"] is True
    assert result["map_file"] == SAVED
    assert result["map_size_woxels"] == [8960, 5120]


def test_open_map_survives_the_bridge_restarting_under_it(bridge, fast_clock):
    """Mods load after the map, so the bridge goes away and comes back."""
    calls = itertools.count()

    def request(command, **params):
        if command == "open_map":
            return {"opening": True}
        if next(calls) < 3:
            raise BridgeUnavailableError("Could not reach the Dungeondraft MCP bridge")
        return {"map_open": True, "map_file": SAVED, "level_id": 0}

    bridge.script["open_map"] = [{"opening": True}]
    object.__setattr__(server.bridge, "request", request)
    try:
        assert server.open_map(SAVED)["opened"] is True
    finally:
        object.__delattr__(server.bridge, "request")


def test_open_map_that_never_arrives_says_so_without_reopening(bridge, fast_clock):
    bridge.script["open_map"] = [{"opening": True}]
    bridge.script["get_status"] = [
        {"map_open": True, "map_file": "/maps/previous.dungeondraft_map"}
    ]

    result = server.open_map(SAVED)

    assert result["opened"] is False
    assert "rather than opening it again" in result["note"]
    assert [command for command, _ in bridge.sent].count("open_map") == 1


def test_a_never_saved_map_is_not_mistaken_for_a_file(fast_clock):
    """Dungeondraft stringifies a null CurrentMapFile as the literal "Null"."""
    assert server._same_map_file("Null", SAVED) is False
    assert server._same_map_file("", SAVED) is False
    assert server._same_map_file(SAVED, SAVED) is True


# Measured while building UAT fixtures (2026-09-20): during a map load the
# outgoing bridge instance still answers, reporting the NEW map_file with the OLD
# map's counts. open_map returned `walls: 7` for a blank map.
STALE = {
    "map_open": True,
    "map_file": SAVED,
    "counts": {"walls": 7},
    "map_size_woxels": [4096, 4096],
}
FRESH = {
    "map_open": True,
    "map_file": SAVED,
    "counts": {"walls": 0},
    "map_size_woxels": [8960, 5120],
}


def test_open_map_ignores_the_outgoing_instance_reporting_the_new_path(bridge, fast_clock):
    bridge.script["open_map"] = [{"opening": True}]
    bridge.script["get_status"] = [
        {"map_open": True, "map_file": "/maps/previous.dungeondraft_map", "bridge_instance": 1},
        {**STALE, "bridge_instance": 1},  # right path, wrong world
        {**FRESH, "bridge_instance": 2},
    ]

    result = server.open_map(SAVED)

    assert result["opened"] is True
    assert result["counts"] == {"walls": 0}
    assert result["map_size_woxels"] == [8960, 5120]


def test_reopening_the_same_file_still_waits_for_the_new_instance(bridge, fast_clock):
    """The path matches from the first reading, so only the instance can tell."""
    bridge.script["open_map"] = [{"opening": True}]
    bridge.script["get_status"] = [
        {**STALE, "bridge_instance": 1},
        {**STALE, "bridge_instance": 1},
        {**FRESH, "bridge_instance": 2},
    ]

    assert server.open_map(SAVED)["counts"] == {"walls": 0}


def test_an_older_bridge_falls_back_to_rejecting_readings_with_history(bridge, fast_clock):
    bridge.script["open_map"] = [{"opening": True}]
    bridge.script["get_status"] = [
        {"map_open": True, "map_file": "/maps/previous.dungeondraft_map", "undo_depth": 12},
        {**STALE, "undo_depth": 12},  # no instance reported: history gives it away
        {**FRESH, "undo_depth": 0, "redo_depth": 0},
    ]

    assert server.open_map(SAVED)["counts"] == {"walls": 0}
