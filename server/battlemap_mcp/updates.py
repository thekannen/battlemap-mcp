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
import platform
import re
import sys
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


def downloads(version: str, system: str | None = None, machine: str | None = None) -> dict:
    """Direct links to one release's files for this computer.

    Release assets are named by version and platform, so the links follow
    from the version alone; nothing more is asked of GitHub. Missing
    `companion` means a platform no release is built for.
    """
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    name = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(system)
    base = f"https://github.com/{REPOSITORY}/releases/download/v{version}"
    links = {
        "mod": f"{base}/battlemap-mcp-mod-{version}.zip",
        "checksums": f"{base}/SHA256SUMS",
    }
    if name and arch and not (name != "macos" and arch == "arm64"):
        extension = "zip" if name == "windows" else "tar.gz"
        links["companion"] = f"{base}/battlemap-mcp-companion-{version}-{name}-{arch}.{extension}"
    return links


def install_channel(executable: str | None = None) -> str:
    """How this companion was installed, from where it runs.

    A Claude Code plugin unpacks its bundle into `.mcpb-cache` under the plugin,
    and Claude Desktop keeps extensions under `Claude Extensions`. Both update
    through their own app, so a download link would be the wrong advice.
    """
    parts = Path(executable or sys.executable).parts
    if ".mcpb-cache" in parts:
        return "claude-code-plugin"
    if "Claude Extensions" in parts:
        return "claude-desktop-extension"
    return "download"


def notice(installed: str, newest: str | None, channel: str | None = None) -> dict | None:
    """What to tell the user, or None when the installed version is current."""
    current, available = parse(installed), parse(newest or "")
    if current is None or available is None or available <= current:
        return None
    channel = channel or install_channel()
    if channel == "claude-code-plugin":
        return {
            "installed": installed,
            "latest": newest,
            "url": RELEASES_URL,
            "message": (
                f"battlemap-mcp {newest} is available (this is {installed}). In "
                "Claude Code, run /plugin, update the battlemap-mcp plugin, and "
                "restart Claude Code. Then ask me to install the bridge, and "
                "restart Dungeondraft."
            ),
        }
    if channel == "claude-desktop-extension":
        return {
            "installed": installed,
            "latest": newest,
            "url": RELEASES_URL,
            "message": (
                f"battlemap-mcp {newest} is available (this is {installed}). "
                f"Download battlemap-mcp-{newest}.mcpb from {RELEASES_URL}, open "
                "it to update the extension in Claude Desktop, then ask me to "
                "install the bridge and restart Dungeondraft."
            ),
        }
    files = downloads(str(newest))
    companion = files.get("companion", f"the one for your computer from {RELEASES_URL}")
    return {
        "installed": installed,
        "latest": newest,
        "url": RELEASES_URL,
        "downloads": files,
        "message": (
            f"battlemap-mcp {newest} is available (this is {installed}). Download "
            f"the companion, {companion}, and the mod ZIP, {files['mod']} "
            f"(checksums: {files['checksums']}). Replace the whole companion folder "
            "with the new one and run its Connect file again; replace the mod folder "
            "and restart Dungeondraft. The "
            "companion cannot update itself."
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
