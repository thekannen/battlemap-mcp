"""Release artifacts must contain only the intended, matching payload."""

import importlib.util
import json
import shutil
import subprocess
import sysconfig
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def release_module():
    path = ROOT / "tools/release.py"
    assert path.is_file(), "release builder is required"
    spec = importlib.util.spec_from_file_location("release_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checkout(tmp_path):
    for name in (
        "server/pyproject.toml",
        "server/battlemap_mcp/__init__.py",
        ".claude-plugin/plugin.json",
        "LICENSE",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copytree(ROOT / "mod", tmp_path / "mod")
    return tmp_path


def test_version_bump_and_tag_validation(checkout):
    release = release_module()
    release.set_version(checkout, "1.2.3")
    assert release.check_versions(checkout, "v1.2.3") == "1.2.3"
    with pytest.raises(ValueError, match="tag"):
        release.check_versions(checkout, "v1.2.4")
    manifest = checkout / ".claude-plugin/plugin.json"
    data = json.loads(manifest.read_text())
    data["version"] = "1.0.0"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="version"):
        release.check_versions(checkout)


def test_mod_archive_has_exact_payload_bytes(checkout, tmp_path):
    release = release_module()
    archive = release.build_mod(checkout, tmp_path / "out", "0.2.0")
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {
            "battlemap-mcp-bridge/mcp_bridge.ddmod",
            "battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd",
            "battlemap-mcp-bridge/LICENSE",
            "battlemap-mcp-bridge/icons/mcp_bridge.png",
        }
        for name in release.MOD_FILES:
            assert (
                zipped.read("battlemap-mcp-bridge/" + name)
                == (checkout / "mod/battlemap-mcp-bridge" / name).read_bytes()
            )


def test_unexpected_mod_file_rejected(checkout, tmp_path):
    release = release_module()
    (checkout / "mod/battlemap-mcp-bridge/private.log").write_text("secret")
    with pytest.raises(ValueError, match="Unexpected"):
        release.build_mod(checkout, tmp_path / "out", "0.2.0")


def test_symlink_payload_rejected(checkout, tmp_path):
    release = release_module()
    script = checkout / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    script.unlink()
    try:
        script.symlink_to(checkout / "LICENSE")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink creation not permitted")
        raise
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        release.build_mod(checkout, tmp_path / "out", "0.2.0")


def test_required_manifest_missing_rejected(checkout):
    release = release_module()
    (checkout / "mod/battlemap-mcp-bridge/mcp_bridge.ddmod").unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        release.check_versions(checkout)


def test_prerelease_not_silently_normalized(checkout):
    release = release_module()
    with pytest.raises(ValueError, match="version"):
        release.set_version(checkout, "1.2.3-alpha")


def test_unexpected_skills_rejected(tmp_path):
    release = release_module()
    (tmp_path / "secrets.txt").write_text("private")
    with pytest.raises(ValueError, match="Unexpected"):
        release.validate_tree(tmp_path, release.SKILL_FILES)


def test_crlf_mod_source_is_rejected(checkout, tmp_path):
    """v1.0.0's Windows companion bundled a CRLF bridge from its runner's
    checkout while the mod ZIP, built on Linux, stayed LF. The smoke test
    compared the payload with the same CRLF checkout, so nothing noticed."""
    release = release_module()
    script = checkout / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    script.write_bytes(script.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ValueError, match="line endings"):
        release.build_mod(checkout, tmp_path / "out", "0.2.0")


def test_crlf_skill_source_is_rejected(tmp_path):
    release = release_module()
    for name in release.SKILL_FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"skill\n")
    (tmp_path / release.SKILL_FILES[0]).write_bytes(b"skill\r\n")
    with pytest.raises(ValueError, match="line endings"):
        release.require_lf(tmp_path, release.SKILL_FILES)
    (tmp_path / release.SKILL_FILES[0]).write_bytes(b"skill\n")
    release.require_lf(tmp_path, release.SKILL_FILES)


