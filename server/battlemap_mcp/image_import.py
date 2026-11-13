"""Local PNG checks for import_image, and building tagged asset packs."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import struct
from pathlib import Path
from uuid import uuid4

from . import pack_contents
from .errors import ValidationError
from .validation import require_bare_filename

# The bridge refuses the same limits before it decodes anything.
MAX_BYTES = 32 * 1024 * 1024
MAX_SIDE = 8192
MAX_PIXELS = 16_000_000
MAX_PACK_IMAGES = 100
MAX_PACK_IMAGE_BYTES = 256 * 1024 * 1024
PACK_SUFFIX = pack_contents.PACK_SUFFIX


def read_png(path: str) -> bytes:
    """The file's bytes, if it is a PNG that decodes within the limits."""
    from PIL import Image

    source = Path(path).expanduser()
    if not source.is_absolute() or not source.is_file() or source.suffix.lower() != ".png":
        raise ValidationError("path must be an absolute path to a local PNG file")
    with source.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValidationError("PNG must not exceed 32 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError("not PNG")
            w, h = image.size
            if max(w, h) > MAX_SIDE or w * h > MAX_PIXELS:
                raise ValueError("exceeds 8192 pixels per side or 16 million pixels")
            image.verify()
        # verify() checks chunks and CRCs but does not decompress the pixels.
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(f"invalid or oversized PNG: {exc}") from exc
    return data


def _pack_destination(filename: str) -> Path:
    """Resolve a bare pack filename inside Dungeondraft's configured asset folder."""
    folder = pack_contents.assets_directory()
    bare = require_bare_filename(filename)
    if not bare.endswith(PACK_SUFFIX):
        bare += PACK_SUFFIX
    # require_bare_filename already forbids separators; keep the join closed.
    root = folder.resolve()
    destination = (folder / bare).resolve()
    if destination.parent != root or not destination.name.endswith(PACK_SUFFIX):
        raise ValidationError(
            f"filename resolves outside the asset pack folder ({destination}); refusing"
        )
    return destination


def _open_new_pack(destination: Path):
    """Open destination for exclusive create; never replace an existing file.

    Uses O_CREAT|O_EXCL so publication works on filesystems that lack hard
    links (exFAT, FAT32, many network shares). A competing writer that claimed
    the name first becomes FileExistsError.
    """
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(destination, flags, 0o644)
    except FileExistsError as exc:
        raise ValidationError(f"{destination.name} already exists; choose a new filename") from exc
    return os.fdopen(fd, "wb")


def build_pack(
    filename: str, name: str, images: list[dict], pack_id: str = "", author: str = ""
) -> dict:
    """Write a new tagged .dungeondraft_pack into the configured asset folder."""
    destination = _pack_destination(filename)
    if destination.exists() or destination.is_symlink():
        raise ValidationError(f"{destination.name} already exists; choose a new filename")
    if not name.strip() or len(name) > 120:
        raise ValidationError("name must contain 1-120 characters")
    pack_id = pack_id or uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9]{8}", pack_id):
        raise ValidationError("pack_id must be eight letters or digits")
    if not 1 <= len(images) <= MAX_PACK_IMAGES:
        raise ValidationError(f"provide 1-{MAX_PACK_IMAGES} images")
    files: dict[str, bytes] = {}
    tags: dict[str, list[str]] = {}
    assets = []
    total = 0
    for item in images:
        asset_name = item["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,99}", asset_name):
            raise ValidationError("image name must be 1-100 letters, digits, spaces, _ or -")
        relative = f"textures/objects/{asset_name}.png"
        if relative.casefold() in {key.casefold() for key in files}:
            raise ValidationError("image names must be unique ignoring case")
        asset_tags = item["tags"]
        if not 1 <= len(asset_tags) <= 32 or any(
            not tag.strip() or len(tag) > 80 or any(ord(c) < 32 for c in tag) for tag in asset_tags
        ):
            raise ValidationError("each image needs 1-32 nonempty tags, at most 80 characters each")
        # Colorable is an engine instruction, not descriptive metadata.
        asset_tags = list(dict.fromkeys(tag.strip() for tag in asset_tags))
        if any(tag.casefold() == "colorable" for tag in asset_tags):
            raise ValidationError("Colorable is reserved; it would recolor the imported artwork")
        data = read_png(item["path"])
        total += len(data)
        if total > MAX_PACK_IMAGE_BYTES:
            raise ValidationError("pack images must total at most 256 MiB")
        files[relative] = data
        for tag in dict.fromkeys(tag.strip() for tag in asset_tags):
            tags.setdefault(tag, []).append(relative)
        assets.append(
            {"name": asset_name, "asset": f"res://packs/{pack_id}/{relative}", "tags": asset_tags}
        )
    meta = {
        "id": pack_id,
        "name": name,
        "author": author,
        "version": "1.0",
        "allow_3rd_party_mapping_software_to_read": True,
    }
    files["pack.json"] = json.dumps(meta).encode()
    files["data/default.dungeondraft_tags"] = json.dumps(
        {"tags": tags, "sets": {name: list(tags)}}
    ).encode()
    files = {f"res://packs/{pack_id}/{key}": value for key, value in files.items()}
    # Native pack enumeration reads this root manifest; the inner pack.json is
    # also emitted by Dungeondraft's own packager and read by our indexer.
    files[f"res://packs/{pack_id}.json"] = json.dumps(meta).encode()
    names = [key.encode() for key in files]
    names = [value + b"\0" * (-len(value) % 4) for value in names]
    offset = 88 + sum(4 + len(value) + 32 for value in names)
    index = bytearray()
    for entry, data in zip(names, files.values(), strict=True):
        index.extend(struct.pack("<I", len(entry)) + entry)
        index.extend(struct.pack("<QQ", offset, len(data)) + hashlib.md5(data).digest())
        offset += len(data)
    created = False
    try:
        with _open_new_pack(destination) as handle:
            created = True
            handle.write(struct.pack("<5I", pack_contents.PCK_MAGIC, 1, 3, 4, 2) + b"\0" * 64)
            handle.write(struct.pack("<I", len(files)) + index)
            for data in files.values():
                handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # Only remove a file this call created; never a competing writer's.
        if created:
            try:
                os.unlink(destination)
            except OSError:
                pass
        raise
    return {
        "path": str(destination),
        "pack": meta,
        "assets": assets,
        "installed": False,
        "included_in_map": False,
        "note": "Wrote into Dungeondraft's configured asset folder. "
        "Rescan packs in the Assets window (or restart Dungeondraft), then include "
        "this pack with prepare_map_with_packs. This tool does not call Assets.UpdateTree. "
        "search_pack_contents can already see the new archive on disk. "
        "Use a new pack id for additions during a session: already-loaded pack ids "
        "are cached until Dungeondraft restarts. Keep old packs for existing maps. "
        "Never move or remove a mounted pack while Dungeondraft is running.",
    }
