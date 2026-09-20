"""Execute the mod's actual Linux permission command against disposable files."""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="requires Linux native tools")


def harden(path):
    source = (
        Path(__file__).resolve().parents[2] / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    ).read_text()
    match = re.search(r'var linux_script = ("(?:[^"\\]|\\.)*")', source)
    assert match, "Linux token hardening is missing"
    script = json.loads(match.group(1))
    args = ["-c", script, "--", str(path)]
    # Godot 3.4.2's blocking Unix execute uses popen, wrapping each argument
    # in double quotes without escaping it. Exercise that extra shell layer.
    helper = re.search(r"func _unix_execute\(.*?(?=\nfunc )", source, re.S)
    if helper:
        replacements = re.findall(
            r'\.replace\(("(?:[^"\\]|\\.)*"), ("(?:[^"\\]|\\.)*")\)',
            helper.group(0),
        )
        for before, after in replacements:
            args = [arg.replace(json.loads(before), json.loads(after)) for arg in args]
    command = '"/bin/sh"' + "".join(' "' + arg + '"' for arg in args)
    return subprocess.run(["/bin/sh", "-c", command], check=False).returncode


def test_linux_hardening_makes_public_token_private(tmp_path):
    token = tmp_path / "token ' with spaces;$(false)"
    token.write_text("synthetic")
    token.chmod(0o666)
    assert harden(token) == 0
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert token.read_text() == "synthetic"


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "missing"])
def test_linux_hardening_rejects_non_regular_storage(tmp_path, kind):
    token = tmp_path / "token"
    target = tmp_path / "target"
    target.write_text("synthetic")
    target.chmod(0o644)
    if kind == "symlink":
        token.symlink_to(target)
    elif kind == "directory":
        token.mkdir()
    elif kind == "fifo":
        os.mkfifo(token)
    assert harden(token) != 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_linux_hardening_rejects_foreign_owner(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("requires root to create a foreign-owned fixture")
    token = tmp_path / "token"
    token.write_text("synthetic")
    os.chown(token, 65534, -1)
    assert harden(token) != 0


def test_linux_hardening_in_actual_engine(tmp_path):
    executable = os.environ.get("DUNGEONDRAFT_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("set DUNGEONDRAFT_TEST_EXECUTABLE to run the purchased engine")
    source = (
        Path(__file__).resolve().parents[2] / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    ).read_text()
    helper = re.search(r"func _unix_execute\(.*?(?=\nfunc )", source, re.S).group(0)
    hardening = re.search(r"func _harden_token_file\(.*?(?=\nfunc )", source, re.S).group(0)
    token = tmp_path / 'token " $HOME `false` \\ with spaces'
    token.write_text("synthetic")
    token.chmod(0o666)
    harness = tmp_path / "permission_probe.gd"
    harness.write_text(
        "extends SceneTree\n\n"
        + helper
        + "\n"
        + re.search(r"func _powershell_token_check\(.*?(?=\nfunc )", source, re.S).group(0)
        + hardening
        + "\nfunc _token_path():\n\treturn "
        + json.dumps(str(token))
        + "\n\nfunc _init():\n\tquit(0 if _harden_token_file() else 1)\n"
    )
    result = subprocess.run(
        [executable, "--no-window", "--script", str(harness)],
        cwd=Path(executable).parent,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert token.read_text() == "synthetic"
