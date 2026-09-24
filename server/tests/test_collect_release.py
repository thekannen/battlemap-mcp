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


def collect(source, output, *extra):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            str(output),
            "--version",
            "0.2.0",
            *extra,
        ],
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


def test_platform_subset_collects_only_those_companions(tmp_path):
    """The public workflow builds Windows and Linux; signed macOS companions
    are attached by hand, so they must not be required here."""
    source = fixture_artifacts(tmp_path)
    output = tmp_path / "release"
    result = collect(source, output, "--platform", "windows-x64", "--platform", "linux-x64")
    assert result.returncode == 0, result.stderr
    names = sorted(p.name for p in output.iterdir())
    assert not [n for n in names if "macos" in n]
    assert len(names) == 5
    sums = (output / "SHA256SUMS").read_text()
    assert "windows-x64" in sums and "linux-x64" in sums and "macos" not in sums


# --- the release page's "What's new" -----------------------------------------

CHANGELOG = """# Changelog

## Unreleased

**Not yet.** Work in progress.

## 0.2.0 — 2026-09-24

Fixes for maps and water.

**Resized maps open again.** Long explanation that wraps
over two lines.

**Water keeps its colour.** More.

## 0.1.0 — 2026-09-01

**Older.** Not this release.
"""


def _summary(tmp_path, changelog=CHANGELOG, version="0.2.0", out=None):
    log = tmp_path / "CHANGELOG.md"
    log.write_text(changelog, encoding="utf-8")
    out = out or tmp_path / "notes" / "summary.md"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(fixture_artifacts(tmp_path)),
            str(tmp_path / "release"),
            "--version",
            version,
            "--changelog",
            str(log),
            "--summary-out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    return result, out


def test_the_summary_is_this_versions_intro_and_bold_leads(tmp_path):
    result, out = _summary(tmp_path)
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == (
        "## What's new in 0.2.0\n\n"
        "Fixes for maps and water.\n\n"
        "- Resized maps open again.\n"
        "- Water keeps its colour.\n"
    )
    # A notes file must never become a download.
    assert not (tmp_path / "release" / "summary.md").exists()


def test_a_version_without_a_changelog_section_is_refused(tmp_path):
    result, _ = _summary(tmp_path, changelog=CHANGELOG.replace("## 0.2.0", "## 0.2.9"))
    assert result.returncode != 0
    assert "no '## 0.2.0' section" in result.stderr


def test_the_summary_may_not_land_among_the_assets(tmp_path):
    result, _ = _summary(tmp_path, out=tmp_path / "release" / "summary.md")
    assert result.returncode != 0
    assert "outside the asset directory" in result.stderr
