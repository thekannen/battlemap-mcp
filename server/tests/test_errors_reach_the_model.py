"""Every error this package raises must reach the model, not just the log.

The MCP SDK sends a ToolError's message to the caller and treats anything else
as a crash: it logs the traceback server-side and tells the model only
"Error executing tool <name>". These classes subclassed plain Exception, so
every refusal the package writes was discarded at that boundary.

Measured before the fix: across 18 eval runs and 839 MCP calls, all 15 failures
returned the bare string. A model that guessed an asset path was never told the
path was bad, so it guessed again — three times in one run.
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from battlemap_mcp.errors import (
    BridgeCommandError,
    BridgeProtocolError,
    BridgeUnavailableError,
    DungeondraftMCPError,
    ValidationError,
)

EVERY_ERROR = (
    DungeondraftMCPError,
    ValidationError,
    BridgeUnavailableError,
    BridgeProtocolError,
    BridgeCommandError,
)


@pytest.mark.parametrize("cls", EVERY_ERROR)
def test_is_a_tool_error(cls):
    assert issubclass(cls, ToolError), (
        f"{cls.__name__} is not a ToolError, so the SDK treats it as a crash "
        f"and the model is told only 'Error executing tool <name>'"
    )


@pytest.mark.parametrize("cls", EVERY_ERROR)
def test_keeps_its_message(cls):
    assert "known ids: [0]" in str(cls("no level with id 4242; known ids: [0]"))


def test_bridge_unavailable_still_names_the_killing_payload():
    exc = BridgeUnavailableError("bridge died", last_command={"cmd": "set_level"})
    assert "set_level" in str(exc)


def test_bridge_command_error_still_carries_its_command():
    exc = BridgeCommandError("refused", cmd="add_light", params={"x": 1})
    assert exc.cmd == "add_light"
    assert exc.params == {"x": 1}
