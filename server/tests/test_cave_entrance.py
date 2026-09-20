"""Invalid cave entrance requests must never reach the live editor."""

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.mark.parametrize(
    "params",
    [
        {"x": float("nan"), "y": 0},
        {"x": 0, "y": float("inf")},
        {"x": 0, "y": 0, "radius": 0},
        {"x": 0, "y": 0, "radius": -1},
        {"x": 0, "y": 0, "radius": float("nan")},
        {"x": 0, "y": 0, "radius": 2049},
    ],
)
def test_invalid_entrance_never_reaches_editor(monkeypatch, params):
    calls = []
    monkeypatch.setattr(server.bridge, "request", lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(ValidationError):
        server.set_cave_entrance(**params)
    assert calls == []


def test_closing_an_entrance_preserves_false_and_actual_result(monkeypatch):
    calls = []
    observed = {"open": False, "changed_cells": 17}

    def request(command, **params):
        calls.append((command, params))
        return observed

    monkeypatch.setattr(server.bridge, "request", request)
    assert server.set_cave_entrance(256, 512, radius=128, open=False) is observed
    assert calls == [("set_cave_entrance", {"x": 256, "y": 512, "radius": 128, "open": False})]
    server.get_cave()
    assert calls[-1] == ("get_cave", {})
