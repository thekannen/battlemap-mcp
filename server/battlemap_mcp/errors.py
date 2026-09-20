"""Error types for the Dungeondraft MCP bridge.

The split matters for diagnosis: a validation failure never touched the socket,
an unavailable bridge means Dungeondraft is closed or the mod crashed, and a
command error means the bridge ran and refused.

Every one of them is a `ToolError`, and that is not decoration. The MCP SDK
treats a `ToolError` as an anticipated failure and sends its message to the
model; anything else is treated as a crash, logged server-side, and reported to
the model as the bare string "Error executing tool <name>". These classes
subclassed plain Exception, so every refusal this package writes — "no level
with id 4242; known ids: [0]", "no such category", "'points' needs >= 2 [x,y]
pairs", the whole save-in-flight explanation — was discarded at the boundary
and the model was told nothing.

Measured, not assumed: across 18 eval runs and 839 tool calls, all 15 failures
returned "Error executing tool <name>" and nothing more. A model that guessed
an asset path was never told the path was bad, so it guessed again.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError


class DungeondraftMCPError(ToolError):
    """Base for every error this package raises.

    A ToolError so the message reaches the model. See the module docstring.
    """


SECRET_FIELDS = frozenset({"token", "auth", "authorization", "password", "secret"})


def redact_secrets(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """A copy of `payload` with any credential field masked."""
    if not isinstance(payload, dict):
        return payload
    return {
        key: ("<redacted>" if str(key).lower() in SECRET_FIELDS else value)
        for key, value in payload.items()
    }


class ValidationError(DungeondraftMCPError):
    """Rejected before sending. Never reached the socket."""


class BridgeUnavailableError(DungeondraftMCPError):
    """Could not reach the bridge.

    `last_command` is the payload sent immediately before the socket went dead.
    When the mod crashes mid-session that payload is the prime suspect, so it is
    surfaced in the message rather than left for the reader to reconstruct.
    """

    def __init__(self, message: str, last_command: dict[str, Any] | None = None):
        self.last_command = redact_secrets(last_command)
        if self.last_command is not None:
            message = f"{message} (bridge died after {self.last_command})"
        super().__init__(message)


class BridgePeerUntrustedError(DungeondraftMCPError):
    """Something answered on the bridge port but could not prove it knows the token.

    This can be raised while verifying either the pre-command handshake or a
    post-command response envelope. Callers must not retry the latter because
    the command may already have executed.
    """


class BridgeHandshakeUntrustedError(BridgePeerUntrustedError):
    """The peer failed the pre-command proof, so no command was sent."""


class BridgeProtocolError(DungeondraftMCPError):
    """Connected, but the response was empty or unparseable."""


class BridgeCommandError(DungeondraftMCPError):
    """The bridge ran the command and returned ok:false."""

    def __init__(self, message: str, cmd: str = "", params: dict[str, Any] | None = None):
        self.cmd = cmd
        self.params = params or {}
        super().__init__(message)


# Retained so existing `except BridgeError` sites keep working.
BridgeError = DungeondraftMCPError
