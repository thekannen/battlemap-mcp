"""set_trace_image position: put the trace image where its grid lines up."""

from __future__ import annotations

import math

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def request(command, **params):
        calls.append((command, params))
        return {"position": params.get("position", [0, 0])}

    monkeypatch.setattr(server.bridge, "request", request)
    return calls


def trace_params(sent):
    [(command, params)] = sent
    assert command == "set_trace_image"
    return params


def test_position_is_sent_in_woxels(sent):
    server.set_trace_image(position=[1953.3, 2114.6])
    assert trace_params(sent)["position"] == [1953.3, 2114.6]


# Models retry calls: a position, unlike a relative offset, lands in the same
# place however many times it is sent.
def test_repeating_a_position_sends_the_same_request(sent):
    server.set_trace_image(position=[100.0, 200.0])
    server.set_trace_image(position=[100.0, 200.0])
    assert sent[0] == sent[1]


def test_position_omitted_when_not_given(sent):
    server.set_trace_image(scale=2.0)
    assert "position" not in trace_params(sent)


def test_position_alone_is_accepted(sent):
    server.set_trace_image(position=[10.0, 20.0])
    assert trace_params(sent) == {"position": [10.0, 20.0]}


def test_position_goes_with_center_in_one_call(sent):
    server.set_trace_image(center=True, position=[10.0, 20.0])
    assert trace_params(sent) == {"center": True, "position": [10.0, 20.0]}


@pytest.mark.parametrize("bad", [[math.nan, 0.0], [0.0, math.inf]])
def test_position_must_be_finite(sent, bad):
    with pytest.raises(ValidationError, match="position"):
        server.set_trace_image(position=bad)
    assert sent == []


@pytest.mark.parametrize("bad", [[1.0], [1.0, 2.0, 3.0]])
def test_position_needs_two_numbers(sent, bad):
    with pytest.raises(ValidationError, match="position"):
        server.set_trace_image(position=bad)
    assert sent == []


def test_relative_offsets_are_gone():
    with pytest.raises(TypeError):
        server.set_trace_image(offset_x=10.0)  # type: ignore[call-arg]
