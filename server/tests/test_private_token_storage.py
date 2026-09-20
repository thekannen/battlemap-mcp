"""Exercise the mod's native permission scripts on disposable synthetic files."""

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from battlemap_mcp.installer import payload_root

MOD = payload_root().joinpath("scripts", "tools", "mcp_bridge.gd")


def native_script(name):
    match = re.search(r"var " + name + r' = ("(?:[^"\\]|\\.)*")', MOD.read_text())
    assert match is not None
    return json.loads(match.group(1))


def harden_result(path, reset=False):
    if sys.platform in ("darwin", "linux"):
        name = "mac_script" if sys.platform == "darwin" else "linux_script"
        args = ["-c", native_script(name), "--", str(path), str(int(reset))]
        # Execute through the same extra shell layer Godot 3 uses.
        helper = re.search(r"func _unix_execute\(.*?(?=\nfunc )", MOD.read_text(), re.S)
        for before, after in re.findall(
            r'\.replace\(("(?:[^"\\]|\\.)*"), ("(?:[^"\\]|\\.)*")\)', helper.group(0)
        ):
            args = [arg.replace(json.loads(before), json.loads(after)) for arg in args]
        command = '"/bin/sh"' + "".join(' "' + arg + '"' for arg in args)
        argv = ["/bin/sh", "-c", command]
    elif sys.platform == "win32":
        encoded_path = base64.b64encode(str(path).encode()).decode()
        source = (
            "$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
            + encoded_path
            + "'));$reset="
            + ("$true;" if reset else "$false;")
            + native_script("acl_script")
        )
        argv = [
            str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(source.encode("utf-16-le")).decode(),
        ]
    else:
        pytest.skip("requires a supported native platform")
    return subprocess.run(argv, capture_output=True, timeout=30)


def harden(path, reset=False):
    return harden_result(path, reset).returncode


