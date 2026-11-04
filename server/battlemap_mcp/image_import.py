"""Create native, tagged Dungeondraft packs from explicitly supplied PNGs."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import struct
import tempfile
from pathlib import Path
from uuid import uuid4

from .errors import ValidationError


def read_png(path: str) -> bytes:
    from PIL import Image

    source = Path(path).expanduser()
    if not source.is_absolute() or not source.is_file() or source.suffix.lower() != ".png":
        raise ValidationError("path must be an absolute path to a local PNG file")
    with source.open("rb") as handle:
        data = handle.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValidationError("PNG must not exceed 32 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError("not PNG")
            w, h = image.size
            if max(w, h) > 8192 or w * h > 16_000_000:
                raise ValueError("exceeds 8192 pixels per side or 16 million pixels")
            image.verify()
        # verify() checks chunks/CRCs but does not decompress the pixel stream.
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(f"invalid or oversized PNG: {exc}") from exc
    return data


def build_pack(
    path: str, name: str, images: list[dict], pack_id: str = "", author: str = ""
) -> dict:
    destination = Path(path).expanduser()
    if not destination.is_absolute() or destination.suffix != ".dungeondraft_pack":
        raise ValidationError("path must be an absolute .dungeondraft_pack filename")
    if destination.exists() or destination.is_symlink():
        raise ValidationError("output already exists; choose a new filename")
    if not destination.parent.is_dir():
        raise ValidationError("output directory must exist")
    if not name.strip() or len(name) > 120:
        raise ValidationError("name must contain 1-120 characters")
    pack_id = pack_id or uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9]{8}", pack_id):
        raise ValidationError("pack_id must be eight letters or digits")
    if not 1 <= len(images) <= 100:
        raise ValidationError("provide 1-100 images")
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
        if total > 256 * 1024 * 1024:
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
    # Native RefreshAssetPacks enumerates this root manifest; the inner one
    # is also emitted by Dungeondraft's own packager and read by our indexer.
    files[f"res://packs/{pack_id}.json"] = json.dumps(meta).encode()
    names = [key.encode() for key in files]
    names = [value + b"\0" * (-len(value) % 4) for value in names]
    offset = 88 + sum(4 + len(value) + 32 for value in names)
    index = bytearray()
    for entry, data in zip(names, files.values(), strict=True):
        index.extend(struct.pack("<I", len(entry)) + entry)
        index.extend(struct.pack("<QQ", offset, len(data)) + hashlib.md5(data).digest())
        offset += len(data)
    fd, temporary = tempfile.mkstemp(prefix=".image-pack-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(struct.pack("<5I", 0x43504447, 1, 3, 4, 2) + b"\0" * 64)
            handle.write(struct.pack("<I", len(files)) + index)
            for data in files.values():
                handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic no-clobber publication, including a competing writer.
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)
    return {
        "path": str(destination),
        "pack": meta,
        "assets": assets,
        "installed": False,
        "included_in_map": False,
        "note": "Save this pack in Dungeondraft's configured asset directory, "
        "call refresh_asset_packs, then include "
        "it with prepare_map_with_packs. This tool does not reload the editor. "
        "Use a new pack id for additions during a session: already-loaded pack ids "
        "are cached until Dungeondraft restarts. Keep old packs for existing maps.",
    }
