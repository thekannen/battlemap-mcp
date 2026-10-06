"""Search what is inside the installed asset packs, including ones a map lacks.

`list_assets` only sees the packs the open map includes, and
`list_asset_packs` only names the others. Choosing a pack to include then comes
down to its name, and a name like "FA_Objects_A_v3.51" says nothing about
whether it has a pergola in it. This reads the packs themselves.

A `.dungeondraft_pack` is a Godot 3 PCK archive: a short header, then an index
of every file as (path, offset, size, md5), then the files, uncompressed. The
index is at the start, so listing a 4.9 GB pack reads a few megabytes and takes
about 80 ms (FA_Objects_A, 258,246 entries, measured 2026-10-05). Only three
kinds of thing are ever read: the index, `pack.json` and the pack's
`data/default.dungeondraft_tags`. Never any art.

Pack authors can opt out. `pack.json` may set
`allow_3rd_party_mapping_software_to_read: false`, and then nothing but
`pack.json` itself is read: the pack is listed by name as not searched. Assets
from a pack the map already includes still reach the caller through
Dungeondraft's own `list_assets`, as they always have.

The layout and the tags format follow Ryex/Dungeondraft-GoPackager (BSD-3) and
casancam/Dungeondraft-MCP (MIT), checked against real packs. Neither's code is
copied here.
"""

from __future__ import annotations

import json
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from . import installer
from .asset_search import query_words, score_path, searchable_text
from .errors import ValidationError

PACK_SUFFIX = ".dungeondraft_pack"
PCK_MAGIC = 0x43504447  # "GDPC"
# A real index entry's path is under a few hundred bytes. Anything far past
# that is a corrupt or foreign file, not a pack worth reading further.
MAX_PATH_BYTES = 4096
# The largest pack.json or tags file read. FA_Objects_A's tags are 14.7 MB.
MAX_TEXT_BYTES = 64 * 1024 * 1024
# Folders under textures/ and the list_assets category each one fills.
CATEGORY_FOLDERS = {
    "objects": "Objects",
    "walls": "Walls",
    "paths": "Paths",
    "terrain": "Terrain",
    "lights": "Lights",
    "portals": "Portals",
    "roofs": "Roofs",
    "patterns/normal": "Patterns",
    "patterns/colorable": "Patterns Colorable",
    "caves": "Caves",
    "materials": "Materials",
    "tilesets/simple": "Simple Tiles",
    "tilesets/smart": "Smart Tiles",
    "tilesets/smart_double": "Smart Tiles Double",
}
CATEGORIES = tuple(dict.fromkeys(CATEGORY_FOLDERS.values()))
IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")
OPT_OUT = "allow_3rd_party_mapping_software_to_read"
ASSETS_DIR_ENV = "BATTLEMAP_MCP_ASSETS_DIR"


class PackReadError(ValueError):
    """A file that is not a readable pack."""


@dataclass
class Pack:
    """One pack file: its pack.json and, unless it opted out, its assets."""

    file: Path
    info: dict[str, Any]
    restricted: bool
    # list_assets category -> [(res:// path, tags)]
    assets: dict[str, list[tuple[str, tuple[str, ...]]]] = field(default_factory=dict)
    # category -> [(path, tags as text, searchable text)], built on first search
    _searchable: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)

    def searchable(self, category: str) -> list[tuple[str, str, str]]:
        if category not in self._searchable:
            rows = []
            for path, tags in self.assets.get(category, ()):
                extra = " ".join(tags)
                rows.append((path, extra, searchable_text(path, extra)))
            self._searchable[category] = rows
        return self._searchable[category]

    @property
    def id(self) -> str:
        return str(self.info.get("id", ""))

    @property
    def name(self) -> str:
        return str(self.info.get("name", "")) or self.file.stem


def lenient_json(text: str) -> Any:
    """JSON as pack tools write it: trailing commas are common in tags files."""
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


