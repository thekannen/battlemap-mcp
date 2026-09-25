"""Tell the user when a newer release has been published.

The companion cannot update itself, so the only way a user learns of a fix is
by being told. At most once a day, this asks GitHub's API for the latest
published release: drafts and prereleases never count, and a version number is
the only thing read from the reply. Nothing is downloaded or run. GitHub sees
the request's IP address; no version, identifier or map data is sent.

Set BATTLEMAP_MCP_UPDATE_CHECK=0 to turn it off. Every failure is silent:
offline, rate-limited or blocked, the companion behaves as if no update exists.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import __version__, installer, user_settings

REPOSITORY = "thekannen/battlemap-mcp"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases/latest"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
OPT_OUT = "BATTLEMAP_MCP_UPDATE_CHECK"
CHECK_INTERVAL = timedelta(hours=24)
TIMEOUT = 3.0
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

_lock = threading.Lock()
_result: dict | None = None
_started = False


def enabled() -> bool:
    """The environment variable if set, else the Dungeondraft panel's setting."""
    return user_settings.update_check(OPT_OUT)


def cache_path() -> Path:
    return installer.default_state_dir() / "battlemap-mcp" / "update-check.json"


def parse(version: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(version.strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def fetch_latest(timeout: float = TIMEOUT) -> str | None:
    """The latest published version, or None when GitHub cannot say."""
    request = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "battlemap-mcp"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            tag = json.load(response).get("tag_name", "")
    except Exception:  # noqa: BLE001 - any failure means "no news", never an error
        return None
    version = str(tag).removeprefix("v")
    return version if parse(version) else None


def latest(now: datetime | None = None, *, fetch=fetch_latest) -> str | None:
    """The latest version, from a cache younger than a day or from GitHub."""
    now = now or datetime.now(UTC)
    path = cache_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if now - datetime.fromisoformat(cached["checked"]) < CHECK_INTERVAL:
            return cached.get("latest")
    except (OSError, ValueError, KeyError, TypeError):
        pass
    version = fetch()
    if version is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"checked": now.isoformat(), "latest": version}) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return version


def notice(installed: str, newest: str | None) -> dict | None:
    """What to tell the user, or None when the installed version is current."""
    current, available = parse(installed), parse(newest or "")
    if current is None or available is None or available <= current:
        return None
    return {
        "installed": installed,
        "latest": newest,
        "url": RELEASES_URL,
        "message": (
            f"battlemap-mcp {newest} is available (this is {installed}). Download the "
            f"companion and the mod ZIP from {RELEASES_URL} and install both; "
            "the companion cannot update itself."
        ),
    }


def check_now() -> dict | None:
    """Blocking check for the command line; None when disabled or current."""
    if not enabled():
        return None
    return notice(__version__, latest())


def start_background_check() -> None:
    """Check once per process without delaying startup or any tool call."""
    global _started
    with _lock:
        if _started or not enabled():
            return
        _started = True

    def run() -> None:
        global _result
        result = notice(__version__, latest())
        with _lock:
            _result = result

    threading.Thread(target=run, name="update-check", daemon=True).start()


def available() -> dict | None:
    """The background check's notice, once it has finished; never blocks.

    Re-reads the setting, so turning the check off in Dungeondraft's panel
    also hides a notice found earlier in the session.
    """
    if not enabled():
        return None
    with _lock:
        return _result
