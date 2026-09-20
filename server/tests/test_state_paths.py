"""Runtime state belongs to this integration, never Dungeondraft's data root."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from battlemap_mcp import bridge_client


def test_linux_respects_absolute_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "custom"))
    assert bridge_client._state_file("mcp_bridge_port", _platform="linux") == (
        tmp_path / "custom" / "battlemap-mcp" / "mcp_bridge_port"
    )


def test_linux_ignores_relative_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    assert bridge_client._state_file("mcp_bridge_token", _platform="linux") == (
        tmp_path / ".local" / "state" / "battlemap-mcp" / "mcp_bridge_token"
    )


def test_old_dd_token_is_not_used_as_a_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(bridge_client.sys, "platform", "darwin")
    monkeypatch.delenv("BATTLEMAP_MCP_TOKEN_FILE", raising=False)
    old = tmp_path / "Library" / "Application Support" / "Dungeondraft" / "mcp_bridge_token"
    old.parent.mkdir(parents=True)
    old.write_text("old-credential")
    with pytest.raises(bridge_client.BridgeUnavailableError):
        bridge_client._resolve_token()
    assert old.read_text() == "old-credential"


@pytest.mark.parametrize(
    ("platform", "environment", "suffix"),
    [
        ("Windows", "LOCALAPPDATA", "custom/battlemap-mcp"),
        ("Windows", "", "AppData/Local/battlemap-mcp"),
        ("OSX", "", "Library/Application Support/battlemap-mcp"),
        ("X11", "XDG_STATE_HOME", "custom/battlemap-mcp"),
        ("X11", "", ".local/state/battlemap-mcp"),
    ],
)
def test_bridge_resolves_platform_state_in_actual_engine(tmp_path, platform, environment, suffix):
    executable = os.environ.get("DUNGEONDRAFT_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("requires isolated Godot runtime")
    source = (
        Path(__file__).resolve().parents[2] / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    ).read_text(encoding="utf-8")
    function = re.search(r"func _state_directory\(.*?(?=\nfunc )", source, re.S).group(0)
    function = function.replace("OS.get_name()", f'"{platform}"')
    harness = tmp_path / "state_path.gd"
    harness.write_text(
        "extends SceneTree\n"
        + function
        + '\nfunc _init():\n\tprint("STATE=" + _state_directory())\n\tquit(0)\n',
        encoding="utf-8",
    )
    # Supply only path lookup values inside the copied function; leave the real
    # engine's user profile and logging environment alone.
    values = {
        "HOME": tmp_path.as_posix(),
        "USERPROFILE": tmp_path.as_posix(),
        "LOCALAPPDATA": "",
        "XDG_STATE_HOME": "",
    }
    if environment:
        values[environment] = (tmp_path / "custom").as_posix()
    text = harness.read_text(encoding="utf-8")
    for name, value in values.items():
        text = text.replace(f'OS.get_environment("{name}")', f'"{value}"')
    harness.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [executable, "--no-window", "--script", str(harness)],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"STATE={tmp_path.as_posix()}/{suffix}".encode() in result.stdout
    assert not (tmp_path / suffix).exists()  # Resolving must not create state.
