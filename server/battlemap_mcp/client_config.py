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
