"""Capture installed distribution metadata and supplied legal notices."""

import importlib.metadata
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
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
        if any(
            part.lower().startswith(("license", "copying", "notice"))
            for part in file.parts
        ):
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
