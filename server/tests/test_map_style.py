"""Validate complete map-style requests before any bridge mutation."""

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"building_wear": ""},
        {"building_wear": "rust"},
        {"building_wear": "grime", "grid_style": "square"},
        {"grid_style": ""},
        {"grid_style": "hex"},
    ],
)
def test_invalid_style_never_reaches_editor(monkeypatch, params):
    calls = []
    monkeypatch.setattr(server.bridge, "request", lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(ValidationError):
        server.set_map_style(**params)
    assert calls == []


def test_omitted_style_is_not_sent_and_readback_is_preserved(monkeypatch):
    calls = []
    observed = {"building_wear": "none", "grid_style": "dotted", "grid_texture": "actual"}

    def request(command, **params):
        calls.append((command, params))
        return observed

    monkeypatch.setattr(server.bridge, "request", request)
    assert server.set_map_style(building_wear="none") is observed
    assert calls == [("set_map_style", {"building_wear": "none"})]
    assert server.get_map_style() is observed
    assert calls[-1] == ("get_map_style", {})