def read_index(handle: BinaryIO) -> list[tuple[str, int, int]]:
    """The (path, offset, size) of every file in a Godot 3 PCK."""
    header = handle.read(20)
    if len(header) != 20:
        raise PackReadError("too short to be a pack")
    magic, _version, _major, _minor, _patch = struct.unpack("<5I", header)
    if magic != PCK_MAGIC:
        raise PackReadError("not a Godot PCK archive")
    handle.read(64)  # 16 reserved u32
    (count,) = struct.unpack("<I", handle.read(4))
    entries = []
    for _ in range(count):
        (length,) = struct.unpack("<I", handle.read(4))
        if length > MAX_PATH_BYTES:
            raise PackReadError("index entry path is implausibly long")
        path = handle.read(length).rstrip(b"\0").decode("utf-8")
        offset, size = struct.unpack("<QQ", handle.read(16))
        handle.read(16)  # md5
        entries.append((path, offset, size))
    return entries


def _read_text(handle: BinaryIO, offset: int, size: int) -> str:
    if size > MAX_TEXT_BYTES:
        raise PackReadError(f"text entry of {size} bytes is too large")
    handle.seek(offset)
    return handle.read(size).decode("utf-8-sig")


def _category(relative: str) -> str | None:
    """The list_assets category of a pack-relative path, or None."""
    if not relative.startswith("textures/"):
        return None
    folders = relative.split("/")[1:-1]
    for depth in (2, 1):
        category = CATEGORY_FOLDERS.get("/".join(folders[:depth]))
        if category is not None and len(folders) >= depth:
            return category
    return None


def read_pack(file: Path) -> Pack:
    """Read one pack's index, pack.json and, unless it opted out, its tags."""
    with file.open("rb") as handle:
        entries = read_index(handle)
        located = {path: (offset, size) for path, offset, size in entries}
        manifests = [
            path for path in located if re.fullmatch(r"res://packs/[^/]+/pack\.json", path)
        ]
        if len(manifests) != 1:
            raise PackReadError("pack has no single pack.json")
        info = lenient_json(_read_text(handle, *located[manifests[0]]))
        if not isinstance(info, dict):
            raise PackReadError("pack.json is not an object")
        pack_id = manifests[0].split("/")[3]
        info.setdefault("id", pack_id)
        if info.get(OPT_OUT) is False:
            return Pack(file, info, restricted=True)
        prefix = f"res://packs/{pack_id}/"
        tags: dict[str, list[str]] = {}
        tags_entry = located.get(prefix + "data/default.dungeondraft_tags")
        if tags_entry is not None:
            try:
                document = lenient_json(_read_text(handle, *tags_entry))
            except (ValueError, UnicodeDecodeError):
                document = {}
            raw = document.get("tags", {}) if isinstance(document, dict) else {}
            for tag, paths in raw.items() if isinstance(raw, dict) else ():
                for relative in paths if isinstance(paths, list) else ():
                    tags.setdefault(str(relative), []).append(str(tag))
    assets: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for path in located:
        if not path.startswith(prefix) or not path.lower().endswith(IMAGE_SUFFIXES):
            continue
        relative = path[len(prefix) :]
        category = _category(relative)
        if category is None:
            continue
        if category == "Walls" and re.search(r"_end\.\w+$", relative):
            continue  # a wall's end cap, listed by Dungeondraft with its wall
        assets.setdefault(category, []).append((path, tuple(tags.get(relative, ()))))
    return Pack(file, info, restricted=False, assets=assets)


_cache: dict[Path, tuple[tuple[int, int], Pack | PackReadError]] = {}


def load_pack(file: Path) -> Pack:
    """read_pack, remembered until the file's size or mtime changes."""
    resolved = file.resolve()
    stat = resolved.stat()
    key = (stat.st_size, stat.st_mtime_ns)
    cached = _cache.get(resolved)
    if cached is None or cached[0] != key:
        try:
            result: Pack | PackReadError = read_pack(resolved)
        except (OSError, PackReadError, ValueError, UnicodeDecodeError, struct.error) as error:
            result = error if isinstance(error, PackReadError) else PackReadError(str(error))
        cached = (key, result)
        _cache[resolved] = cached
    if isinstance(cached[1], PackReadError):
        raise cached[1]
    return cached[1]