def windows_acl(path):
    encoded = base64.b64encode(str(path).encode()).decode()
    script = (
        "$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
        + encoded
        + "'));$a=(Get-Item -Force -LiteralPath $p).GetAccessControl();"
        "$me=[System.Security.Principal.WindowsIdentity]::GetCurrent().User;"
        "@{protected=$a.AreAccessRulesProtected;rules=@($a.GetAccessRules("
        "$true,$true,[System.Security.Principal.SecurityIdentifier]) | ForEach-Object {"
        "@{current_user=($_.IdentityReference -eq $me);"
        "allow=($_.AccessControlType -eq 'Allow');rights=[int]$_.FileSystemRights;"
        "inherit=[int]$_.InheritanceFlags;inherited=$_.IsInherited}})} | ConvertTo-Json -Depth 4"
    )
    result = subprocess.run(
        [
            str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def storage(tmp_path):
    root = tmp_path.resolve() / "storage"
    root.mkdir()
    return root / "token"


def test_create_and_recheck_private_storage(tmp_path):
    token = storage(tmp_path)
    assert harden(token, reset=True) == 0
    token.write_text("synthetic-secret")
    assert harden(token) == 0
    assert token.read_text() == "synthetic-secret"
    if sys.platform == "darwin":
        assert token.stat().st_mode & 0o777 == 0o600
        assert token.parent.stat().st_mode & 0o777 == 0o700


def test_creates_private_directory_without_changing_ancestors_or_dd(tmp_path):
    root = tmp_path.resolve()
    dd = root / "Dungeondraft"
    dd.mkdir()
    (dd / "config.ini").write_text("unchanged")
    token = root / "battlemap-mcp" / "token"
    before = windows_acl(root) if sys.platform == "win32" else root.stat().st_mode
    dd_before = windows_acl(dd) if sys.platform == "win32" else dd.stat().st_mode
    result = harden_result(token, reset=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert token.is_file()
    assert (dd / "config.ini").read_text() == "unchanged"
    assert (windows_acl(root) if sys.platform == "win32" else root.stat().st_mode) == before
    assert (windows_acl(dd) if sys.platform == "win32" else dd.stat().st_mode) == dd_before


def test_verification_does_not_create_private_directory(tmp_path):
    token = tmp_path.resolve() / "absent" / "token"
    assert harden(token) != 0
    assert not token.parent.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
def test_refuse_junction_ancestor_before_creating_storage(tmp_path):
    real = tmp_path.resolve() / "real"
    real.mkdir()
    alias = tmp_path.resolve() / "alias"

    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"

    source = f"New-Item -ItemType Junction -Path {quote(alias)} -Value {quote(real)} | Out-Null"
    subprocess.run(
        [
            str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(source.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    before = windows_acl(real)
    assert harden(alias / "battlemap-mcp" / "token", reset=True) != 0
    assert not (real / "battlemap-mcp").exists()
    assert windows_acl(real) == before


def test_rotation_does_not_write_into_an_old_open_handle(tmp_path):
    token = storage(tmp_path)
    token.write_text("old-synthetic")
    token.chmod(0o666)
    token.parent.chmod(0o777)
    with token.open() as old:
        result = harden(token, reset=True)
        if sys.platform == "win32" and result != 0:
            assert old.read() == "old-synthetic"
            assert token.read_text() == "old-synthetic"
            return  # Windows sharing modes can safely refuse replacement.
        assert result == 0
        token.write_text("new-synthetic")
        assert old.read() == "old-synthetic"
    assert token.read_text() == "new-synthetic"


@pytest.mark.parametrize("kind", ["symlink", "dangling", "directory", "hardlink"])
def test_refuse_redirected_or_nonregular_storage(tmp_path, kind):
    token = storage(tmp_path)
    target = tmp_path.resolve() / "target"
    if kind != "dangling":
        target.write_text("do not change")
    try:
        if kind in ("symlink", "dangling"):
            token.symlink_to(target)
        elif kind == "hardlink":
            os.link(target, token)
        else:
            token.mkdir()
    except OSError:
        pytest.skip("platform does not permit this link type")
    assert harden(token, reset=True) != 0
    if kind == "dangling":
        assert not target.exists()
    else:
        assert target.read_text() == "do not change"


def test_refuse_redirected_parent(tmp_path):
    real = tmp_path.resolve() / "real"
    real.mkdir()
    alias = tmp_path.resolve() / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("platform does not permit directory links")
    assert harden(alias / "token", reset=True) != 0
    assert not (real / "token").exists()


def test_missing_storage_is_not_recreated_during_verification(tmp_path):
    token = storage(tmp_path)
    assert harden(token) != 0
    assert not token.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS native ACLs")
def test_macos_removes_explicit_public_read_acl(tmp_path):
    token = storage(tmp_path)
    token.write_text("old-synthetic")
    for path in (token.parent, token):
        subprocess.run(["/bin/chmod", "+a", "everyone allow read", str(path)], check=True)
    assert harden(token, reset=True) == 0
    for path in (token.parent, token):
        result = subprocess.run(["/bin/ls", "-lde", str(path)], capture_output=True, text=True)
        assert "everyone" not in result.stdout
    assert token.stat().st_mode & 0o777 == 0o600
    assert token.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS path metacharacters")
def test_mac_path_is_literal_shell_data(tmp_path):
    token = storage(tmp_path).with_name('token " $(touch INJECTED) `touch INJECTED` é')
    assert harden(token, reset=True) == 0
    assert token.is_file()
    assert not (Path.cwd() / "INJECTED").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS native diagnostics")
@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("directory", "regular file"),
        ("hardlink", "hard link"),
        ("symlink", "symlink"),
        ("parent", "ancestor"),
        ("missing", "missing token"),
    ],
)
def test_macos_storage_failure_is_actionable(tmp_path, kind, reason):
    token = storage(tmp_path)
    target = tmp_path.resolve() / "target"
    target.write_text("unchanged synthetic value")
    if kind == "directory":
        token.mkdir()
    elif kind == "hardlink":
        os.link(target, token)
    elif kind == "symlink":
        token.symlink_to(target)
    elif kind == "parent":
        alias = tmp_path.resolve() / "alias"
        alias.symlink_to(token.parent, target_is_directory=True)
        token = alias / "token"
    result = harden_result(token, reset=kind != "missing")
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert b"token storage:" in output
    assert reason.encode() in output
    assert b"unchanged synthetic value" not in output
    assert target.read_text() == "unchanged synthetic value"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS native ACLs")
def test_macos_preserves_ancestor_and_dungeondraft_acls(tmp_path):
    root = tmp_path.resolve()
    dd = root / "Dungeondraft"
    dd.mkdir()
    config = dd / "config.ini"
    config.write_text("synthetic configuration")
    protected = [root, dd, config]
    for path in protected:
        subprocess.run(["/bin/chmod", "+a", "everyone allow read", str(path)], check=True)

    def permissions(path):
        acl = subprocess.check_output(["/bin/ls", "-lde", str(path)], text=True)
        return path.stat().st_mode, path.stat().st_uid, acl.splitlines()[1:]

    before = [permissions(path) for path in protected]
    token = root / "battlemap-mcp" / "token"
    assert harden(token, reset=True) == 0
    assert token.stat().st_uid == os.getuid()
    assert token.parent.stat().st_uid == os.getuid()
    assert [permissions(path) for path in protected] == before
    assert config.read_text() == "synthetic configuration"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS native owner checks")
@pytest.mark.parametrize("entry", ["parent", "p"])
def test_macos_owner_mismatch_refuses_before_mutation(tmp_path, monkeypatch, entry):
    token = storage(tmp_path)
    token.write_text("unchanged synthetic token")
    before = [(p.stat().st_mode, p.stat().st_ino) for p in (token.parent, token)]
    original = native_script("mac_script")
    check = f'test "$(/usr/bin/stat -f %u "${entry}")" = "$(/usr/bin/id -u)"'
    check = ("\n" if entry == "parent" else "\n ") + check
    assert original.count(check) == 1
    # Read the real native owner, but inject a different expected identity. This
    # tests refusal without needing root to create a foreign-owned fixture.
    injected = original.replace(check, check.replace('"$(/usr/bin/id -u)"', '"-1"'))
    monkeypatch.setitem(harden_result.__globals__, "native_script", lambda _name: injected)
    result = harden_result(token, reset=True)
    assert result.returncode != 0
    assert b"owner mismatch" in result.stdout + result.stderr
    assert [(p.stat().st_mode, p.stat().st_ino) for p in (token.parent, token)] == before
    assert token.read_text() == "unchanged synthetic token"


@pytest.mark.parametrize("failure", ["none", "open", "write", "readback", "permissions", "type"])
def test_token_persistence_in_isolated_engine(tmp_path, failure):
    executable = os.environ.get("DUNGEONDRAFT_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("set DUNGEONDRAFT_TEST_EXECUTABLE for an isolated SceneTree harness")
    source = MOD.read_text()
    funcs = []
    for name in ("_ensure_token", "_unix_execute", "_powershell_token_check", "_harden_token_file"):
        match = re.search(r"func " + name + r"\(.*?(?=\nfunc |\n# ---)", source, re.S)
        assert match is not None
        funcs.append(match.group(0))
    token = tmp_path.resolve() / "storage" / "token"
    if failure == "type":
        if sys.platform not in ("win32", "darwin"):
            pytest.skip("Windows/macOS permission diagnostics")
        token.mkdir(parents=True)
    elif failure != "none":
        # Inject I/O outcomes into the actual startup function, not a Python
        # reimplementation of it. No real token or user directory is accessed.
        funcs[0] = funcs[0].replace("File.new()", "FailingFile.new()")
        funcs[-1] = "func _harden_token_file(reset = false):\n\treturn " + (
            "false\n" if failure == "permissions" else "true\n"
        )
    fake = """
class FailingFile:
    func open(_path, _mode):
        return ERR_CANT_OPEN if OS.get_environment("TOKEN_TEST_FAILURE") == "open" else OK
    func store_string(_value):
        pass
    func flush():
        pass
    func get_error():
        return ERR_FILE_CANT_WRITE if OS.get_environment("TOKEN_TEST_FAILURE") == "write" else OK
    func close():
        pass
    func get_as_text():
        return "incorrect-persisted-value"
"""
    harness = tmp_path / "token_probe.gd"
    harness.write_text(
        'extends SceneTree\nconst TOKEN_FILE = "storage/token"\n'
        + fake
        + '\nfunc _token_path():\n\treturn OS.get_environment("TOKEN_TEST_PATH")\n\n'
        + "\n".join(funcs)
        + "\nfunc _init():\n\tvar secret = _ensure_token()\n"
        + (
            "\tquit(0 if secret.length() == 64 else 1)\n"
            if failure == "none"
            else '\tquit(0 if secret == "" else 1)\n'
        )
    )
    result = subprocess.run(
        [executable, "--no-window", "--script", str(harness)],
        cwd=tmp_path,
        env={**os.environ, "TOKEN_TEST_PATH": str(token), "TOKEN_TEST_FAILURE": failure},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if failure == "none":
        assert len(token.read_text()) == 64
        assert harden(token) == 0
    elif failure == "type":
        assert token.is_dir()
        output = result.stdout + result.stderr
        expected = b"type" if sys.platform == "win32" else b"token must be a regular file"
        assert b"[mcp-bridge] token storage:" in output
        assert expected in output
    else:
        assert not token.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native ACL inheritance")
def test_windows_removes_permissive_inheritance(tmp_path):
    token = storage(tmp_path)
    icacls = str(Path(os.environ["SystemRoot"]) / "System32/icacls.exe")
    result = subprocess.run(
        [icacls, str(token.parent), "/grant", "*S-1-1-0:(OI)(CI)F"],
        capture_output=True,
    )
    assert result.returncode == 0, "could not prepare synthetic permissive inheritance"
    token.write_text("old-synthetic")
    assert harden(token, reset=True) == 0
    token.write_text("new-synthetic")
    assert harden(token) == 0
    assert token.read_text() == "new-synthetic"
    for path, inheritance in ((token, 0), (token.parent, 3)):
        acl = windows_acl(path)
        assert acl["protected"]
        assert acl["rules"] == [
            {
                "current_user": True,
                "allow": True,
                "rights": 2032127,  # FullControl
                "inherit": inheritance,
                "inherited": False,
            }
        ]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native ACL inheritance")
def test_windows_keeps_inherited_sibling_access(tmp_path):
    token = storage(tmp_path)
    siblings = [token.parent / name for name in ("logs", "mods", "mcp_output")]
    for sibling in siblings:
        sibling.mkdir()
        (sibling / "existing.txt").write_text("keep accessible")
    result = harden_result(token, reset=True)
    # Check side effects even when hardening reports failure: Set-Acl used to
    # remove the inherited grants before throwing its privilege error.
    for sibling in siblings:
        assert any(
            rule["current_user"] and rule["allow"] and rule["inherited"]
            for rule in windows_acl(sibling)["rules"]
        )
        assert (sibling / "existing.txt").read_text() == "keep accessible"
        (sibling / "new.txt").write_text("still writable")
        nested = sibling / "nested"
        nested.mkdir()
        (nested / "new.txt").write_text("inherits through directories")
    assert result.returncode == 0, result.stdout + result.stderr
    assert harden(token) == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows permission diagnostics")
def test_windows_reports_storage_failure_reason(tmp_path):
    token = storage(tmp_path)
    token.mkdir()
    result = harden_result(token, reset=True)
    assert result.returncode != 0
    assert b"type" in result.stdout.lower()
