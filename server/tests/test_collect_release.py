"""The release job must assemble exactly the tested platform artifacts."""

import hashlib
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "collect_release.py"
PLATFORMS = ("windows-x64", "macos-x64", "macos-arm64", "linux-x64")


def fixture_artifacts(tmp_path):
    source = tmp_path / "inputs"
    for platform in PLATFORMS:
        folder = source / platform
        folder.mkdir(parents=True)
        ext = "zip" if platform.startswith("windows") else "tar.gz"
        (folder / f"battlemap-mcp-companion-0.2.0-{platform}.{ext}").write_bytes(platform.encode())
    common = source / "linux-x64"
    (common / "battlemap-mcp-mod-0.2.0.zip").write_bytes(b"mod")
    (common / "battlemap_mcp-0.2.0-py3-none-any.whl").write_bytes(b"wheel")
    return source


def collect(source, output):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), str(output), "--version", "0.2.0"],
        capture_output=True,
        text=True,
    )


def test_assembly_only_includes_named_release_assets_and_hashes(tmp_path):
    source = fixture_artifacts(tmp_path)
    (source / "linux-x64" / "private-notes.txt").write_text("do not publish")
    output = tmp_path / "release"
    result = collect(source, output)
    assert result.returncode == 0, result.stderr
    assert len(list(output.iterdir())) == 7
    for line in (output / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert not (output / "private-notes.txt").exists()


def test_missing_platform_cannot_produce_partial_release(tmp_path):
    source = fixture_artifacts(tmp_path)
    (source / "macos-arm64" / "battlemap-mcp-companion-0.2.0-macos-arm64.tar.gz").unlink()
    output = tmp_path / "release"
    result = collect(source, output)
    assert result.returncode != 0
    assert not output.exists()


def test_existing_output_is_not_reused_or_destroyed(tmp_path):
    source = fixture_artifacts(tmp_path)
    output = tmp_path / "release"
    output.mkdir()
    sentinel = output / "personal.txt"
    sentinel.write_text("keep")
    assert collect(source, output).returncode != 0
    assert sentinel.read_text() == "keep"
