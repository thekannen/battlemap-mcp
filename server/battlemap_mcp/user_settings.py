"""The bridge's panel writes them to `mcp_bridge_settings.json` in the
integration's state folder, beside the token. No bridge command writes that
file, so an assistant can read these but never change them. An environment
variable that is explicitly set still wins, so admin and CI configurations
keep working; `sources()` says which applied.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .state_paths import state_dir

SETTINGS_FILE = "mcp_bridge_settings.json"
SNAP_DEFAULTS = ("none", "auto")

_cache: tuple[float, dict] | None = None


def path() -> Path:
    return state_dir() / SETTINGS_FILE


def load() -> dict:
    """The panel's settings, re-read when the file changes; {} if absent or unreadable."""
    global _cache
    try:
        mtime = path().stat().st_mtime
    except OSError:
        _cache = None
        return {}
    if _cache is not None and _cache[0] == mtime:
        return _cache[1]
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _cache = (mtime, data)
    return data


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() != "" else None


def update_check(env_var: str) -> bool:
    """Whether to check for a newer release: the env var if set, else the panel, else yes."""
    value = _env(env_var)
    if value is not None:
        return value.lower() not in {"0", "false", "no", "off"}
    setting = load().get("update_check")
    return setting if isinstance(setting, bool) else True


def capture_retention(env_var: str, default: int = 20) -> int:
    """How many generated captures to keep: the env var if set, else the panel."""
    value = _env(env_var)
    if value is not None:
        try:
            return max(0, int(value))
        except ValueError:
            return default
    setting = load().get("capture_retention")
    if isinstance(setting, int) and not isinstance(setting, bool):
        return max(0, setting)
    return default


def snap_default() -> str:
    """The panel's default for a placement's `snap` when the caller gave none."""
    setting = load().get("snap_default")
    return setting if setting in SNAP_DEFAULTS else "none"


def sources(update_env: str, retention_env: str) -> dict:
    """Each effective value and whether the panel or the environment set it."""
    panel = load()
    return {
        "update_check": {
            "value": update_check(update_env),
            "source": "environment"
            if _env(update_env) is not None
            else ("panel" if "update_check" in panel else "default"),
        },
        "capture_retention": {
            "value": capture_retention(retention_env),
            "source": "environment"
            if _env(retention_env) is not None
            else ("panel" if "capture_retention" in panel else "default"),
        },
        "snap_default": {
            "value": snap_default(),
            "source": "panel" if "snap_default" in panel else "default",
        },
    }
