"""Retention may remove only capture files this server names."""

import io
import os

from PIL import Image

from battlemap_mcp import server


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(output, format="PNG")
    return output.getvalue()


def capture(root, name, timestamp):
    path = root / name
    path.write_bytes(b"capture")
    os.utime(path, ns=(timestamp, timestamp))
    return path


def test_pruning_keeps_the_newest_generated_captures_and_preserves_user_files(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    oldest = capture(tmp_path, f"screenshot-{'a' * 32}.png", 1_000_000_000)
    retained = capture(tmp_path, f"export-{'b' * 32}.webp", 2_000_000_000)
    newest = capture(tmp_path, "asset_preview.png", 3_000_000_000)
    user_file = capture(tmp_path, "holiday.png", 4_000_000_000)
    near_match = capture(tmp_path, f"screenshot-{'c' * 32}.jpg", 5_000_000_000)
    user_dir = tmp_path / f"export-{'d' * 32}.png"
    user_dir.mkdir()

    assert server._prune_captures(keep=2) == 1

    assert not oldest.exists()
    assert retained.exists()
    assert newest.exists()
    assert user_file.exists()
    assert near_match.exists()
    assert user_dir.is_dir()


def test_clear_captures_removes_only_generated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    screenshot = capture(tmp_path, f"screenshot-{'a' * 32}.png", 1)
    export = capture(tmp_path, f"export-{'b' * 32}.jpeg", 2)
    preview = capture(tmp_path, "asset_preview.png", 3)
    user_file = capture(tmp_path, "notes.png", 4)

    assert server.clear_captures() == {"cleared": 3}

    assert not screenshot.exists()
    assert not export.exists()
    assert not preview.exists()
    assert user_file.exists()


def test_clear_captures_preserves_a_capture_shaped_symlink(
    tmp_path, monkeypatch, create_file_symlink_or_skip
):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    target = tmp_path / "notes.png"
    target.write_bytes(b"user content")
    link = tmp_path / f"screenshot-{'a' * 32}.png"
    create_file_symlink_or_skip(link, target)

    assert server.clear_captures() == {"cleared": 0}

    assert link.is_symlink()
    assert target.read_bytes() == b"user content"


def test_a_successful_screenshot_triggers_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    calls = []

    def request(command, **params):
        path = tmp_path / params["name"]
        path.write_bytes(image_bytes())
        return {"path": str(path)}

    monkeypatch.setattr(server.bridge, "request", request)
    monkeypatch.setattr(server, "_prune_captures", lambda: calls.append(True) or 0)

    server.screenshot()

    assert calls == [True]


def test_successful_preview_and_export_trigger_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    calls = []
    preview = tmp_path / "asset_preview.png"
    export = tmp_path / f"export-{'a' * 32}.png"
    preview.write_bytes(image_bytes())
    export.write_bytes(image_bytes())
    monkeypatch.setattr(server, "_prune_captures", lambda: calls.append(True) or 0)
    monkeypatch.setattr(server.bridge, "request", lambda command, **params: {"path": str(preview)})

    server.preview_assets(["textures/objects/x.png"])
    server._export_image(
        {"state": "completed", "operation_id": "export-1", "path": str(export), "format": "png"}
    )

    assert calls == [True, True]
