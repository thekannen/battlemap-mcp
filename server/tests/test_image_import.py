import struct
import zlib

import pytest
from PIL import Image

from battlemap_mcp import image_import, server
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


def test_valid_png_chunks_with_corrupt_pixels_are_rejected(png):
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
        image_import.read_png(str(png))
