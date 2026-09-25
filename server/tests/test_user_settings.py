"""Runtime behavior and validation."""

from __future__ import annotations

import json
import os

from battlemap_mcp import server, updates, user_settings


def _panel(data) -> None:
    path = user_settings.path()
    path.write_text(json.dumps(data), encoding="utf-8")
    # A later write inside the same mtime tick would be missed; tests step it.
    stamp = path.stat().st_mtime + len(json.dumps(data))
    os.utime(path, (stamp, stamp))


def test_nothing_chosen_means_the_defaults(monkeypatch):
    monkeypatch.delenv(updates.OPT_OUT, raising=False)
    assert updates.enabled() is True
    assert server._capture_keep() == 20
    assert user_settings.snap_default() == "none"


def test_the_panel_turns_the_update_check_off(monkeypatch):
    monkeypatch.delenv(updates.OPT_OUT, raising=False)
    _panel({"update_check": False})
    assert updates.enabled() is False


def test_an_explicit_environment_variable_wins_over_the_panel(monkeypatch):
    _panel({"update_check": False, "capture_retention": 5})
    monkeypatch.setenv(updates.OPT_OUT, "1")
    monkeypatch.setenv(server.CAPTURE_RETENTION_ENV, "40")
    assert updates.enabled() is True
    assert server._capture_keep() == 40
    sources = user_settings.sources(updates.OPT_OUT, server.CAPTURE_RETENTION_ENV)
    assert sources["update_check"]["source"] == "environment"
    assert sources["capture_retention"] == {"value": 40, "source": "environment"}


def test_panel_retention_applies_without_the_environment(monkeypatch):
    monkeypatch.delenv(server.CAPTURE_RETENTION_ENV, raising=False)
    _panel({"capture_retention": 7})
    assert server._capture_keep() == 7


def test_a_changed_file_is_read_again():
    _panel({"snap_default": "auto"})
    assert user_settings.snap_default() == "auto"
    _panel({"snap_default": "none", "padding": "x"})
    assert user_settings.snap_default() == "none"


def test_bad_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.delenv(updates.OPT_OUT, raising=False)
    _panel({"update_check": "no", "capture_retention": True, "snap_default": "hex"})
    assert updates.enabled() is True
    assert server._capture_keep() == 20
    assert user_settings.snap_default() == "none"


def test_an_unreadable_file_is_no_settings():
    user_settings.path().write_text("{not json", encoding="utf-8")
    assert user_settings.load() == {}


def test_a_placement_without_snap_follows_the_panel(monkeypatch):
    calls = []

    def request(command, **params):
        calls.append(command)
        if command == "get_snap_settings":
            return {"vanilla_snapping": False, "mod_loaded": False}
        return {"id": 1}

    monkeypatch.setattr(server.bridge, "request", request)
    _panel({"snap_default": "auto"})
    result = server.place_object("res://a.png", x=1, y=1)
    assert calls == ["get_snap_settings", "place_object"]
    assert result["snap"]["mode"] == "auto"


def test_turning_the_check_off_hides_a_notice_already_found(monkeypatch):
    """The background check runs once at startup; the panel can change later."""
    monkeypatch.delenv(updates.OPT_OUT, raising=False)
    monkeypatch.setattr(updates, "_result", {"latest": "9.9.9"})
    assert updates.available() == {"latest": "9.9.9"}
    _panel({"update_check": False})
    assert updates.available() is None
