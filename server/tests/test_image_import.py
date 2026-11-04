import struct
import zlib

import pytest
from PIL import Image

from battlemap_mcp import image_import, pack_contents, server
from battlemap_mcp.errors import ValidationError


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (64, 32), (128, 0, 255, 80)).save(path)
    return path


def test_embedded_request(png, monkeypatch):
    calls = []
    monkeypatch.setattr(
        server.bridge, "request", lambda cmd, **kw: calls.append((cmd, kw)) or {"id": 9}
    )
    assert server.import_image(str(png), 20, 30, 256, snap="none")["id"] == 9
    assert calls[0][0] == "import_image"
    assert calls[0][1]["width"] == 256
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
    ],
)
def test_invalid_placement_never_calls_bridge(png, monkeypatch, kw):
    monkeypatch.setattr(server.bridge, "request", lambda *a, **k: pytest.fail("bridge called"))
    params = dict(path=str(png), x=0, y=0, width=256, snap="none")
    params.update(kw)
    with pytest.raises(ValidationError):
        server.import_image(**params)


def test_invalid_png(png):
    png.write_bytes(b"not an image")
    with pytest.raises(ValidationError):
        image_import.read_png(str(png))


def test_native_pack_roundtrip(png, tmp_path):
    output = tmp_path / "Project.dungeondraft_pack"
    result = server.create_image_pack(
        str(output),
        "Project props",
        [{"path": str(png), "name": "Test prop", "tags": ["Workshop", "Wood"]}],
        pack_id="test1234",
    )
    pack = pack_contents.read_pack(output)
    assert pack.name == "Project props"
    [(asset, tags)] = pack.assets["Objects"]
    assert tags == ("Workshop", "Wood")
    assert asset == result["assets"][0]["asset"]
    # PCK payload is byte-identical, preserving alpha and original resolution.
    with output.open("rb") as f:
        f.seek(84)
        count = struct.unpack("<I", f.read(4))[0]
        entries = []
        for _ in range(count):
            n = struct.unpack("<I", f.read(4))[0]
            name = f.read(n).rstrip(b"\0").decode()
            offset, size = struct.unpack("<QQ", f.read(16))
            f.read(16)
            entries.append((name, offset, size))
        assert any(e[0] == "res://packs/test1234.json" for e in entries)
        name, offset, size = next(e for e in entries if e[0].endswith(".png"))
        f.seek(offset)
        assert f.read(size) == png.read_bytes()
    before = output.read_bytes()
    with pytest.raises(ValidationError):
        server.create_image_pack(
            str(output), "Project", [{"path": str(png), "name": "Test", "tags": ["Wood"]}]
        )
    assert output.read_bytes() == before


@pytest.mark.parametrize(
    "name,tags", [("../escape", ["Wood"]), ("Test", []), ("Test", ["Colorable"])]
)
def test_pack_rejects_unsafe_metadata(png, tmp_path, name, tags):
    output = tmp_path / "bad.dungeondraft_pack"
    with pytest.raises(ValidationError):
        image_import.build_pack(
            str(output), "Project", [{"path": str(png), "name": name, "tags": tags}]
        )
    assert not output.exists()


@pytest.mark.parametrize("tag", [" Colorable ", " colorable", "COLORABLE "])
def test_reserved_tag_is_checked_after_normalizing(png, tmp_path, tag):
    with pytest.raises(ValidationError, match="reserved"):
        image_import.build_pack(
            str(tmp_path / "bad.dungeondraft_pack"),
            "Project",
            [{"path": str(png), "name": "Test", "tags": [tag]}],
        )


def test_pack_returns_normalized_unique_tags(png, tmp_path):
    result = image_import.build_pack(
        str(tmp_path / "good.dungeondraft_pack"),
        "Project",
        [{"path": str(png), "name": "Test", "tags": [" Wood ", "Wood"]}],
    )
    assert result["assets"][0]["tags"] == ["Wood"]


def test_valid_png_chunks_with_corrupt_pixels_are_rejected(png, tmp_path):
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
            str(tmp_path / "bad.dungeondraft_pack"),
            "Project",
            [{"path": str(png), "name": "Test", "tags": ["Wood"]}],
        )
    assert not (tmp_path / "bad.dungeondraft_pack").exists()


def test_competing_output_writer_is_not_overwritten(png, tmp_path, monkeypatch):
    output = tmp_path / "race.dungeondraft_pack"
    link = image_import.os.link

    def race(source, destination):
        output.write_bytes(b"other writer")
        return link(source, destination)

    monkeypatch.setattr(image_import.os, "link", race)
    with pytest.raises(FileExistsError):
        image_import.build_pack(
            str(output),
            "Project",
            [{"path": str(png), "name": "Test", "tags": ["Wood"]}],
        )
    assert output.read_bytes() == b"other writer"
    assert not list(tmp_path.glob(".image-pack-*"))
