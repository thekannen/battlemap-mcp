"""An asynchronous writer pausing mid-image must not look like completion."""

import io

import pytest
from PIL import Image

from battlemap_mcp import server
from battlemap_mcp.errors import BridgeUnavailableError, ValidationError


@pytest.fixture(autouse=True)
def captures_land_in_tmp_path(tmp_path, monkeypatch):
    """These fakes write where the test says; make that the trusted root."""
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)


def image_bytes(format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(output, format=format)
    return output.getvalue()


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_wait_returns_exact_decodable_bytes(tmp_path, format):
    path = tmp_path / "render"
    data = image_bytes(format)
    path.write_bytes(data)
    assert server._wait_for_file(str(path), timeout=0.1) == data


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_unchanging_truncated_image_does_not_count_as_complete(tmp_path, monkeypatch, format):
    path = tmp_path / "render"
    path.write_bytes(image_bytes(format)[:-12])
    now = [0.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(server.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    with pytest.raises(BridgeUnavailableError):
        server._wait_for_file(str(path), timeout=1.0)
    assert now[0] == 1.0


def test_paused_writer_can_finish_after_several_identical_sizes(tmp_path, monkeypatch):
    path = tmp_path / "render.png"
    data = image_bytes()
    path.write_bytes(data[:-12])
    sleeps = []

    def advance(delay):
        sleeps.append(delay)
        if len(sleeps) == 3:
            path.write_bytes(data)

    monkeypatch.setattr(server.time, "sleep", advance)
    assert server._wait_for_file(str(path)) == data
    assert len(sleeps) == 3


def test_screenshots_use_distinct_files_and_preserve_old_output(tmp_path, monkeypatch):
    old = tmp_path / "export.png"
    old.write_bytes(b"previous output")
    names = []
    data = image_bytes()

    def request(command, **params):
        path = tmp_path / params["name"]
        names.append(params["name"])
        path.write_bytes(data)
        return {"path": str(path)}

    monkeypatch.setattr(server.bridge, "request", request)
    first, _ = server.screenshot()
    second, _ = server.screenshot()
    assert len(set(names)) == 2
    assert old.read_bytes() == b"previous output"
    assert first.data == second.data == data


class FakeExporter:
    """The bridge's export operation: rendering for `polls` polls, then settles."""

    def __init__(self, tmp_path, polls=2, outcome="completed", error="", flaky=0):
        self.tmp_path = tmp_path
        self.polls = polls
        self.outcome = outcome
        self.error = error
        self.flaky = flaky
        self.names = []
        self.calls = []

    def request(self, command, **params):
        self.calls.append(command)
        if command == "export_map":
            self.names.append(params["name"])
            self.path = self.tmp_path / params["name"]
            self.format = params["format"]
            return {"operation_id": f"export-{len(self.names)}", "state": "rendering"}
        assert command == "get_operation", command
        if self.flaky:
            self.flaky -= 1
            raise BridgeUnavailableError("recv timed out", last_command={"cmd": command})
        status = {
            "operation_id": params["operation_id"],
            "path": str(self.path),
            "format": self.format,
            "chunks_rendered": 4,
        }
        if self.polls:
            self.polls -= 1
            return {**status, "state": "rendering"}
        if self.outcome == "completed":
            self.path.write_bytes(image_bytes())
        return {**status, "state": self.outcome, "error": self.error}


@pytest.fixture
def no_sleep(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        server.time, "sleep", lambda delay: now.__setitem__(0, now[0] + max(delay, 0.25))
    )
    return now


def test_export_waits_for_the_bridge_operation_not_the_file(tmp_path, monkeypatch, no_sleep):
    fake = FakeExporter(tmp_path, polls=3)
    monkeypatch.setattr(server.bridge, "request", fake.request)
    image, _ = server.export_map()
    assert image.data == image_bytes()
    assert fake.calls == ["export_map"] + ["get_operation"] * 4


def test_exports_use_distinct_files_and_preserve_old_output(tmp_path, monkeypatch, no_sleep):
    old = tmp_path / "export.png"
    old.write_bytes(b"previous output")
    fake = FakeExporter(tmp_path, polls=0)
    monkeypatch.setattr(server.bridge, "request", fake.request)
    server.export_map()
    server.export_map()
    assert len(set(fake.names)) == 2
    assert old.read_bytes() == b"previous output"


def test_failed_export_raises_the_bridges_reason(tmp_path, monkeypatch, no_sleep):
    fake = FakeExporter(tmp_path, polls=1, outcome="failed", error="the exporter never started")
    monkeypatch.setattr(server.bridge, "request", fake.request)
    with pytest.raises(ValidationError, match="the exporter never started"):
        server.export_map()


def test_a_poll_that_times_out_is_retried(tmp_path, monkeypatch, no_sleep):
    """The final encode blocks Dungeondraft's main thread, which serves the socket."""
    fake = FakeExporter(tmp_path, polls=0, flaky=3)
    monkeypatch.setattr(server.bridge, "request", fake.request)
    assert server.export_map()[0].data == image_bytes()


def test_timeout_names_the_operation_to_collect(tmp_path, monkeypatch, no_sleep):
    fake = FakeExporter(tmp_path, polls=10_000)
    monkeypatch.setattr(server.bridge, "request", fake.request)
    with pytest.raises(ValidationError, match=r"get_export\(operation_id='export-1'\)"):
        server.export_map(timeout=2)
    fake.polls = 0
    assert server.get_export("export-1")[0].data == image_bytes()
    assert len(fake.names) == 1, "collecting must never start a second render"


def test_losing_the_bridge_is_not_reported_as_still_rendering(tmp_path, monkeypatch, no_sleep):
    fake = FakeExporter(tmp_path, polls=0, flaky=10_000)
    monkeypatch.setattr(server.bridge, "request", fake.request)
    with pytest.raises(BridgeUnavailableError, match="lost the bridge"):
        server.export_map(timeout=2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ppi": 0},
        {"ppi": True},
        {"ppi": 40.5},
        {"timeout": 0},
        {"timeout": 601},
        {"timeout": float("nan")},
        {"format": "vtt"},
    ],
)
def test_bad_export_arguments_never_reach_the_bridge(monkeypatch, kwargs):
    monkeypatch.setattr(server.bridge, "request", lambda *a, **k: pytest.fail("sent"))
    with pytest.raises(ValidationError):
        server.export_map(**kwargs)


def test_an_overdue_export_stops_the_wait_and_names_the_recovery(tmp_path, monkeypatch, no_sleep):
    """The bridge keeps an unconfirmed export locked; waiting on cannot help."""
    fake = FakeExporter(tmp_path, polls=10_000)
    original = fake.request

    def overdue(command, **params):
        result = original(command, **params)
        if command == "get_operation" and len(fake.calls) > 3:
            result = {**result, "overdue": True, "recovery": "rendering for over 600 s. Restart"}
        return result

    monkeypatch.setattr(server.bridge, "request", overdue)
    with pytest.raises(ValidationError, match="Restart"):
        server.export_map(timeout=600)
    assert no_sleep[0] < 5, "kept polling an export the bridge will not release"


def test_max_px_shrinks_only_the_long_edge_and_never_upscales(monkeypatch):
    """The knob exists for a caller who has measured what detail they need; the
    default stays the full capture, because nobody has measured that here."""
    import io

    from PIL import Image as PILImage

    from battlemap_mcp import server

    def png(width, height):
        buffer = io.BytesIO()
        PILImage.new("RGB", (width, height), "red").save(buffer, format="PNG")
        return buffer.getvalue()

    original = png(2000, 1000)
    assert server._downscale(original, None, "png") is original, "the default must not touch it"

    shrunk = server._downscale(original, 500, "png")
    with PILImage.open(io.BytesIO(shrunk)) as rendered:
        assert rendered.size == (500, 250)

    small = png(100, 80)
    assert server._downscale(small, 500, "png") is small, "never upscale"


def test_max_px_is_validated_before_a_render_is_started():
    import pytest

    from battlemap_mcp import server
    from battlemap_mcp.errors import ValidationError

    for bad in (0, 63, -10, True):
        with pytest.raises(ValidationError):
            server._require_max_px(bad)
    server._require_max_px(None)
    server._require_max_px(64)
