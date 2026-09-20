"""Tests for the Dungeondraft bridge payload included with the package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def test_payload_root_contains_the_bridge_manifest():
    """Installer packaging must expose the canonical bridge mod directory."""
    from battlemap_mcp.installer import payload_root

    manifest = payload_root().joinpath("mcp_bridge.ddmod")

    assert manifest.is_file()
    contents = manifest.read_text()
    assert '"unique_id": "Knownframe.MCPBridge"' in contents
    assert '"dd_version": "1.2.0.1"' in contents


def test_bridge_payload_supports_vanilla_only_asset_filtering():
    """The server's vanilla_only option must be understood by the shipped bridge."""
    from battlemap_mcp.installer import payload_root

    bridge = payload_root().joinpath("scripts", "tools", "mcp_bridge.gd").read_text()

    assert 'req.get("vanilla_only", false)' in bridge
    assert 'begins_with("res://textures/")' in bridge


def test_bridge_payload_creates_its_tool_icon_in_a_user_writable_location():
    """Installing a mod under Program Files must not cause a startup write error."""
    from battlemap_mcp.installer import payload_root

    bridge = payload_root().joinpath("scripts", "tools", "mcp_bridge.gd").read_text()

    assert 'var path = "user://mcp_bridge.png"' in bridge
    assert 'Global.Root + "icons/mcp_bridge.png"' not in bridge


def test_bridge_payload_accepts_an_evaluator_dedicated_listen_port():
    """An eval process must not rely on the user's shared bridge port file."""
    from battlemap_mcp.installer import payload_root

    bridge = payload_root().joinpath("scripts", "tools", "mcp_bridge.gd").read_text()

    assert 'const EVALUATOR_PORT_ENV := "BATTLEMAP_MCP_LISTEN_PORT"' in bridge
    assert "OS.get_environment(EVALUATOR_PORT_ENV)" in bridge
    port_publisher = bridge.split("func _write_port_file", 1)[1].split("func update", 1)[0]
    assert 'if OS.get_environment(EVALUATOR_PORT_ENV) != "":' in port_publisher


def test_skills_payload_contains_discoverable_skills_and_shared_references():
    """The installable package must carry the entire Codex skill bundle."""
    from battlemap_mcp.installer import skills_payload_root

    payload = skills_payload_root()

    assert payload.joinpath("battlemap-art-direction", "SKILL.md").is_file()
    assert payload.joinpath("_shared", "build-loop.md").is_file()


def test_default_build_includes_the_bridge_in_the_wheel(tmp_path):
    """A release build must retain the mod after its sdist-to-wheel step."""
    result = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    wheel = next(tmp_path.glob("*.whl"))
    with ZipFile(wheel) as archive:
        manifest_path = "battlemap_mcp/bridge_payload/battlemap-mcp-bridge/mcp_bridge.ddmod"
        assert manifest_path in archive.namelist()
        assert '"dd_version": "1.2.0.1"' in archive.read(manifest_path).decode()
        assert "battlemap_mcp/skills_payload/battlemap-art-direction/SKILL.md" in archive.namelist()
        assert "battlemap_mcp/skills_payload/_shared/build-loop.md" in archive.namelist()
