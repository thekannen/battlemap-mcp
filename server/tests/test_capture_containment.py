"""A capture path comes from whatever answers the bridge port. Never trust it.

Security review 2026-09-13: anything listening on the port answers these
requests, and the server used to read whichever path the answer named and hand
the bytes to the model.
"""

import io

import pytest
from PIL import Image as PILImage

from battlemap_mcp import server
from battlemap_mcp.errors import BridgeProtocolError


def png():
    out = io.BytesIO()
    PILImage.new("RGB", (8, 8), "blue").save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def root(tmp_path, monkeypatch):
    output = tmp_path / "Dungeondraft" / "mcp_output"
    output.mkdir(parents=True)
    monkeypatch.setattr(server, "_capture_root", lambda: output)
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    return output


@pytest.fixture
def private(tmp_path):
    secrets = tmp_path / "private"
    secrets.mkdir()
    return secrets


def test_screenshot_refuses_an_image_outside_the_output_directory(root, private, monkeypatch):
    photo = private / "holiday.png"
    photo.write_bytes(png())
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **kw: {"path": str(photo)})
    with pytest.raises(BridgeProtocolError, match="refusing to read it"):
        server.screenshot()


def test_preview_refuses_an_arbitrary_file(root, private, monkeypatch):
    """Image(path=...) used to base64 any file, image or not."""
    key = private / "id_rsa"
    key.write_text("-----BEGIN SYNTHETIC PRIVATE KEY-----\n")
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **kw: {"path": str(key)})
    with pytest.raises(BridgeProtocolError):
        server.preview_assets(["textures/objects/x.png"])


def test_preview_refuses_even_the_right_name_elsewhere(root, private, monkeypatch):
    elsewhere = private / "asset_preview.png"
    elsewhere.write_bytes(png())
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **kw: {"path": str(elsewhere)})
    with pytest.raises(BridgeProtocolError):
        server.preview_assets(["textures/objects/x.png"])


def test_export_refuses_a_completed_status_pointing_elsewhere(root, private):
    photo = private / f"export-{'a' * 32}.png"
    photo.write_bytes(png())
    status = {"state": "completed", "operation_id": "export-1", "path": str(photo), "format": "png"}
    with pytest.raises(BridgeProtocolError):
        server._export_image(status)


def test_a_symlink_inside_the_output_directory_is_followed_before_the_check(
    root, private, create_file_symlink_or_skip
):
    photo = private / "holiday.png"
    photo.write_bytes(png())
    link = root / f"export-{'b' * 32}.png"
    create_file_symlink_or_skip(link, photo)
    with pytest.raises(BridgeProtocolError):
        server._capture_path(str(link))


@pytest.mark.parametrize(
    "name",
    ["holiday.png", "export-short.png", f"export-{'c' * 32}.png.txt", "../asset_preview.png"],
)
def test_names_the_server_never_asks_for_are_refused(root, name):
    target = root / name
    with pytest.raises(BridgeProtocolError):
        server._capture_path(str(target))


def test_a_relative_path_is_refused(root, monkeypatch):
    monkeypatch.chdir(root)
    (root / "asset_preview.png").write_bytes(png())
    with pytest.raises(BridgeProtocolError):
        server._capture_path("asset_preview.png", "asset_preview.png")


def test_the_screenshot_must_be_the_name_this_call_chose(root, monkeypatch):
    stale = root / f"screenshot-{'d' * 32}.png"
    stale.write_bytes(png())
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **kw: {"path": str(stale)})
    with pytest.raises(BridgeProtocolError):
        server.screenshot()


def test_a_genuine_capture_is_returned(root, monkeypatch):
    data = png()

    def request(cmd, **kw):
        path = root / kw["name"]
        path.write_bytes(data)
        return {"path": str(path)}

    monkeypatch.setattr(server.bridge, "request", request)
    assert server.screenshot()[0].data == data
    assert server.preview_assets(["textures/objects/x.png"]).data == data


def test_the_root_uses_an_independent_capture_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(tmp_path / "credentials" / "tok"))
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(tmp_path / "elsewhere" / "mcp_output"))
    assert server._capture_root() == tmp_path / "elsewhere" / "mcp_output"
