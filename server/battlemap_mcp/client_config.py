"""Supported client-CLI integration without direct settings-file writes."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClientRegistrationResult:
    """The outcome of an optional, user-scoped client setup command."""

    registered: bool
    manual_command: list[str] | None
    client_cli_available: bool = False
    # The command of a Claude Code user entry that already holds this name,
    # which `claude mcp add` refuses to replace.
    existing_command: str | None = None


def registration_argv(client: str, executable: Path) -> list[str]:
    """Return the supported user-scoped registration command for a client."""
    validate_launcher(executable)
    command = str(executable)
    if client == "claude-code":
        return ["claude", "mcp", "add", "--scope", "user", "battlemap", "--", command]
    if client == "codex":
        return ["codex", "mcp", "add", "battlemap", "--", command]
    raise ValueError(f"Unsupported MCP client: {client}")


def validate_launcher(executable: Path) -> None:
    """Refuse uv cache launchers that can disappear on cache cleanup."""
    candidates = (executable.absolute(), executable.resolve())
    cache = os.environ.get("UV_CACHE_DIR")
    for candidate in candidates:
        if any(
            re.fullmatch(r"(?:archive|tools)-v\d+", part.lower()) for part in candidate.parts
        ) or (cache and candidate.is_relative_to(Path(cache).expanduser().resolve())):
            raise ValueError(
                "Cannot register a disposable uv cache launcher. Use uv tool install "
                "battlemap-mcp, then run its persistent battlemap-mcp launcher; "
                "or supply --server-executable with a durable launcher."
            )


def register_client(
    client: str,
    executable: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> ClientRegistrationResult:
    """Register a local stdio server through the requested client's CLI."""
    if client == "none":
        return ClientRegistrationResult(registered=False, manual_command=None)

    command = registration_argv(client, executable)
    if client == "claude-code" and _claude_launcher_matches(executable):
        return ClientRegistrationResult(registered=True, manual_command=None)
    launcher = shutil.which(command[0])
    if launcher is None:
        return ClientRegistrationResult(
            registered=False, manual_command=command, client_cli_available=False
        )

    invocation = command.copy()
    invocation[0] = launcher

    try:
        completed = runner(
            invocation,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
        )
    except OSError:
        return ClientRegistrationResult(
            registered=False, manual_command=command, client_cli_available=False
        )
    if completed.returncode == 0:
        return ClientRegistrationResult(
            registered=True, manual_command=None, client_cli_available=True
        )
    return ClientRegistrationResult(
        registered=False,
        manual_command=command,
        client_cli_available=True,
        existing_command=_claude_registered_command() if client == "claude-code" else None,
    )


def _claude_user_entry() -> Any:
    config = json.loads(
        claude_registry_paths()["Claude Code (user scope)"].read_text(encoding="utf-8")
    )
    return config["mcpServers"]["battlemap"]


def _claude_registered_command() -> str | None:
    """The command an existing Claude Code user entry runs, if there is one."""
    try:
        command = _claude_user_entry().get("command")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return command if isinstance(command, str) and command else None


def _claude_launcher_matches(executable: Path) -> bool:
    """A repeated setup need not remove an already-correct user entry."""
    try:
        entry = _claude_user_entry()
        return (
            entry.get("type", "stdio") == "stdio"
            and entry.get("args", []) == []
            and isinstance(entry.get("command"), str)
            and Path(entry["command"]).is_absolute()
            and Path(entry["command"]) == executable.absolute()
        )
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        return False


def claude_registry_paths() -> dict[str, Path]:
    """Name each Claude user registry separately; Code is not Desktop chat."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    code = Path(config_dir) / ".claude.json" if config_dir else Path.home() / ".claude.json"
    paths = {"Claude Code (user scope)": code}
    if sys.platform == "darwin":
        paths["Claude Desktop (chat)"] = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    elif sys.platform == "win32":
        paths["Claude Desktop (chat)"] = (
            Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            / "Claude"
            / "claude_desktop_config.json"
        )
    return paths


def inspect_registration(path: Path) -> str:
    """Report presence, not connection health, without exposing config values."""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "not registered (config missing)"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "cannot inspect config"
    if not isinstance(config, dict):
        return "invalid config"
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        return "invalid mcpServers config"
    if "battlemap" not in servers:
        return "not registered"
    entry = servers["battlemap"]
    if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
        return "invalid battlemap registration"
    if not entry["command"].strip():
        return "invalid battlemap registration"
    return "registered (connection not tested)"


def opencode_config_path() -> Path:
    """OpenCode's global config file."""
    return Path.home() / ".config" / "opencode" / "opencode.json"


def opencode_entry(executable: Path) -> dict[str, Any]:
    """The `mcp` entry OpenCode needs: a local stdio command with no arguments.

    This is the format OpenCode 1.x documents. OpenCode 2.x writes entries
    under `mcp.servers` but still reads this one.
    """
    validate_launcher(executable)
    return {"type": "local", "command": [str(executable)], "enabled": True}


def opencode_registration_argv(executable: Path) -> list[str]:
    """OpenCode 2.x's own command for a global local server."""
    validate_launcher(executable)
    return ["opencode", "mcp", "add", "--global", "battlemap", "--", str(executable)]


