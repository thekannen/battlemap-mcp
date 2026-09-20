"""Tests for installer actions exposed on the MCP surface."""

from __future__ import annotations


def test_install_tool_returns_a_write_free_preview_by_default(monkeypatch, tmp_path):
    """Tool callers must explicitly opt in before the bridge directory is created."""
    from battlemap_mcp import server

    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")

    preview = server.install_dungeondraft_bridge(str(mods_dir))

    assert preview["changed"] is False
    assert preview["destination"] == str(mods_dir / "battlemap-mcp-bridge")
    assert not mods_dir.exists()


def test_inspection_separates_historical_log_from_static_files(monkeypatch, tmp_path):
    from battlemap_mcp import server

    dd = tmp_path / "Dungeondraft"
    logs = dd / "logs"
    logs.mkdir(parents=True)
    (logs / "session.log").write_text(
        "Battlemap MCP Bridge mod found in /old/mods/mcp_bridge.ddmod\n"
        "[mcp-bridge] listening on 127.0.0.1:8787 (protocol v23)\n"
    )
    monkeypatch.setattr(server.installer, "dungeondraft_data_dir", lambda: dd)
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(server.installer, "candidate_mods_dirs", lambda: [tmp_path / "mods"])

    def forbidden_live_check():
        raise AssertionError("default inspection must not authenticate or contact the bridge")

    monkeypatch.setattr(server.installer, "live_bridge_identity", forbidden_live_check)
    report = server.inspect_dungeondraft_installation()
    assert report["status"] == "missing"
    assert report["latest_log"]["mod_path"] == "/old/mods/mcp_bridge.ddmod"
    assert report["latest_log"]["protocol"] == 23
    assert report["latest_log"]["live_verified"] is False


def test_inspection_opt_in_reports_authenticated_location(monkeypatch, tmp_path):
    from battlemap_mcp import server

    monkeypatch.setattr(server.installer, "dungeondraft_data_dir", lambda: tmp_path)
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(server.installer, "candidate_mods_dirs", lambda: [tmp_path / "mods"])
    monkeypatch.setattr(
        server.installer,
        "live_bridge_identity",
        lambda: server.installer.LiveIdentity(
            "current",
            "Matches",
            bridge_root=str(tmp_path / "executing"),
            process_id=123,
        ),
    )
    report = server.inspect_dungeondraft_installation(live=True)
    assert report["live_identity"]["bridge_root"] == str(tmp_path / "executing")
    assert report["live_identity"]["process_id"] == 123
    assert report["latest_log"]["live_verified"] is False
