"""set_grid: show or hide the editor grid."""

from __future__ import annotations

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def request(command, **params):
        calls.append((command, params))
        return {"grid_visible": params.get("visible"), "grid_toggle": params.get("visible")}

    monkeypatch.setattr(server.bridge, "request", request)
    return calls


def test_set_grid_sends_visible(sent):
    assert server.set_grid(False) == {"grid_visible": False, "grid_toggle": False}
    assert sent == [("set_grid", {"visible": False})]


def test_set_grid_docstring_says_it_is_not_saved():
    doc = server.set_grid.__doc__ or ""
    assert "View menu" in doc and "not saved" in doc


@pytest.mark.parametrize("bad", ["no", 0, None])
def test_set_grid_rejects_non_bool(sent, bad):
    with pytest.raises(ValidationError):
        server.set_grid(bad)
    assert sent == []