def assets_directory() -> Path:
    """Dungeondraft's asset pack folder."""
    config = installer.dungeondraft_data_dir() / "config.ini"
    override = os.environ.get(ASSETS_DIR_ENV, "").strip()
    folder = (
        Path(override)
        if override
        else installer.config_path_value(config, "Assets", "custom_assets_directory")
    )
    if folder is None:
        raise ValidationError(
            "Dungeondraft has no asset pack folder set (Settings > Assets), so "
            f"there are no packs to search. Set {ASSETS_DIR_ENV} if they live "
            "somewhere Dungeondraft's config.ini does not name."
        )
    if not folder.is_dir():
        raise ValidationError(f"the asset pack folder {folder} does not exist")
    return folder


def _version_key(pack: Pack) -> tuple:
    numbers = [int(part) for part in re.findall(r"\d+", str(pack.info.get("version", "")))]
    return (numbers, pack.file.stat().st_mtime_ns)


def discover(folder: Path, mounted_versions: dict[str, str] | None = None) -> dict[str, Any]:
    """Every pack file in the folder, one per id.

    Two files can carry the same pack id (an old and a new version left side
    by side). Dungeondraft mounts one of them; the one whose version matches
    what the bridge reports mounted is used, else the newest.
    """
    by_id: dict[str, list[Pack]] = {}
    unreadable = []
    for file in sorted(folder.rglob(f"*{PACK_SUFFIX}")):
        if not file.is_file():
            continue
        try:
            pack = load_pack(file)
        except (OSError, PackReadError) as error:
            unreadable.append({"file": file.name, "reason": str(error)})
            continue
        by_id.setdefault(pack.id, []).append(pack)
    chosen: dict[str, Pack] = {}
    duplicates = {}
    for pack_id, packs in by_id.items():
        wanted = (mounted_versions or {}).get(pack_id)
        matching = [p for p in packs if wanted is not None and str(p.info.get("version")) == wanted]
        chosen[pack_id] = (matching or sorted(packs, key=_version_key))[-1]
        if len(packs) > 1:
            duplicates[pack_id] = {
                "searched": chosen[pack_id].file.name,
                "also_found": [p.file.name for p in packs if p is not chosen[pack_id]],
            }
    return {"packs": chosen, "duplicates": duplicates, "unreadable": unreadable}


def search(
    packs: dict[str, Pack],
    terms: list[str],
    category: str,
    *,
    mode: str = "tokens",
    limit: int = 20,
) -> dict[str, Any]:
    """Match each term against every searchable pack's paths and tags.

    Per term: how many assets matched in each pack (all of them, not just the
    ones returned), and the best `limit` paths across packs, grouped by pack.
    """
    results = {}
    for term in terms:
        scored = []
        counts: dict[str, int] = {}
        needle, words = term.lower(), query_words(term)
        for pack_id, pack in packs.items():
            if pack.restricted:
                continue
            for path, extra, text in pack.searchable(category):
                # Cheap prefilter: score_path's own test for both modes.
                if mode == "substring":
                    if needle not in path.lower() and needle not in extra.lower():
                        continue
                elif not all(word in text for word in words):
                    continue
                match = score_path(path, term, mode, extra)
                if match is None:
                    continue
                counts[pack_id] = counts.get(pack_id, 0) + 1
                scored.append((match.score, path, pack_id))
        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        best: dict[str, list[str]] = {}
        for _score, path, pack_id in scored[:limit]:
            best.setdefault(pack_id, []).append(path)
        results[term] = {
            "matched_by_pack": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "best": best,
        }
    return results
