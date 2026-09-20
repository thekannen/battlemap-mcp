"""The Claude plugin and marketplace manifests. Offline — no CLI, no network.

Both schemas were confirmed against the installed `claude` CLI rather than
assumed: `claude plugin init --with mcp` produced the plugin.json shape, and
`claude plugin marketplace add` names `.claude-plugin/marketplace.json` and
accepted this one. These tests keep them from drifting out of that shape.
"""

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPOSITORY_ROOT / ".claude-plugin"


def _load(name: str) -> dict:
    path = MANIFEST_DIR / name
    assert path.is_file(), f"{name} is missing from .claude-plugin/"
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_manifest_has_what_the_cli_scaffolds():
    plugin = _load("plugin.json")
    for key in ("name", "version", "description", "author", "skills"):
        assert key in plugin, f"plugin.json is missing {key!r}"
    assert plugin["name"] == "battlemap-mcp"
    assert isinstance(plugin["skills"], list) and plugin["skills"]


def test_marketplace_manifest_lists_this_plugin():
    marketplace = _load("marketplace.json")
    for key in ("name", "owner", "plugins"):
        assert key in marketplace, f"marketplace.json is missing {key!r}"
    names = {entry["name"] for entry in marketplace["plugins"]}
    assert "battlemap-mcp" in names


def test_the_plugin_ships_the_skills_that_actually_exist():
    """A skills path that resolves to nothing installs a plugin with no content."""
    plugin = _load("plugin.json")
    for relative in plugin["skills"]:
        directory = (REPOSITORY_ROOT / relative).resolve()
        assert directory.is_dir(), f"skills path {relative!r} is not a directory"
        found = sorted(p.parent.name for p in directory.glob("*/SKILL.md"))
        assert found, f"no SKILL.md found under {relative!r}"
        # the art-direction entry point has to be among them, or the plugin
        # ships helpers with nothing to enter through
        assert "battlemap-art-direction" in found


def test_plugin_version_tracks_the_python_package():
    """Two version numbers that can disagree will, and the mismatch ships."""
    plugin = _load("plugin.json")
    pyproject = (REPOSITORY_ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8")
    for line in pyproject.splitlines():
        if line.strip().startswith("version"):
            package_version = line.split("=", 1)[1].strip().strip('"')
            break
    else:  # pragma: no cover - pyproject always declares one
        raise AssertionError("no version in server/pyproject.toml")
    assert plugin["version"] == package_version, (
        f"plugin.json says {plugin['version']}, pyproject says {package_version}"
    )
