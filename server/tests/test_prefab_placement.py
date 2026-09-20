"""\"Tavern Tables\" landed near the map's top-left corner, half outside the building,
and moving its 110 pieces took 108 calls and evicted the whole undo history.
"""

import asyncio

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def request(cmd, **params):
        seen.append((cmd, params))
        return {}

    monkeypatch.setattr(server.bridge, "request", request)
    return seen


def test_place_prefab_forwards_the_position(calls):
    server.place_prefab("Tavern Tables", x=2048, y=1536, rotation=90)
    assert calls == [
        ("place_prefab", {"name": "Tavern Tables", "x": 2048, "y": 1536, "rotation": 90})
    ]


def test_place_prefab_without_a_position_sends_what_it_always_did(calls):
    server.place_prefab("Tavern Tables")
    assert calls == [("place_prefab", {"name": "Tavern Tables"})]


def test_place_prefab_refuses_half_a_position(calls):
    with pytest.raises(ValidationError, match="both x and y"):
        server.place_prefab("Tavern Tables", x=2048)
    assert calls == []


def test_the_model_is_told_to_position_a_prefab():
    """The description is what the model reads before it calls this."""
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert "ALWAYS pass x and y" in tools["place_prefab"].description


def test_move_elements_is_one_request(calls):
    server.move_elements([4, 5, 6], dx=256, dy=-128)
    assert calls == [("move_elements", {"ids": [4, 5, 6], "dx": 256, "dy": -128})]


@pytest.mark.parametrize("ids", [[], list(range(1001))], ids=["empty", "over-cap"])
def test_move_elements_refuses_out_of_bounds_batches(calls, ids):
    with pytest.raises(ValidationError):
        server.move_elements(ids, dx=1, dy=1)
    assert calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"dx": float("nan"), "dy": 0},
        {"dx": 0, "dy": float("inf")},
        {"dx": 0, "dy": 0, "rotation": float("nan")},
        {"dx": 0, "dy": 0, "pivot_x": 100},
        {"dx": 0, "dy": 0, "pivot_x": 100, "pivot_y": float("inf")},
    ],
)
def test_group_transform_validation_precedes_bridge(calls, params):
    with pytest.raises(ValidationError):
        server.move_elements([4, 5], **params)
    assert calls == []


def test_group_rotation_and_pivot_are_one_request(calls):
    server.move_elements([4, 5], 256, 128, rotation=90, pivot_x=0, pivot_y=0)
    assert calls == [
        (
            "move_elements",
            {"ids": [4, 5], "dx": 256, "dy": 128, "rotation": 90, "pivot_x": 0, "pivot_y": 0},
        )
    ]
