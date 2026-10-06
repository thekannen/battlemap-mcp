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


@pytest.mark.parametrize(
    "system, machine, companion",
    [
        ("Windows", "AMD64", "battlemap-mcp-companion-1.2.0-windows-x64.zip"),
        ("Darwin", "arm64", "battlemap-mcp-companion-1.2.0-macos-arm64.tar.gz"),
        ("Darwin", "x86_64", "battlemap-mcp-companion-1.2.0-macos-x64.tar.gz"),
        ("Linux", "x86_64", "battlemap-mcp-companion-1.2.0-linux-x64.tar.gz"),
        ("Linux", "aarch64", None),
    ],
)
def test_the_notice_links_this_computers_files(system, machine, companion):
    """Runtime behavior and validation."""
    base = "https://github.com/thekannen/battlemap-mcp/releases/download/v1.2.0/"
    links = updates.downloads("1.2.0", system, machine)
    assert links["mod"] == base + "battlemap-mcp-mod-1.2.0.zip"
    assert links["checksums"] == base + "SHA256SUMS"
    assert links.get("companion") == (base + companion if companion else None)


def test_the_notice_message_names_the_files(monkeypatch):
    monkeypatch.setattr(updates.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(updates.platform, "machine", lambda: "arm64")
    message = updates.notice("1.1.1", "1.2.0")["message"]
    assert "macos-arm64.tar.gz" in message and "SHA256SUMS" in message
    assert "battlemap-mcp-mod-1.2.0.zip" in message


@pytest.mark.parametrize(
    "path, channel",
    [
        (
            "/opt/fixture/.claude/plugins/cache/x/battlemap-mcp/1.2.0/.mcpb-cache/b/server/macos-arm64/battlemap-mcp",
            "claude-code-plugin",
        ),
        (
            "/opt/fixture/Library/Application Support/Claude/Claude Extensions/ant.dir.x/"
            "server/macos-arm64/battlemap-mcp",
            "claude-desktop-extension",
        ),
        ("/opt/fixture/Apps/battlemap-mcp/battlemap-mcp", "download"),
    ],
)
def test_the_notice_follows_how_it_was_installed(path, channel):
    """Runtime behavior and validation."""
    assert updates.install_channel(path) == channel
    message = updates.notice("1.1.1", "1.2.0", channel)["message"]
    if channel == "claude-code-plugin":
        assert "/plugin" in message and ".tar.gz" not in message
    elif channel == "claude-desktop-extension":
        assert "battlemap-mcp-1.2.0.mcpb" in message
    else:
        assert "companion" in message
