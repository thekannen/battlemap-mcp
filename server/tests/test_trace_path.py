"""Runtime behavior and validation."""

from battlemap_mcp import server


def _long_file(tmp_path, suffix=".png"):
    folder = tmp_path
    while len(str(folder)) < server.TRACE_PATH_LIMIT + 10:
        folder = folder / ("d" * 40)
    folder.mkdir(parents=True)
    image = folder / f"reference{suffix}"
    image.write_bytes(b"\x89PNG fake image bytes")
    return image


def test_a_long_path_is_copied_somewhere_short(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(out))
    image = _long_file(tmp_path)
    sent, copied_from = server._short_trace_path(str(image))
    assert copied_from == str(image)
    assert len(sent) < server.TRACE_PATH_LIMIT
    assert sent.startswith(str(out))
    assert open(sent, "rb").read() == image.read_bytes()


def test_a_short_path_is_passed_through(tmp_path, monkeypatch):
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(tmp_path / "out"))
    image = tmp_path / "plan.png"
    image.write_bytes(b"x")
    assert server._short_trace_path(str(image)) == (str(image), None)


def test_only_images_are_ever_copied(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(out))
    secret = _long_file(tmp_path, suffix=".txt")
    assert server._short_trace_path(str(secret)) == (str(secret), None)
    assert not out.exists()


def test_an_unreadable_long_path_is_left_for_the_bridge_to_report(tmp_path, monkeypatch):
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(tmp_path / "out"))
    missing = "C:/" + "x" * 300 + ".png"
    assert server._short_trace_path(missing) == (missing, None)
