"""With a desktop extension and a Claude Code connection both installed, every
tool appeared twice, from companions that can be different versions, and
nothing told the user. These tests build the Claude apps' records in a temp
folder; the files are other apps' and undocumented, so unreadable ones must be
skipped, never raised.
"""

from __future__ import annotations

import json

import pytest

from battlemap_mcp import client_config, server


@pytest.fixture
def claude(tmp_path, monkeypatch):
    """Empty Claude Code and Claude desktop folders."""
    code = tmp_path / "code"
    app = tmp_path / "app"
    (code / "plugins").mkdir(parents=True)
    (app / "Claude Extensions Settings").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(code))
    monkeypatch.setattr(client_config, "_claude_app_dir", lambda: app)
    monkeypatch.setattr(
        client_config,
        "claude_registry_paths",
        lambda: {
            "Claude Code (user scope)": code / ".claude.json",
            "Claude Desktop (chat)": app / "claude_desktop_config.json",
        },
    )
    return code, app


def _connection(code):
    entry = {"mcpServers": {client_config.SERVER_NAME: {"command": "/apps/companion"}}}
    (code / ".claude.json").write_text(json.dumps(entry))


def _extension(app, version="1.3.0", enabled=True, name=None):
    ident = "local.mcpb.thekannen.x"
    record = {
        "extensions": {
            ident: {
                "version": version,
                "manifest": {"name": name or client_config.SERVER_NAME, "version": version},
            }
        }
    }
    (app / "extensions-installations.json").write_text(json.dumps(record))
    (app / "Claude Extensions Settings" / f"{ident}.json").write_text(
        json.dumps({"isEnabled": enabled})
    )


def _plugin(code, version="1.4.2"):
    record = {
        "version": 2,
        "plugins": {f"{client_config.PLUGIN_NAME}@market": [{"version": version}]},
    }
    (code / "plugins" / "installed_plugins.json").write_text(json.dumps(record))


def test_one_route_is_not_a_duplicate(claude):
    code, _ = claude
    _connection(code)
    installs = client_config.claude_installs()
    assert installs == [{"route": "Claude Code connection", "version": None}]
    assert client_config.duplicate_note(installs, "download") is None


def test_a_connection_and_an_extension_are_named_with_versions(claude):
    code, app = claude
    _connection(code)
    _extension(app, version="1.3.0")
    note = client_config.duplicate_note(client_config.claude_installs(), "download")
    assert note is not None
    assert "2 ways" in note["message"] and "Claude desktop extension (1.3.0)" in note["message"]
    assert "Tell the user" in note["message"]


def test_a_plugin_counts_with_its_version(claude):
    code, app = claude
    _plugin(code, "1.4.2")
    _extension(app)
    routes = [(i["route"], i["version"]) for i in client_config.claude_installs()]
    assert ("Claude Code plugin", "1.4.2") in routes


def test_a_disabled_extension_or_another_product_is_ignored(claude):
    code, app = claude
    _connection(code)
    _extension(app, enabled=False)
    assert len(client_config.claude_installs()) == 1
    _extension(app, name="someone-else")
    assert len(client_config.claude_installs()) == 1


def test_unreadable_records_are_skipped(claude):
    code, app = claude
    (code / ".claude.json").write_text("{not json")
    (app / "extensions-installations.json").write_text('{"extensions": [1, 2]}')
    (code / "plugins" / "installed_plugins.json").write_text('{"plugins": {"x": 3}}')
    assert client_config.claude_installs() == []


def test_ping_carries_the_note(claude, monkeypatch):
    code, app = claude
    _connection(code)
    _extension(app)
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **_: {"pong": True})
    monkeypatch.setattr(server.updates, "available", lambda: None)
    result = server.ping()
    assert result["duplicate_installs"]["installs"][1]["route"] == "Claude desktop extension"


def test_ping_survives_a_broken_inventory(monkeypatch):
    def broken():
        raise RuntimeError("unexpected file layout")

    monkeypatch.setattr(client_config, "claude_installs", broken)
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **_: {"pong": True})
    monkeypatch.setattr(server.updates, "available", lambda: None)
    assert "duplicate_installs" not in server.ping()
