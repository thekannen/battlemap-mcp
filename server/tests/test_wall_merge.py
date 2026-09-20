"""Typed wall merge boundary validation; geometry is exercised by live UAT."""

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.mark.parametrize("ids", [[], [1], [1, 1], [1, 2, 3], [-1, 2], [True, 2], [1.5, 2]])
def test_invalid_wall_pairs_never_reach_bridge(monkeypatch, ids):
    calls = []
    monkeypatch.setattr(server.bridge, "request", lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(ValidationError):
        server.merge_walls(ids)
    assert calls == []


def test_survivor_order_is_preserved(monkeypatch):
    calls = []
    monkeypatch.setattr(server.bridge, "request", lambda *a, **kw: calls.append((a, kw)))
    server.merge_walls([8, 3])
    assert calls == [(("merge_walls",), {"ids": [8, 3]})]
