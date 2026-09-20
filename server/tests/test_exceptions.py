"""Exception hierarchy and crash attribution."""

import pytest

from battlemap_mcp.errors import (
    BridgeCommandError,
    BridgeError,
    BridgeProtocolError,
    BridgeUnavailableError,
    DungeondraftMCPError,
    ValidationError,
)


@pytest.mark.parametrize(
    "cls",
    [ValidationError, BridgeUnavailableError, BridgeProtocolError, BridgeCommandError],
)
def test_all_derive_from_base(cls):
    assert issubclass(cls, DungeondraftMCPError)


def test_bridge_error_is_the_base_alias():
    assert BridgeError is DungeondraftMCPError


def test_unavailable_carries_the_last_command():
    err = BridgeUnavailableError("gone", last_command={"cmd": "draw_wall", "points": []})
    assert err.last_command["cmd"] == "draw_wall"
    assert "draw_wall" in str(err)


def test_unavailable_without_a_last_command():
    err = BridgeUnavailableError("never connected")
    assert err.last_command is None
    assert str(err) == "never connected"


def test_command_error_carries_cmd_and_params():
    err = BridgeCommandError("no map open", cmd="place_object", params={"x": 1})
    assert err.cmd == "place_object"
    assert err.params == {"x": 1}
