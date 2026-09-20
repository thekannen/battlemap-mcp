"""Batch placement and deletion: what reaches the bridge, and what is refused.

The engine behaviour (one undo step, rollback, the frame budget) belongs to the
UAT — it can only be observed in a running editor. These cover the half that is
knowable offline: validation, caps, and the exact request the bridge receives.
"""

from __future__ import annotations

import asyncio

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
