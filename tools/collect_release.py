"""Assemble the native jobs' named assets and an aggregate checksum file.

By default every platform must be present. `--platform` narrows the set to the
platforms a workflow builds; the rest (signed macOS companions) are attached
to the draft release by hand, with SHA256SUMS regenerated then.
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
    args = parser.parse_args()
    collect(args.source, args.output, args.version, tuple(args.platform or PLATFORMS))
