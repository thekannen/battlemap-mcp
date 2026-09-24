"""Assemble the native jobs' named assets and an aggregate checksum file.

By default every platform must be present. `--platform` narrows the set to the
platforms a workflow builds; the rest (signed macOS companions) are attached
to the draft release by hand, with SHA256SUMS regenerated then.

`--changelog` with `--summary-out` also writes a short "What's new" for the
release page from this version's CHANGELOG.md section: its opening line and
one bullet per bold lead. The file goes outside the asset directory, so it
is never uploaded as a download.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from pathlib import Path

PLATFORMS = ("windows-x64", "macos-x64", "macos-arm64", "linux-x64")


def collect(
    source: Path, output: Path, version: str, platforms: tuple[str, ...] = PLATFORMS
) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected a numeric major.minor.patch version")
    if output.exists():
        raise ValueError("Output must be a new directory, not an existing release")
    unknown = set(platforms) - set(PLATFORMS)
    if unknown or not platforms:
        raise ValueError(f"Unknown or empty platform list: {sorted(unknown)}")
    assets = [
        source / "linux-x64" / f"battlemap-mcp-mod-{version}.zip",
        source / "linux-x64" / f"battlemap_mcp-{version}-py3-none-any.whl",
    ]
    for platform in platforms:
        ext = "zip" if platform.startswith("windows") else "tar.gz"
        assets.append(
            source / platform / f"battlemap-mcp-companion-{version}-{platform}.{ext}"
        )
    for asset in assets:
        if not asset.is_file() or asset.is_symlink():
            raise ValueError(f"Missing regular release asset: {asset}")
        if not asset.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Release asset escapes input directory: {asset}")
    output.mkdir(parents=True)
    checksums = []
    for asset in sorted(assets):
        target = output / asset.name
        shutil.copyfile(asset, target)
        checksums.append(
            f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target.name}\n"
        )
    (output / "SHA256SUMS").write_text(
        "".join(checksums), encoding="utf-8", newline="\n"
    )


def summary(changelog: str, version: str) -> str:
    """The release page's "What's new" for `version`, from its CHANGELOG section.

    Refuses a missing or undated section, so a release cannot go out with the
    notes of the previous one or of "Unreleased".
    """
    heading = re.compile(rf"^## {re.escape(version)}(?: .*)?$", re.MULTILINE)
    found = heading.search(changelog)
    if found is None:
        raise ValueError(f"CHANGELOG.md has no '## {version}' section")
    body = changelog[found.end() :]
    following = re.search(r"^## ", body, re.MULTILINE)
    section = body[: following.start()] if following else body
    paragraphs = [p.strip() for p in section.strip().split("\n\n") if p.strip()]
    intro = [p for p in paragraphs if not p.startswith("**")][:1]
    leads = [
        m.group(1).strip()
        for p in paragraphs
        if (m := re.match(r"\*\*(.+?)\*\*", p)) is not None
    ]
    if not leads:
        raise ValueError(f"CHANGELOG.md's {version} section has no bold entries")
    lines = [f"## What's new in {version}", ""]
    if intro:
        lines += [" ".join(intro[0].split()), ""]
    lines += [f"- {lead}" for lead in leads]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--platform",
        action="append",
        choices=PLATFORMS,
        help="include only these companions (repeatable); default: all",
    )
    parser.add_argument("--changelog", type=Path, help="CHANGELOG.md to summarise")
    parser.add_argument("--summary-out", type=Path, help="where to write the summary")
    args = parser.parse_args()
    if (args.changelog is None) != (args.summary_out is None):
        parser.error("--changelog and --summary-out go together")
    if args.summary_out is not None and args.summary_out.resolve().is_relative_to(
        args.output.resolve()
    ):
        parser.error("--summary-out must be outside the asset directory")
    collect(args.source, args.output, args.version, tuple(args.platform or PLATFORMS))
    if args.changelog is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            summary(args.changelog.read_text(encoding="utf-8"), args.version),
            encoding="utf-8",
            newline="\n",
        )
