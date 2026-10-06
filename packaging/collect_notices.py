"""Capture installed distribution metadata and supplied legal notices."""

import importlib.metadata
import json
import sys
from pathlib import Path, PurePath

LEGAL_PREFIXES = ("license", "copying", "notice")
# Code is never a notice. hatchling, packaging and pip each ship a Python
# package named `licenses`, and matching on any path part copied its sources
# and their __pycache__ into every companion: bytecode that differs per build.
CODE_SUFFIXES = (".py", ".pyc", ".pyi", ".pyd", ".so")


def is_notice(file: PurePath) -> bool:
    """A legal text: named like one, or in a PEP 639 dist-info licenses folder."""
    if file.suffix.lower() in CODE_SUFFIXES or "__pycache__" in file.parts:
        return False
    if file.name.lower().startswith(LEGAL_PREFIXES):
        return True
    parts = [part.lower() for part in file.parts]
    return any(
        part.endswith(".dist-info") and parts[index + 1 : index + 2] == ["licenses"]
        for index, part in enumerate(parts)
    )


def main(out: Path) -> None:
    records = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        record = {
            "name": name,
            "version": dist.version,
            "license": dist.metadata.get("License-Expression")
            or dist.metadata.get("License"),
            "notices": [],
        }
        for file in dist.files or []:
            if is_notice(file):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = out / "THIRD_PARTY_NOTICES" / name / Path(*file.parts[-2:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
                    record["notices"].append(target.relative_to(out).as_posix())
        records.append(record)
    (out / "DEPENDENCIES.json").write_text(
        json.dumps(sorted(records, key=lambda r: r["name"].lower()), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