def test_payload_sources_check_out_with_lf_on_every_host():
    """Git must not convert the bridge or skills on a Windows runner."""
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    release = release_module()
    paths = [f"mod/{release.MOD_ROOT}/{name}" for name in release.MOD_TEXT_FILES]
    paths += [f"skills/{name}" for name in release.SKILL_FILES]
    completed = subprocess.run(
        [git, "-C", str(ROOT), "check-attr", "eol", "--", *paths],
        capture_output=True,
        check=True,
        text=True,
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == len(paths)
    assert all(line.endswith(": eol: lf") for line in lines), completed.stdout
    # The panel icon's PNG header holds a CR byte; conversion would corrupt it.
    icons = [
        f"mod/{release.MOD_ROOT}/{name}"
        for name in release.MOD_FILES
        if name not in release.MOD_TEXT_FILES
    ]
    binary = subprocess.run(
        [git, "-C", str(ROOT), "check-attr", "text", "--", *icons],
        capture_output=True,
        check=True,
        text=True,
    )
    assert all(line.endswith(": text: unset") for line in binary.stdout.splitlines()), binary.stdout


def test_line_ending_attributes_ship_to_users():
    manifest_path = ROOT / "tools" / "public_export_manifest.json"
    if not manifest_path.exists():
        pytest.skip("no export manifest here; this is the published tree")
    assert ".gitattributes" in json.loads(manifest_path.read_text())


def test_companion_archive_rejects_escaping_link(tmp_path):
    release = release_module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    try:
        (bundle / "escape").symlink_to(tmp_path)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink creation not permitted")
        raise
    with pytest.raises(ValueError, match="escape"):
        release.validate_companion_links(bundle)


def test_runtime_license_uses_standard_library_on_linux(tmp_path, monkeypatch):
    release = release_module()
    prefix = tmp_path / "prefix"
    stdlib = prefix / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    license_file = stdlib / "LICENSE.txt"
    license_file.write_text("Python runtime license", encoding="utf-8")
    monkeypatch.setattr(release.sys, "base_prefix", str(prefix))
    monkeypatch.setattr(sysconfig, "get_path", lambda name: str(stdlib))
    assert release.python_runtime_license() == license_file


@pytest.mark.parametrize("name", ["LICENSE.txt", "LICENSE"])
def test_runtime_license_keeps_prefix_layout(tmp_path, monkeypatch, name):
    release = release_module()
    license_file = tmp_path / name
    license_file.write_text("Python license", encoding="utf-8")
    monkeypatch.setattr(release.sys, "base_prefix", str(tmp_path))
    monkeypatch.setattr(sysconfig, "get_path", lambda key: str(tmp_path / "missing"))
    assert release.python_runtime_license() == license_file


def test_runtime_license_missing_fails_closed(tmp_path, monkeypatch):
    release = release_module()
    monkeypatch.setattr(release.sys, "base_prefix", str(tmp_path))
    monkeypatch.setattr(sysconfig, "get_path", lambda key: str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="Python runtime license not found"):
        release.python_runtime_license()


def test_local_artifacts_do_not_block_packaging(checkout, tmp_path):
    """Shell metadata is gitignored, not payload; the panel icon ships."""
    release = release_module()
    base = checkout / "mod/battlemap-mcp-bridge"
    (base / ".DS_Store").write_bytes(b"\x00\x01")
    (base / "scripts/.DS_Store").write_bytes(b"\x00\x01")

    archive = release.build_mod(checkout, tmp_path / "out", "0.2.0")
    with zipfile.ZipFile(archive) as zipped:
        names = set(zipped.namelist())
        icon = zipped.read("battlemap-mcp-bridge/icons/mcp_bridge.png")
    assert names == {
        "battlemap-mcp-bridge/mcp_bridge.ddmod",
        "battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd",
        "battlemap-mcp-bridge/LICENSE",
        "battlemap-mcp-bridge/icons/mcp_bridge.png",
    }
    assert icon == (ROOT / "mod/battlemap-mcp-bridge/icons/mcp_bridge.png").read_bytes()


def test_stray_file_still_rejected_alongside_artifacts(checkout, tmp_path):
    """Tolerating known artifacts must not weaken the allowlist itself."""
    release = release_module()
    base = checkout / "mod/battlemap-mcp-bridge"
    (base / ".DS_Store").write_bytes(b"\x00\x01")
    (base / "private.log").write_text("secret")
    with pytest.raises(ValueError, match="Unexpected"):
        release.build_mod(checkout, tmp_path / "out", "0.2.0")


def test_signing_flags_must_be_paired(checkout, tmp_path, monkeypatch):
    """Half a signing configuration fails before the build, not after it.

    Notarizing an unsigned bundle is accepted and then comes back Invalid, so
    the useful failure is an immediate one. Discovering it after a multi-minute
    build is how people learn to skip signing.
    """
    release = release_module()
    # Signing is macOS-only and refused first elsewhere; test the pairing rule
    # as a Mac would see it, so the test holds on every CI host.
    monkeypatch.setattr(release.platform, "system", lambda: "Darwin")
    for kwargs in (
        {"sign_identity": "Developer ID Application: X"},
        {"notary_profile": "some-profile"},
    ):
        with pytest.raises(ValueError, match="pass both"):
            release.build(checkout, tmp_path / "out", companion=True, **kwargs)


def test_signing_is_refused_off_macos(checkout, tmp_path, monkeypatch):
    """Windows and Linux are deliberately unsigned; asking is an error."""
    release = release_module()
    monkeypatch.setattr(release.platform, "system", lambda: "Windows")
    with pytest.raises(ValueError, match="macOS-only"):
        release.build(
            checkout,
            tmp_path / "out",
            companion=True,
            sign_identity="Developer ID Application: X",
            notary_profile="some-profile",
        )


def test_is_macho_detects_real_binaries(tmp_path):
    """The signer walks the bundle by magic number, not by file extension."""
    release = release_module()
    macho = tmp_path / "binary"
    macho.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 32)
    plain = tmp_path / "notes.txt"
    plain.write_text("not a binary")
    missing = tmp_path / "gone"
    assert release.is_macho(macho) is True
    assert release.is_macho(plain) is False
    assert release.is_macho(missing) is False