def opencode_registered_command(path: Path | None = None) -> list[str] | None:
    """The command of an existing global OpenCode `battlemap` entry, if any.

    Reads both formats: OpenCode 2.x's `mcp.servers.<name>` and 1.x's
    `mcp.<name>`. A 2.x `mcp add` into a 1.x file leaves both in one file,
    and OpenCode reads it that way. Comments (JSONC) are not parsed: such a
    file reads as no entry, and `mcp add` would then replace one silently,
    so register_opencode refuses to run on a file it cannot read.
    """
    try:
        config = json.loads((path or opencode_config_path()).read_text(encoding="utf-8"))
        mcp = config["mcp"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(mcp, dict):
        return None
    servers = mcp.get("servers")
    for table in (servers if isinstance(servers, dict) else {}, mcp):
        entry = table.get("battlemap")
        command = entry.get("command") if isinstance(entry, dict) else None
        if isinstance(command, list) and all(isinstance(part, str) for part in command):
            return command
    return None


def _opencode_config_unreadable(path: Path) -> bool:
    """True when the file exists but is not plain JSON this module can check."""
    if not path.exists():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return True
    return False


def register_opencode(
    executable: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> ClientRegistrationResult:
    """Add the server through `opencode mcp add --global` (OpenCode 2.x).

    That command replaces an entry of the same name without asking, unlike
    `claude mcp add`, so the caller checks opencode_registered_command first.
    OpenCode 1.x has no `mcp add`; the result then asks for the manual entry.
    """
    command = opencode_registration_argv(executable)
    launcher = shutil.which(command[0])
    if launcher is None or _opencode_config_unreadable(opencode_config_path()):
        return ClientRegistrationResult(
            registered=False, manual_command=None, client_cli_available=launcher is not None
        )
    try:
        probe = runner(
            [launcher, "mcp", "add", "--help"],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=60,
        )
        # OpenCode 1.19 has `mcp add` without --global, and the add then fails.
        if probe.returncode != 0 or "--global" not in f"{probe.stdout}{probe.stderr}":
            return ClientRegistrationResult(
                registered=False, manual_command=None, client_cli_available=True
            )
        completed = runner(
            [launcher, *command[1:]],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ClientRegistrationResult(
            registered=False, manual_command=command, client_cli_available=True
        )
    return ClientRegistrationResult(
        registered=completed.returncode == 0,
        manual_command=None if completed.returncode == 0 else command,
        client_cli_available=True,
    )


SERVER_NAME = "battlemap"
PLUGIN_NAME = "battlemap-mcp"


def _claude_app_dir() -> Path | None:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude"
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def _desktop_extensions(app_dir: Path) -> list[dict[str, Any]]:
    data = _read_json(app_dir / "extensions-installations.json")
    found = []
    extensions = data.get("extensions") if isinstance(data, dict) else None
    for ident, entry in (extensions or {}).items() if isinstance(extensions, dict) else []:
        manifest = entry.get("manifest") if isinstance(entry, dict) else None
        if not isinstance(manifest, dict) or manifest.get("name") != SERVER_NAME:
            continue
        settings = _read_json(app_dir / "Claude Extensions Settings" / f"{ident}.json")
        if isinstance(settings, dict) and settings.get("isEnabled") is False:
            continue
        found.append({"route": "Claude desktop extension", "version": entry.get("version")})
    return found


def _code_plugins() -> list[dict[str, Any]]:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    data = _read_json(base / "plugins" / "installed_plugins.json")
    plugins = data.get("plugins") if isinstance(data, dict) else None
    found = []
    for key, entries in plugins.items() if isinstance(plugins, dict) else []:
        if str(key).split("@", 1)[0] != PLUGIN_NAME or not isinstance(entries, list):
            continue
        version = entries[0].get("version") if entries and isinstance(entries[0], dict) else None
        found.append({"route": "Claude Code plugin", "version": version})
    return found


def claude_installs() -> list[dict[str, Any]]:
    """Every route by which a Claude app on this computer loads this server."""
    installs: list[dict[str, Any]] = []
    if _claude_registered_command():
        installs.append({"route": "Claude Code connection", "version": None})
    installs.extend(_code_plugins())
    app_dir = _claude_app_dir()
    if app_dir is not None:
        installs.extend(_desktop_extensions(app_dir))
        desktop_config = claude_registry_paths().get("Claude Desktop (chat)")
        if desktop_config and inspect_registration(desktop_config).startswith("registered"):
            installs.append({"route": "Claude desktop config file", "version": None})
    return installs


def duplicate_note(installs: list[dict[str, Any]], running: str) -> dict[str, Any] | None:
    """What to tell the user when more than one route is installed."""
    if len(installs) < 2:
        return None
    named = ", ".join(
        f"{item['route']} ({item['version']})" if item.get("version") else item["route"]
        for item in installs
    )
    return {
        "installs": installs,
        "this_one": running,
        "message": (
            f"This Dungeondraft server is installed for Claude {len(installs)} ways: "
            f"{named}. Where two load in the same app (Claude Code with a plugin "
            "and a connection, or the Claude desktop app's Code tab), every tool "
            "appears twice, possibly from different versions. Tell the user and "
            "suggest keeping one: Settings > Extensions in the desktop app, /plugin "
            f"in Claude Code, or `claude mcp remove {SERVER_NAME}` for a connection."
        ),
    }
