"""The companion cannot update itself, so it must say when a newer release exists."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from battlemap_mcp import cli, server, updates


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setenv(updates.OPT_OUT, "1")
    monkeypatch.setattr(updates.installer, "default_state_dir", lambda: tmp_path)
    return tmp_path / "battlemap-mcp" / "update-check.json"


@pytest.mark.parametrize(
    ("installed", "newest", "expected"),
    [
        ("1.0.1", "1.0.2", True),
        ("1.0.1", "1.1.0", True),
        ("1.0.9", "1.0.10", True),  # numeric, not string, comparison
        ("1.0.1", "1.0.1", False),
        ("1.0.2", "1.0.1", False),  # a local build ahead of the release
        ("1.0.1", None, False),
        ("1.0.1", "not-a-version", False),
    ],
)
def test_notice_only_for_a_newer_release(installed, newest, expected):
    notice = updates.notice(installed, newest)
    assert (notice is not None) is expected
    if notice:
        assert notice["url"] == updates.RELEASES_URL
        assert newest in notice["message"] and "mod ZIP" in notice["message"]


def test_github_is_asked_at_most_once_a_day(state):
    calls = []

    def fetch():
        calls.append(1)
        return "1.0.2"

    now = datetime(2026, 9, 23, tzinfo=UTC)
    assert updates.latest(now, fetch=fetch) == "1.0.2"
    assert updates.latest(now + timedelta(hours=23), fetch=fetch) == "1.0.2"
    assert len(calls) == 1
    assert json.loads(state.read_text())["latest"] == "1.0.2"
    assert updates.latest(now + timedelta(hours=25), fetch=fetch) == "1.0.2"
    assert len(calls) == 2


def test_a_failed_check_is_silent_and_not_cached(state):
    assert updates.latest(fetch=lambda: None) is None
    assert not state.exists()


def test_a_corrupt_cache_is_ignored(state):
    state.parent.mkdir(parents=True)
    state.write_text("{not json")
    assert updates.latest(fetch=lambda: "1.0.2") == "1.0.2"


def test_fetch_failure_returns_none(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(updates.urllib.request, "urlopen", fail)
    assert updates.fetch_latest() is None


def test_opt_out_makes_no_request(monkeypatch):
    monkeypatch.setenv(updates.OPT_OUT, "0")
    monkeypatch.setattr(updates, "latest", lambda *a, **k: pytest.fail("checked while opted out"))
    assert updates.check_now() is None


def test_background_notice_reaches_ping_and_get_status(monkeypatch, state):
    monkeypatch.setattr(updates, "_started", False)
    monkeypatch.setattr(updates, "_result", None)
    monkeypatch.setattr(updates, "latest", lambda: "99.0.0")
    updates.start_background_check()
    for _ in range(100):
        if updates.available():
            break
        time.sleep(0.01)
    status = server._add_update_notice({"map_open": True})
    assert status["update_available"]["latest"] == "99.0.0"
    assert server._add_update_notice("not a dict") == "not a dict"


def test_no_notice_until_the_check_finishes(monkeypatch):
    monkeypatch.setattr(updates, "_result", None)
    assert "update_available" not in server._add_update_notice({"map_open": True})


def test_check_connection_says_so_loudly(monkeypatch, capsys, state):
    monkeypatch.setattr(updates, "latest", lambda: "99.0.0")
    cli._report_update()
    output = capsys.readouterr().out
    assert "UPDATE AVAILABLE" in output and "99.0.0" in output
    assert updates.RELEASES_URL in output


def test_check_connection_is_quiet_when_current(monkeypatch, capsys, state):
    monkeypatch.setattr(updates, "latest", lambda: updates.__version__)
    cli._report_update()
    assert capsys.readouterr().out == ""