def test_changelog_leads_with_the_current_version():
    """A release whose changelog stops at the previous version tells users
    nothing about what they just installed, and nothing else catches it."""
    import re

    from battlemap_mcp import __version__

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## (\d+\.\d+\.\d+)", changelog, flags=re.MULTILINE)
    assert versions, "no version headings in CHANGELOG.md"
    assert versions[0] == __version__, (
        f"changelog starts at {versions[0]}, package is {__version__}"
    )


def test_changelog_ships_to_users():
    """Only checkable where the exporter lives: the published tree has no
    manifest, and the changelog's presence there is the proof anyway."""
    manifest_path = ROOT / "tools" / "public_export_manifest.json"
    if not manifest_path.exists():
        pytest.skip("no export manifest here; this is the published tree")
    assert "CHANGELOG.md" in json.loads(manifest_path.read_text())


def test_intel_macs_pin_cryptography_to_a_version_with_wheels():
    release = release_module()
    assert release.dependency_pins("Darwin", "x86_64") == ["cryptography>=48,<49"]
    assert release.dependency_pins("Darwin", "arm64") == []
    assert release.dependency_pins("Windows", "AMD64") == []
    assert release.dependency_pins("Linux", "x86_64") == []


def test_windows_version_resource_names_the_release():
    """An unlabelled executable scores worse with antivirus heuristics."""
    text = release_module().windows_version_info("1.2.3")
    compile(text, "version_info.txt", "eval")
    assert "filevers=(1, 2, 3, 0)" in text
    assert "StringStruct('ProductVersion', '1.2.3')" in text
    assert "StringStruct('OriginalFilename', 'battlemap-mcp.exe')" in text
    assert "StringStruct('Comments', " in text
    assert "StringStruct('CompanyName', 'Knownframe')" in text


def test_windows_build_carries_icon_and_skips_upx(tmp_path):
    release = release_module()
    args = release.windows_pyinstaller_args(ROOT, tmp_path, "1.2.3")
    icon = args[args.index("--icon") + 1]
    assert icon == ROOT / "packaging/icon.ico"
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"  # ICO header
    assert "--noupx" in args
    assert "filevers=(1, 2, 3, 0)" in args[args.index("--version-file") + 1].read_text()
    (tmp_path / "packaging").mkdir()
    with pytest.raises(ValueError, match="icon missing"):
        release.windows_pyinstaller_args(tmp_path, tmp_path, "1.2.3")


def test_windows_bootloader_compile_refuses_the_stock_bootloader(tmp_path, monkeypatch):
    release = release_module()
    stock = tmp_path / "stock.exe"
    stock.write_bytes(b"stock")
    package = tmp_path / "PyInstaller"
    (package / "bootloader/Windows-64bit-intel").mkdir(parents=True)
    run_exe = package / "bootloader/Windows-64bit-intel/run.exe"
    run_exe.write_bytes(b"stock")
    calls = []
    monkeypatch.setattr(release, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=f"{package}\n"),
    )
    monkeypatch.setattr(
        release, "STOCK_WINDOWS_BOOTLOADER", release.hashlib.sha256(b"stock").hexdigest()
    )
    with pytest.raises(ValueError, match="prebuilt"):
        release.compile_windows_bootloader(ROOT, tmp_path / "python")
    ((args, kwargs),) = calls
    assert "--no-binary" in args and args[-1].lower().startswith("pyinstaller==")
    assert kwargs["env"]["PYINSTALLER_COMPILE_BOOTLOADER"] == "1"

    run_exe.write_bytes(b"compiled")
    assert release.compile_windows_bootloader(ROOT, tmp_path / "python") == (
        release.hashlib.sha256(b"compiled").hexdigest()
    )


def test_every_server_module_is_released_and_exported():
    """A module missing from either list builds nowhere or exports broken."""
    import json

    release = release_module()
    modules = {p.name for p in (ROOT / "server/battlemap_mcp").glob("*.py")}
    assert set(release.SERVER_FILES) == modules
    # The export manifest lives only where the export is made, not in the
    # exported tree, whose own gate runs this test too.
    manifest = ROOT / "tools/public_export_manifest.json"
    if not manifest.exists():
        return
    exported = set(json.loads(manifest.read_text()))
    assert {f"server/battlemap_mcp/{name}" for name in modules} <= exported
