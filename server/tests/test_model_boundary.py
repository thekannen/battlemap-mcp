"""What the MCP boundary actually sends a model, exercised through a real client.

Calling a tool function directly proves nothing about the wire: the SDK does
its own conversion after the function returns. These go through an in-process
MCP client so serialisation, errors and images are checked as a model gets them.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest
from mcp.client import Client
from PIL import Image as PILImage

from battlemap_mcp import server, timing
from battlemap_mcp.bridge_client import BridgeClient

TERRAIN = {
    "samples": 16,
    "weights": [[[1, 0, 0, 0]] * 16] * 16,
    "slots": ["res://textures/terrain/terrain_grass.png"] * 4,
    "label": "Größe ✓",
}


def _call(name: str, arguments: dict):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())


@pytest.fixture
def bridge(monkeypatch):
    replies: dict[str, object] = {}
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **params: replies[cmd])
    return replies


def test_dict_results_reach_the_model_as_one_compact_text_block(bridge):
    bridge["get_terrain"] = TERRAIN
    result = _call("get_terrain", {"samples": 16})

    assert not result.is_error
    assert result.structured_content is None
    [block] = result.content
    assert block.type == "text"
    assert json.loads(block.text) == TERRAIN
    assert "\n" not in block.text
    assert ": " not in block.text and ", " not in block.text
    # The pretty-printed form was 5x this; guard the saving, not an exact size.
    assert len(block.text) < 3000


def test_unicode_is_sent_as_text_not_escapes(bridge):
    bridge["get_terrain"] = TERRAIN
    [block] = _call("get_terrain", {"samples": 16}).content
    assert "Größe ✓" in block.text


def test_direct_python_callers_still_get_dicts(bridge):
    bridge["get_terrain"] = TERRAIN
    assert server.get_terrain(samples=16) == TERRAIN


def test_validation_errors_still_reach_the_model(bridge):
    result = _call("set_ambient_light", {"color": "nope"})
    assert result.is_error
    assert "#rrggbb" in result.content[0].text


def test_images_pass_through_as_image_content(monkeypatch, tmp_path):
    png = io.BytesIO()
    PILImage.new("RGB", (4, 3), "red").save(png, format="PNG")
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **params: {"path": "x"})
    monkeypatch.setattr(server, "_capture_path", lambda reported, expected=None: "x")
    monkeypatch.setattr(server, "_wait_for_file", lambda path, timeout=60.0: png.getvalue())
    monkeypatch.setattr(server, "_prune_captures", lambda: 0)

    image, caption = _call("screenshot", {}).content
    assert image.type == "image"
    assert image.mime_type == "image/png"
    # The client folds the image into the tool call, so the person asking to
    # "see" the map needs the file: the caption must name it (C2, 2026-09-21).
    assert caption.type == "text"
    assert "Screenshot saved: x" in caption.text
    assert "the user cannot" in caption.text


def test_ordinary_list_results_are_still_compact_json(monkeypatch):
    """Only a list carrying an image is passed through as content blocks."""
    assert server._model_text([1, {"a": 2}]) == '[1,{"a":2}]'
    sentinel = [server.Image(data=b"x", format="png"), "caption"]
    assert server._model_text(sentinel) is sentinel


def test_no_tool_advertises_an_output_schema():
    """One text block per result: structured output would send it twice."""
    tools = asyncio.run(server.mcp.list_tools())
    assert [t.name for t in tools if t.output_schema] == []


def test_timing_is_off_unless_asked_for(bridge, monkeypatch, tmp_path):
    monkeypatch.delenv(timing.ENV_VAR, raising=False)
    bridge["get_terrain"] = TERRAIN
    _call("get_terrain", {"samples": 16})
    assert list(tmp_path.iterdir()) == []


def test_timing_records_sizes_and_durations_but_no_content(monkeypatch, tmp_path, fake_bridge):
    """A timing file must be shareable without leaking the map it measured."""
    log = tmp_path / "timing.jsonl"
    monkeypatch.setenv(timing.ENV_VAR, str(log))
    fake_bridge.responses["get_terrain"] = {"ok": True, "result": TERRAIN}
    monkeypatch.setattr(
        server, "bridge", BridgeClient(port=fake_bridge.port, token=fake_bridge.token)
    )

    _call("get_terrain", {"samples": 16, "rect": [1, 2, 3, 4]})
    _call("set_ambient_light", {"color": "nope"})

    rows = [json.loads(line) for line in log.read_text().splitlines()]
    ok, failed = rows
    assert ok["tool"] == "get_terrain"
    assert ok["bridge_requests"] == 1
    assert ok["bridge_response_bytes"] > 0
    assert ok["result_chars"] > 0
    assert ok["total_ms"] >= ok["bridge_ms"] >= 0
    assert "error" not in ok
    assert failed == {**failed, "tool": "set_ambient_light", "error": "ValidationError"}
    assert failed["bridge_requests"] == 0

    allowed = {
        "event",
        "tool",
        "started",
        "total_ms",
        "error",
        "result_chars",
        "result_image_bytes",
        "bridge_requests",
        "bridge_ms",
        "bridge_response_bytes",
    }
    assert {key for row in rows for key in row} <= allowed
    text = log.read_text()
    for content in ("terrain_grass", "Größe", "rect", "nope"):
        assert content not in text


def test_an_unwritable_timing_file_never_fails_a_tool(bridge, monkeypatch, tmp_path):
    monkeypatch.setenv(timing.ENV_VAR, str(tmp_path / "missing-dir" / "timing.jsonl"))
    bridge["get_terrain"] = TERRAIN
    assert not _call("get_terrain", {"samples": 16}).is_error


# The same client that cut server instructions at 2048 characters cuts tool
# descriptions there too. list_assets was 3,083 characters, so the model never
# saw its "up to 8 terms" rule: the S1 and S2 UAT workers sent 16 and 17
# searches and each failed one call without knowing why (2026-09-21).
DESCRIPTION_LIMIT = 2048


def test_every_tool_description_fits_the_client_limit():
    tools = asyncio.run(server.mcp.list_tools())
    too_long = {
        t.name: len(t.description or "")
        for t in tools
        if len(t.description or "") > DESCRIPTION_LIMIT
    }
    assert too_long == {}, f"descriptions a client will truncate: {too_long}"


def test_the_search_cap_is_in_the_schema_not_only_the_prose():
    tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "list_assets")
    searches = tool.input_schema["properties"]["searches"]
    array = next(branch for branch in searches["anyOf"] if branch.get("type") == "array")
    assert array["maxItems"] == server.MAX_SEARCHES
    assert str(server.MAX_SEARCHES) in searches["description"]


def test_too_many_searches_reaches_the_model_as_an_error(bridge):
    result = _call(
        "list_assets", {"searches": [f"term{i}" for i in range(server.MAX_SEARCHES + 1)]}
    )
    assert result.is_error
    assert str(server.MAX_SEARCHES) in result.content[0].text
