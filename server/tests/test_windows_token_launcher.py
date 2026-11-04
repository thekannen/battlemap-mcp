"""Exercise the actual Godot/GUI-host path, with disposable reports and scripts."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOD = ROOT / "mod/battlemap-mcp-bridge"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI process launch")
@pytest.mark.parametrize(
    ("script", "expected", "diagnostic"),
    [
        ("exit 0", 0, ""),
        ("Write-Output 'synthetic failure';exit 1", 1, "synthetic failure"),
        ("Write-Output 'not a success proof';exit 1", 1, "not a success proof"),
    ],
)
def test_hidden_launcher_preserves_outcome_and_diagnostics(tmp_path, script, expected, diagnostic):
    executable = os.environ.get("DUNGEONDRAFT_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("set DUNGEONDRAFT_TEST_EXECUTABLE for an isolated SceneTree harness")
    source = (MOD / "scripts/tools/mcp_bridge.gd").read_text()
    helper = re.search(r"func _powershell_token_check\(.*?(?=\nfunc )", source, re.S).group(0)
    # Keep all reports in this test's directory; never touch real bridge state.
    helper = helper.replace("OS.get_user_data_dir()", json.dumps(str(tmp_path)))
    harness = tmp_path / "launcher_probe.gd"
    harness.write_text(
        'extends SceneTree\nvar Global = {"Root": '
        + json.dumps(str(MOD))
        + "}\n"
        + helper
        + "\nfunc _init():\n\tvar result = _powershell_token_check("
        + json.dumps(script)
        + ', "unused synthetic path", false)\n\tquit(0 if result == '
        + str(expected)
        + " else 1)\n"
    )
    result = subprocess.run(
        [executable, "--no-window", "--script", str(harness)],
        cwd=Path(executable).parent,
        capture_output=True,
        text=True,
        timeout=40,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if diagnostic:
        assert diagnostic in result.stdout + result.stderr
    assert not list(tmp_path.glob("mcp-token-check-*.txt"))


def test_release_ships_the_gui_launcher():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import release

        assert "windows_token_check.js" in release.MOD_FILES
    finally:
        sys.path.pop(0)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI process launch")
@pytest.mark.parametrize("failure", ["missing", "timeout", "forged"])
def test_launcher_failures_never_accept_a_token(tmp_path, failure):
    executable = os.environ.get("DUNGEONDRAFT_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("set DUNGEONDRAFT_TEST_EXECUTABLE for an isolated SceneTree harness")
    source = (MOD / "scripts/tools/mcp_bridge.gd").read_text()
    helper = re.search(r"func _powershell_token_check\(.*?(?=\nfunc )", source, re.S).group(0)
    report = tmp_path / "untrusted-report.txt"
    helper = re.sub(
        r"var report_path = .*", lambda _: "var report_path = " + json.dumps(str(report)), helper
    )
    helper = helper.replace("+ 30000", "+ 300" if failure == "timeout" else "+ 5000")
    launcher = tmp_path / "windows_token_check.js"
    if failure == "timeout":
        launcher.write_text("WScript.Sleep(10000);")
    elif failure == "forged":
        launcher.write_text(
            'var file = new ActiveXObject("Scripting.FileSystemObject").CreateTextFile('
            + json.dumps(str(report))
            + ', false); file.Write("forged success"); file.Close(); WScript.Sleep(10000);'
        )
    harness = tmp_path / "failure_probe.gd"
    harness.write_text(
        'extends SceneTree\nvar Global = {"Root": '
        + json.dumps(str(tmp_path))
        + "}\n"
        + helper
        + '\nfunc _init():\n\tvar result = _powershell_token_check("exit 0", "unused", false)\n'
        + "\tquit(0 if result != 0 else 1)\n"
    )
    result = subprocess.run(
        [executable, "--no-window", "--script", str(harness)],
        cwd=Path(executable).parent,
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if failure == "forged":
        assert "invalid Windows token-check report" in result.stdout + result.stderr
        assert "forged success" not in result.stdout + result.stderr
    else:
        assert not report.exists()
