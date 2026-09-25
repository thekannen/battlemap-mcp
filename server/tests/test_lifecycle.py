"""Runtime behavior and validation."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from battlemap_mcp import lifecycle

# The middle process stands in for the MCP client. It runs on the base
# interpreter, so killing it kills the client itself; on Windows a venv's
# python.exe is a launcher that starts the real interpreter as a child. The
# companion is started the way a client starts a source install, through
# sys.executable, so on Windows it sits behind that launcher exactly as a
# `python -m` companion does. It prints its own pid, not the launcher's, and
# runs the real watchdog while "busy" (sleeping), as in a long tool call.
MIDDLE = """
import subprocess, sys
child = subprocess.Popen([{python!r}, "-c", {companion!r}])
child.wait()
"""
COMPANION = """
import os, time
from battlemap_mcp import lifecycle
lifecycle.start(poll=0.1)
print(os.getpid(), flush=True)
time.sleep(60)
"""


def _alive(pid: int) -> bool:
    if sys.platform.startswith("win"):
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # A zombie still answers kill(0); ask ps whether it is really running.
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return state.stdout.strip() not in ("", "Z")


def _spawn(env: dict[str, str]) -> tuple[subprocess.Popen, int]:
    middle = subprocess.Popen(
        [
            getattr(sys, "_base_executable", sys.executable),
            "-c",
            MIDDLE.format(python=sys.executable, companion=COMPANION),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    companion = int(middle.stdout.readline())
    return middle, companion


def test_the_companion_exits_when_its_client_is_killed():
    middle, companion = _spawn(dict(os.environ))
    try:
        time.sleep(0.5)
        assert _alive(companion)
        middle.kill()
        middle.wait()
        deadline = time.monotonic() + 10
        while _alive(companion) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(companion), "the companion outlived its killed client"
    finally:
        if _alive(companion):
            os.kill(companion, 9)


def test_a_console_script_launcher_is_recognised_without_its_exe():
    # pip's launcher script sets argv[0] to the script path minus ".exe".
    scripts = os.path.join("venv", "Scripts")
    found = lifecycle.launcher_images(
        executable=os.path.join(scripts, "python.exe"),
        argv0=os.path.join(scripts, "battlemap-mcp"),
        base=os.path.join("Python312", "python.exe"),
    )
    assert lifecycle._image_key(os.path.join(scripts, "battlemap-mcp.exe")) in found
    assert lifecycle._image_key(os.path.join(scripts, "python.exe")) in found


def test_a_frozen_companion_has_no_launcher():
    exe = os.path.join("Apps", "battlemap-mcp.exe")
    assert lifecycle.launcher_images(executable=exe, argv0=exe, base=exe) == set()


def test_the_watchdog_can_be_turned_off():
    env = dict(os.environ, BATTLEMAP_MCP_PARENT_WATCHDOG="0")
    middle, companion = _spawn(env)
    try:
        middle.kill()
        middle.wait()
        time.sleep(1.0)
        assert _alive(companion), "turned off, yet the companion still exited"
    finally:
        if _alive(companion):
            os.kill(companion, 9)
