"""Give a map the asset packs it is allowed to use.

The manifest is written into the map FILE rather than onto the live map:
Dungeondraft's own documentation calls `Header` safe to read and dangerous to
modify, so nothing here touches a running editor. The map is prepared on disk
and then opened, which is the same path Dungeondraft takes when it loads any
map someone else made.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

# Fields a manifest entry carries. Read off maps Dungeondraft itself wrote:
# every entry has the first four, and packs that ship colour overrides add the
# fifth. Anything else in pack.json is not part of a map's manifest.
ENTRY_FIELDS = ("name", "id", "version", "author")
OPTIONAL_FIELDS = ("keywords", "allow_3rd_party_mapping_software_to_read", "custom_color_overrides")


def manifest_entry(pack: dict[str, Any]) -> dict[str, Any]:
    """One asset_manifest entry from a pack's own pack.json metadata."""
    entry: dict[str, Any] = {field: pack.get(field, "") for field in ENTRY_FIELDS}
    for field in OPTIONAL_FIELDS:
        if field in pack:
            entry[field] = pack[field]
    return entry


def build_manifest(packs: list[dict[str, Any]], wanted: list[str] | None = None) -> list[dict]:
    """Manifest entries for `wanted` pack ids, or for every pack when None.

    Order follows the installed list so a prepared map is reproducible, and an
    id is never included twice — a duplicate entry is how a map ends up with the
    same pack listed under two versions.
    """
    chosen = []
    seen: set[str] = set()
    for pack in packs:
        pack_id = str(pack.get("id", ""))
        if not pack_id or pack_id in seen:
            continue
        if wanted is not None and pack_id not in wanted:
            continue
        seen.add(pack_id)
        chosen.append(manifest_entry(pack))
    return chosen


def unknown_ids(packs: list[dict[str, Any]], wanted: list[str]) -> list[str]:
    """Requested ids that are not installed — asking for one is a caller error."""
    installed = {str(pack.get("id", "")) for pack in packs}
    return [pack_id for pack_id in wanted if pack_id not in installed]


def merge_manifest(existing: list[dict], adding: list[dict]) -> list[dict]:
    """The packs a prepared map should include: what it already had, plus new ones."""
    merged = [dict(entry) for entry in existing if isinstance(entry, dict)]
    have = {str(entry.get("id", "")) for entry in merged}
    for entry in adding:
        if str(entry.get("id", "")) not in have:
            have.add(str(entry.get("id", "")))
            merged.append(dict(entry))
    return merged


def _publish_new_file(destination: Path, payload: bytes, *, like: Path) -> None:
    """Create `destination` holding `payload`, atomically, never replacing a file.

    Save directories can be shared, so anyone who can write there can plant
    names in advance. A predictable temporary ("<name>.preparing") written with
    `write_text` follows a symlink planted at that name and truncates whatever
    it points at, before any rename happens. So the temporary is created with
    `mkstemp` — an unpredictable name opened O_CREAT|O_EXCL, which refuses an
    existing entry, symlinks included — and written through that descriptor,
    never reopened by path.

    Publishing must not clobber either. `os.replace` overwrites, so a
    destination that appeared after the caller checked would be destroyed. A
    hard link fails if the name exists (POSIX); `os.rename` fails likewise on
    Windows. The copy takes the source map's permission bits, so a map shared
    with other users stays readable by them.
    """
    fd, temporary = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".preparing"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), stat.S_IMODE(like.stat().st_mode))
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            if os.name == "nt":
                os.rename(temporary, destination)
            else:
                os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise ValueError(f"{destination.name} already exists; refusing to replace it") from exc
    finally:
        # Only the file mkstemp created. After a successful hard link this
        # removes the extra name; after a successful rename it is already gone.
        if os.path.lexists(temporary):
            os.unlink(temporary)


def prepare_map_file(source: Path, destination: Path, manifest: list[dict]) -> dict[str, Any]:
    """Write a copy of `source` whose header includes `manifest`.

    Only the header's asset_manifest changes; every other byte of the map is
    carried across untouched, so the geometry, terrain and objects of the map
    being copied are preserved exactly."""
    if source.resolve() == destination.resolve():
        raise ValueError(
            f"refusing to write the prepared map onto its own source ({source.name}); "
            "this prepares a COPY — choose a different filename"
        )
    data = json.loads(source.read_text(encoding="utf-8"))
    header = data.get("header")
    if not isinstance(header, dict):
        raise ValueError(f"{source.name} has no header object; is it a Dungeondraft map?")
    existing = [e for e in (header.get("asset_manifest") or []) if isinstance(e, dict)]
    final = merge_manifest(existing, manifest)
    header["asset_manifest"] = final

    _publish_new_file(destination, json.dumps(data, indent=1).encode("utf-8"), like=source)

    kept = [str(e.get("id", "")) for e in existing]
    return {
        "source": str(source),
        "path": str(destination),
        "packs_before": len(existing),
        "packs_after": len(final),
        "pack_ids": [entry["id"] for entry in final],
        "kept_from_source": kept,
        "added": [str(e["id"]) for e in final if str(e.get("id", "")) not in set(kept)],
    }
