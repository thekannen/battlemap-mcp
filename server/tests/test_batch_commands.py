"""Batch placement and deletion: what reaches the bridge, and what is refused.

The engine behaviour (one undo step, rollback, the frame budget) belongs to the
UAT — it can only be observed in a running editor. These cover the half that is
knowable offline: validation, caps, and the exact request the bridge receives.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest
from mcp.client import Client

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.fixture
def calls(monkeypatch):
    sent: list[tuple[str, dict]] = []

    def request(command, **params):
        sent.append((command, params))
        return {"placed": len(params.get("objects", [])), "deleted": len(params.get("ids", []))}

    monkeypatch.setattr(server.bridge, "request", request)
    return sent


def test_place_objects_is_one_request_carrying_every_entry(calls):
    server.place_objects(
        [
            {"asset": "res://a.png", "x": 10, "y": 20},
            {"asset": "res://b.png", "x": 30, "y": 40, "rotation": 90, "color": "#ff8800"},
        ]
    )

    [(command, params)] = calls
    assert command == "place_objects"
    assert params["objects"] == [
        {
            "asset": "res://a.png",
            "scale": 1.0,
            "rotation": 0.0,
            "sorting": 0,
            "layer": 100,
            "x": 10.0,
            "y": 20.0,
        },
        {
            "asset": "res://b.png",
            "scale": 1.0,
            "rotation": 90.0,
            "sorting": 0,
            "layer": 100,
            "x": 30.0,
            "y": 40.0,
            "color": "#ff8800",
        },
    ]


def test_place_objects_omits_what_was_not_asked_for(calls):
    """An empty colour must not reach the bridge as a colour: place_object
    treats any non-empty `color` as a request to drive ObjectTool."""
    server.place_objects([{"asset": "res://a.png"}])

    [(_, params)] = calls
    assert "color" not in params["objects"][0]
    assert "modulate" not in params["objects"][0]
    assert "block_light" not in params["objects"][0]
    assert "x" not in params["objects"][0] and "y" not in params["objects"][0]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"asset": ""}, "asset path"),
        ({"asset": "a", "scale": 0}, "objects[0].scale"),
        ({"asset": "a", "layer": 150}, "objects[0].layer"),
        ({"asset": "a", "sorting": 2}, "objects[0].sorting"),
        ({"asset": "a", "color": "red"}, "objects[0].color"),
        ({"asset": "a", "modulate": "#gg0000"}, "objects[0].modulate"),
        ({"asset": "a", "x": float("nan")}, "objects[0].x"),
    ],
)
def test_place_objects_names_the_entry_that_is_wrong(calls, entry, expected):
    with pytest.raises(ValidationError) as refused:
        server.place_objects([entry])
    assert expected in str(refused.value)
    assert calls == [], "nothing may reach the bridge when an entry is invalid"


def test_place_objects_refuses_an_oversized_batch(calls):
    with pytest.raises(ValidationError, match="scatter_objects"):
        server.place_objects([{"asset": "a"}] * (server.BATCH_LIMIT + 1))
    assert calls == []


def test_place_objects_refuses_an_empty_batch(calls):
    with pytest.raises(ValidationError):
        server.place_objects([])


def test_delete_elements_is_one_request(calls):
    server.delete_elements([4, 5, 6])
    assert calls == [("delete_elements", {"ids": [4, 5, 6]})]


@pytest.mark.parametrize("ids", [[], [1, -2], [1, True], [1, "2"], [0] * 101])
def test_delete_elements_refuses_what_the_bridge_would_have_to(calls, ids):
    with pytest.raises(ValidationError):
        server.delete_elements(ids)
    assert calls == []


def test_batch_limits_match_the_bridge():
    """The mod caps batches too; a server cap above it would only produce a
    refusal from the far side after the request had crossed the socket."""
    mod = (
        server.Path(__file__).resolve().parents[2]
        / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    ).read_text(encoding="utf-8")
    assert f"const MAX_BATCH_ITEMS := {server.BATCH_LIMIT}" in mod


def test_batch_entry_shape_is_advertised_in_the_schema():
    """A model that cannot see the entry fields has to guess them."""
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    schema = tools["place_objects"].input_schema
    entry = schema["$defs"]["PlacedObject"]
    assert entry["required"] == ["asset"]
    assert entry["additionalProperties"] is False
    assert {"asset", "x", "y", "scale", "rotation", "layer", "color"} <= set(entry["properties"])


def test_an_unknown_entry_field_is_refused_with_its_name():
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(
                "place_objects", {"objects": [{"asset": "a", "rotaton": 90}]}
            )

    result = asyncio.run(run())
    assert result.is_error
    assert "rotaton" in result.content[0].text


@pytest.mark.parametrize("operation", ["place", "batch", "modify"])
def test_persistent_edits_refuse_modulate_before_any_bridge_call(calls, operation):
    with pytest.raises(ValidationError, match="modulate.*sav"):
        if operation == "place":
            server.place_object(asset="a", color="#3366cc", modulate="#ccddff")
        elif operation == "batch":
            server.place_objects([{"asset": "a"}, {"asset": "b", "modulate": "#ccddff"}])
        else:
            server.modify_object(id=1, shadow=False, scale=2, modulate="#ccddff")
    assert calls == []


def test_renderer_preflight_precedes_history_and_batch_mutations():
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    ).read_text(encoding="utf-8")

    def body(name):
        return re.search(r"^func " + name + r"\(.*?(?=^func |\Z)", source, re.M | re.S).group()

    for name, stack in (("_do_undo", "_undo_stack"), ("_do_redo", "_redo_stack")):
        text = body(name)
        assert "_prop_detach_history_error" in text
        assert text.index("_prop_detach_history_error") < text.index(stack + ".pop_back()")
    for name in ("_delete_element", "_delete_elements"):
        text = body(name)
        assert "_prop_detach_error" in text
        assert text.index("_prop_detach_error") < text.index("_detach_node(")
    text = body("_delete_elements")
    assert text.count("for entry in order:") == 2, (
        "all preflight must finish before any batch detach"
    )


def _write(tmp_path, data, name="batch.json"):
    import json

    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_a_file_batch_is_one_compact_request(calls, tmp_path):
    entries = [{"asset": "res://tree.png", "x": i * 10, "y": 5} for i in range(600)]
    server.place_objects(file=_write(tmp_path, entries))
    [(command, params)] = calls
    assert command == "place_objects"
    assert params["compact"] is True
    assert len(params["objects"]) == 600
    assert params["objects"][599]["x"] == 5990.0


def test_a_file_may_wrap_its_entries(calls, tmp_path):
    server.place_objects(file=_write(tmp_path, {"objects": [{"asset": "res://a.png"}]}))
    assert len(calls[0][1]["objects"]) == 1


def test_a_file_batch_is_validated_before_anything_is_sent(calls, tmp_path):
    entries = [{"asset": "res://a.png"}] * 10 + [{"asset": "res://a.png", "layer": 150}]
    with pytest.raises(ValidationError, match=r"objects\[10\]\.layer"):
        server.place_objects(file=_write(tmp_path, entries))
    assert calls == []


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda p: "relative/batch.json", "absolute"),
        (lambda p: _write(p, [], name="batch.txt"), ".json"),
        (lambda p: str(p / "missing.json"), "cannot read"),
        (lambda p: _write(p, {"items": []}), "list of entries"),
        (lambda p: _write(p, [{"asset": "res://a.png"}] * 1001), "past the 1000"),
    ],
)
def test_bad_batch_files_are_refused(calls, tmp_path, make, message):
    with pytest.raises(ValidationError, match=message):
        server.place_objects(file=make(tmp_path))
    assert calls == []


@pytest.mark.parametrize(
    ("given", "hint"),
    [
        ("C:/maps/batch.json", "/mnt/c/maps/batch.json"),
        ("D:\\maps\\batch.json", "/mnt/d/maps/batch.json"),
    ],
)
def test_a_windows_path_on_a_posix_server_names_the_wsl_form(calls, monkeypatch, given, hint):
    monkeypatch.setattr(server, "Path", pathlib.PurePosixPath)
    with pytest.raises(ValidationError, match="absolute") as refused:
        server.place_objects(file=given)
    assert hint in str(refused.value)
    assert calls == []


def test_a_plain_relative_path_gets_no_wsl_hint(calls, monkeypatch):
    monkeypatch.setattr(server, "Path", pathlib.PurePosixPath)
    with pytest.raises(ValidationError, match="absolute") as refused:
        server.place_objects(file="relative/batch.json")
    assert "/mnt/" not in str(refused.value)


def test_objects_and_file_are_exclusive(calls, tmp_path):
    with pytest.raises(ValidationError, match="not both"):
        server.place_objects([{"asset": "res://a.png"}], file=_write(tmp_path, []))


def test_inline_batches_keep_their_cap_of_100(calls):
    with pytest.raises(ValidationError, match="past the 100"):
        server.place_objects([{"asset": "res://a.png"}] * 101)
