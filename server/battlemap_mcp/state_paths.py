"""Shared platform conventions for integration-owned runtime state."""

from __future__ import annotations

import os
import sys
from pathlib import Path

STATE_DIRECTORY = "battlemap-mcp"


def state_dir(*, _platform: str | None = None) -> Path:
    """Resolve without creating directories or altering permissions.

    Keep in sync with the bridge's _state_directory. Public export renames
    STATE_DIRECTORY together with the package; Dungeondraft paths stay separate.
    """
    platform = _platform if _platform is not None else sys.platform
    home = Path.home()
    if platform.startswith("win"):
        value = os.environ.get("LOCALAPPDATA", "")
        base = Path(value) if value and Path(value).is_absolute() else home / "AppData" / "Local"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        value = os.environ.get("XDG_STATE_HOME", "")
        base = Path(value) if value and Path(value).is_absolute() else home / ".local" / "state"
    return base / STATE_DIRECTORY
