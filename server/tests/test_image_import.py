import os
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image

from battlemap_mcp import image_import, pack_contents, server
from battlemap_mcp.errors import ValidationError


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (64, 32), (128, 0, 255, 80)).save(path)
    return path


@pytest.fixture
def assets_dir(tmp_path, monkeypatch):
    folder = tmp_path / "assets"
    folder.mkdir()
    monkeypatch.setenv(pack_contents.ASSETS_DIR_ENV, str(folder))
    return folder


def test_embedded_request(png, monkeypatch):
    calls = []
    monkeypatch.setattr(
        server.bridge, "request", lambda cmd, **kw: calls.append((cmd, kw)) or {"id": 9}
    )
    assert server.import_image(str(png), 20, 30, 256, snap="none")["id"] == 9
    assert calls[0][0] == "import_image"
    assert calls[0][1]["width"] == 256
    assert calls[0][1]["path"] == png.resolve().as_posix()
    assert "height" not in calls[0][1]


@pytest.mark.parametrize(
    "kw",
    [
        {"width": 0},
        {"width": float("inf")},
        {"height": -1},
        {"rotation": float("nan")},
        {"sorting": 4},
        {"layer": 15},
        {"path": "relative.png"},
    ],
)
def test_invalid_placement_never_calls_bridge(png, monkeypatch, kw):
    monkeypatch.setattr(server.bridge, "request", lambda *a, **k: pytest.fail("bridge called"))
    params = dict(path=str(png), x=0, y=0, width=256, snap="none")
    params.update(kw)
    with pytest.raises(ValidationError):
        server.import_image(**params)


def test_not_a_png_is_refused(png, monkeypatch):
    monkeypatch.setattr(server.bridge, "request", lambda *a, **k: pytest.fail("bridge called"))
    png.write_bytes(b"not an image")
    with pytest.raises(ValidationError):
        server.import_image(str(png), 0, 0, 256, snap="none")


def test_other_formats_are_refused(tmp_path):
    jpg = tmp_path / "photo.png"
    Image.new("RGB", (8, 8)).save(jpg, format="JPEG")
    with pytest.raises(ValidationError):
        image_import.read_png(str(jpg))


def test_oversized_png_is_refused_before_decoding(tmp_path):
    big = tmp_path / "big.png"
    Image.new("L", (8193, 1)).save(big)
    with pytest.raises(ValidationError, match="8192"):
        image_import.read_png(str(big))


def test_valid_png_chunks_with_corrupt_pixels_are_rejected(png, assets_dir):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", b"invalid compressed pixel data")
        + chunk(b"IEND", b"")
    )
    with pytest.raises(ValidationError, match="invalid"):
        image_import.build_pack(
            "bad.dungeondraft_pack",
            "Project",
            [{"path": str(png), "name": "Test", "tags": ["Wood"]}],
        )
    assert not (assets_dir / "bad.dungeondraft_pack").exists()


def test_native_pack_roundtrip(png, assets_dir):
    result = server.create_image_pack(
        "Project.dungeondraft_pack",
        "Project props",
        [{"path": str(png), "name": "Test prop", "tags": ["Workshop", "Wood"]}],
        pack_id="test1234",
    )
    output = assets_dir / "Project.dungeondraft_pack"
    assert result["path"] == str(output.resolve())
    pack = pack_contents.read_pack(output)
    assert pack.name == "Project props"
    [(asset, tags)] = pack.assets["Objects"]
    assert tags == ("Workshop", "Wood")
    assert asset == result["assets"][0]["asset"]
    with output.open("rb") as handle:
        handle.seek(84)
        count = struct.unpack("<I", handle.read(4))[0]
        entries = []
        for _ in range(count):
            n = struct.unpack("<I", handle.read(4))[0]
            name = handle.read(n).rstrip(b"\0").decode()
            offset, size = struct.unpack("<QQ", handle.read(16))
            handle.read(16)
            entries.append((name, offset, size))
        assert any(entry[0] == "res://packs/test1234.json" for entry in entries)
        _name, offset, size = next(entry for entry in entries if entry[0].endswith(".png"))
        handle.seek(offset)
        assert handle.read(size) == png.read_bytes()
    before = output.read_bytes()
    with pytest.raises(ValidationError):
        server.create_image_pack(
            "Project.dungeondraft_pack",
            "Project",
            [{"path": str(png), "name": "Test", "tags": ["Wood"]}],
        )
    assert output.read_bytes() == before


def test_pack_refuses_paths_outside_asset_folder(png, assets_dir):
    with pytest.raises(ValidationError):
        image_import.build_pack(
            "../escape.dungeondraft_pack",
            "Project",
            [{"path": str(png), "name": "Test", "tags": ["Wood"]}],
        )
    assert not list(assets_dir.glob("*.dungeondraft_pack"))


@pytest.mark.parametrize(
    "name,tags", [("../escape", ["Wood"]), ("Test", []), ("Test", ["Colorable"])]
)
def test_pack_rejects_unsafe_metadata(png, assets_dir, name, tags):
    with pytest.raises(ValidationError):
        image_import.build_pack(
            "bad.dungeondraft_pack",
            "Project",
            [{"path": str(png), "name": name, "tags": tags}],
        )
    assert not (assets_dir / "bad.dungeondraft_pack").exists()


@pytest.mark.parametrize("tag", [" Colorable ", " colorable", "COLORABLE "])
def test_reserved_tag_is_checked_after_normalizing(png, assets_dir, tag):
    with pytest.raises(ValidationError, match="reserved"):
        image_import.build_pack(
            "bad.dungeondraft_pack",
            "Project",
            [{"path": str(png), "name": "Test", "tags": [tag]}],
        )


def test_pack_returns_normalized_unique_tags(png, assets_dir):
    result = image_import.build_pack(
        "good.dungeondraft_pack",
        "Project",
        [{"path": str(png), "name": "Test", "tags": [" Wood ", "Wood"]}],
    )
    assert result["assets"][0]["tags"] == ["Wood"]


def test_competing_output_writer_is_not_overwritten(png, assets_dir, monkeypatch):
    output = assets_dir / "race.dungeondraft_pack"
    real_open = os.open

    def race(path, flags, mode=0o777, *args, **kwargs):
        if Path(path).resolve() == output.resolve() and flags & os.O_EXCL:
            output.write_bytes(b"other writer")
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(image_import.os, "open", race)
    with pytest.raises(ValidationError, match="already exists"):
        image_import.build_pack(
            "race.dungeondraft_pack",
            "Project",
            [{"path": str(png), "name": "Test", "tags": ["Wood"]}],
        )
    assert output.read_bytes() == b"other writer"
