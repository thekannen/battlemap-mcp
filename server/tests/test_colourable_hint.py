"""Colourable objects: name Dungeondraft's default colour, but never apply it unasked.

Applying #6b3834 to every uncoloured colourable placement was measured at about
twice the time for 100 placements, with an ArgumentNullException logged per
object, and it took away the model's cue to choose a fitting colour.
"""

from __future__ import annotations

import pytest

from battlemap_mcp import server


@pytest.mark.parametrize("tool", [server.place_object, server.place_objects])
def test_docstring_names_the_default_as_a_fallback(tool):
    doc = tool.__doc__ or ""
    assert "#6b3834" in doc
    assert "if nothing fits better" in doc


def test_place_object_sends_no_colour_unasked(monkeypatch):
    sent: list[dict] = []

    def request(command, **params):
        sent.append(params)
        return {"id": 1}

    monkeypatch.setattr(server.bridge, "request", request)
    server.place_object(asset="res://textures/objects/decor/floor/carpet_01.png", x=0, y=0)
    assert all("color" not in params for params in sent), sent
