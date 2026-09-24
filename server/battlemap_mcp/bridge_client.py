"""Thin TCP client for the Dungeondraft MCP bridge mod.

Each request opens a short-lived connection, verifies a challenge, then sends
one authenticated request and verifies its response. See PROTOCOL.md.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import socket
import sys
import time
from typing import Any

from . import timing
from .errors import (
    BridgeCommandError,
    BridgeError,
    BridgeHandshakeUntrustedError,
    BridgePeerUntrustedError,
    BridgeProtocolError,
    BridgeUnavailableError,
)
from .state_paths import state_dir

# Protocol 25 authenticates complete messages, not just connection nonces.
PROTOCOL_VERSION = 25
MAX_HELLO_BYTES = 16384
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# The mod binds this first and walks upward only if it is taken; see _resolve_port.
DEFAULT_PORT = 8787

# What the mod answers when the token does not match. Matched as a substring so
# the mod can add context to the message without breaking the retry.
TOKEN_REJECTED = "bad or missing token"

__all__ = [
    "BridgeClient",
    "BridgeError",
    "BridgeCommandError",
    "BridgePeerUntrustedError",
    "BridgeProtocolError",
    "BridgeUnavailableError",
]


def _state_file(name: str, *, _platform: str | None = None) -> pathlib.Path:
    """Integration-owned state; never fall back to Dungeondraft's shared root."""
    return state_dir(_platform=_platform if _platform is not None else sys.platform) / name


def _resolve_token() -> str:
    """Read the shared token the mod wrote at startup.

    A missing file is a loud failure, never a silent fall back to an
    unauthenticated request: the protection has to fail visibly or it quietly
    disappears the first time something moves.
    """
    override = os.environ.get("BATTLEMAP_MCP_TOKEN_FILE")
    path = pathlib.Path(override) if override else _state_file("mcp_bridge_token")
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BridgeUnavailableError(
            f"Could not read the bridge token at {path}. Start Dungeondraft with "
            f"the Battlemap MCP Bridge mod enabled — it writes this file at startup. ({exc})"
        ) from exc
    if not token:
        raise BridgeUnavailableError(f"Bridge token file is empty: {path}")
    return token


def _resolve_port() -> int:
    """Find the port the live mod instance bound.

    Opening a map orphans the previous instance's listener on its port (see
    start() in the mod), so the newest instance walks to the next free one and
    writes it here. A missing or unreadable file is not an error — it just means
    the default, which is right for the common case of a single map opened since
    launch, and for any mod older than protocol 19.
    """
    override = os.environ.get("BATTLEMAP_MCP_PORT")
    if override:
        return int(override)
    try:
        return int(_state_file("mcp_bridge_port").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return DEFAULT_PORT


BUSY_HINT = (
    "Dungeondraft appears to be running but not answering: a map may still be "
    "loading, a dialog may be open in the editor, or a load may have hung. "
    "Check the Dungeondraft window before restarting it. "
)
# Kept at module level: nested in the request below, a longer bridge name
# pushed this line past the length limit.
NOT_RUNNING_HINT = (
    "Is Dungeondraft running with the Battlemap MCP Bridge mod enabled and a map open? "
)


class BridgeClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        timeout: float = 5.0,
        token: str | None = None,
    ):
        self.host = host
        self._explicit_port = port
        self.timeout = timeout
        self._explicit_token = token

    @functools.cached_property
    def port(self) -> int:
        """Resolve the port on first use, for the same reason as `token`: the
        MCP server constructs a client at import time, before the mod has
        written the file that says where it is listening."""
        return self._explicit_port if self._explicit_port is not None else _resolve_port()

    @functools.cached_property
    def token(self) -> str:
        """Resolve the bridge token on first use, not at construction time.

        Constructing a `BridgeClient` must never touch the filesystem: the MCP
        server builds one at module import time, before Dungeondraft (and the
        mod that writes the token file) has necessarily started. Deferring
        resolution to first access means the loud failure in `_resolve_token`
        still happens — just on first `request()` instead of on import.
        """
        return self._explicit_token if self._explicit_token is not None else _resolve_token()

    def request(self, cmd: str, **params: Any) -> dict:
        """Send one command; safely refresh changed local connection settings.

        The token is cached for the client's lifetime, and the MCP server holds
        one client for the life of the process — so if Dungeondraft ever writes
        a new token file (a fresh install, a wiped user directory, a future
        rotation), every later call would fail with "bad or missing token" and
        stay failing until the server was restarted. Re-reading the file once on
        rejection costs nothing and turns that dead end into a hiccup.
        """
        try:
            return self._request(cmd, **params)
        except BridgeCommandError as exc:
            if TOKEN_REJECTED not in str(exc):
                raise
            self.__dict__.pop("token", None)  # drop the cached_property value
            return self._request(cmd, **params)
        except BridgeHandshakeUntrustedError:
            changed = False
            if self._explicit_port is None:
                previous_port = self.__dict__.pop("port", None)
                changed = previous_port is not None and self.port != previous_port
            if self._explicit_token is None:
                previous_token = self.__dict__.pop("token", None)
                changed = (previous_token is not None and self.token != previous_token) or changed
            if not changed:
                raise
            return self._request(cmd, **params)
        except BridgeUnavailableError as exc:
            if self._explicit_port is not None or exc.last_command is not None:
                raise
            if "port" not in self.__dict__:
                raise
            stale = self.__dict__.pop("port")
            if self.port == stale:
                raise
            return self._request(cmd, **params)

    @staticmethod
    def _proof(token: str, role: str, client_nonce: str, server_nonce: str) -> str:
        message = f"{PROTOCOL_VERSION}|{role}|{client_nonce}|{server_nonce}"
        return hmac.new(
            token.encode("utf-8"), f"dd-mcp/{message}".encode(), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _message_proof(
        token: str, role: str, client_nonce: str, server_nonce: str, payload: str
    ) -> str:
        # One command per connection, sequence 1. The final field is the exact
        # serialized payload, so Python and Godot need no JSON canonicalizer.
        message = f"dd-mcp/{PROTOCOL_VERSION}|{role}|{client_nonce}|{server_nonce}|1|{payload}"
        return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _remaining(sock: socket.socket, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("bridge request deadline exceeded")
        sock.settimeout(remaining)

    def _handshake(self, sock: socket.socket, deadline: float) -> tuple[str, str]:
        client_nonce = secrets.token_hex(16)
        hello = {"cmd": "hello", "protocol": PROTOCOL_VERSION, "nonce": client_nonce}
        self._remaining(sock, deadline)
        sock.sendall((json.dumps(hello) + "\n").encode())
        answer = self._read_line(sock, payload=None, deadline=deadline, limit=MAX_HELLO_BYTES)
        if not answer.get("ok"):
            raise BridgeProtocolError(
                f"The bridge refused the protocol {PROTOCOL_VERSION} handshake. "
                "The mod is probably older than this package — reinstall the "
                "bridge mod and restart Dungeondraft."
            )
        result = answer.get("result")
        if not isinstance(result, dict):
            raise BridgeProtocolError("Invalid bridge handshake result")
        server_nonce = result.get("nonce")
        proof = result.get("proof")
        if (
            result.get("protocol") != PROTOCOL_VERSION
            or not isinstance(server_nonce, str)
            or len(server_nonce) != 32
            or any(c not in "0123456789abcdef" for c in server_nonce)
            or not isinstance(proof, str)
            or not proof.isascii()
            or not hmac.compare_digest(
                proof, self._proof(self.token, "server", client_nonce, server_nonce)
            )
        ):
            raise BridgeHandshakeUntrustedError(
                "The peer could not prove it knows the bridge token; the command was not sent."
            )
        return client_nonce, server_nonce

    def _read_line(
        self,
        sock: socket.socket,
        payload: dict | None,
        *,
        deadline: float,
        limit: int = MAX_RESPONSE_BYTES,
    ) -> dict:
        buf = bytearray()
        while True:
            self._remaining(sock, deadline)
            chunk = sock.recv(min(65536, limit + 1 - len(buf)))
            if not chunk:
                if not buf:
                    raise BridgeUnavailableError(
                        "The bridge sent no response.", last_command=payload
                    )
                raise BridgeProtocolError("Bridge response ended before its newline")
            newline = chunk.find(b"\n")
            buf.extend(chunk if newline < 0 else chunk[:newline])
            if len(buf) > limit:
                raise BridgeProtocolError("Bridge response exceeded the byte limit")
            if newline >= 0:
                break
        try:
            result = json.loads(buf.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise BridgeProtocolError("Unparseable response from bridge") from exc
        if not isinstance(result, dict):
            raise BridgeProtocolError("Bridge response must be a JSON object")
        return result

    def _verify_response(self, envelope: dict, nonces: tuple[str, str]) -> dict:
        body = envelope.get("payload")
        proof = envelope.get("auth")
        if (
            envelope.get("seq") != 1
            or not isinstance(body, str)
            or not isinstance(proof, str)
            or not proof.isascii()
            or not hmac.compare_digest(
                proof, self._message_proof(self.token, "response", *nonces, body)
            )
        ):
            raise BridgePeerUntrustedError(
                "Bridge response authentication failed; "
                "the command may have executed and was not retried."
            )
        try:
            result = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise BridgeProtocolError("Invalid authenticated response") from exc
        if not isinstance(result, dict):
            raise BridgeProtocolError("Authenticated response must be an object")
        return result

    def _request(self, cmd: str, **params: Any) -> dict:
        started = time.perf_counter()
        received = [0]
        try:
            return self._exchange(cmd, params, received)
        finally:
            timing.bridge_request(time.perf_counter() - started, received[0])

    def _exchange(self, cmd: str, params: dict[str, Any], received: list[int]) -> dict:
        payload = {"cmd": cmd, **params}
        deadline = time.monotonic() + self.timeout

        # Connecting and talking are separated so the two failures stay
        # distinguishable. Wrapping both in one `except OSError` made every
        # socket error look like a connect failure, including a recv timeout or
        # a reset — and request() then re-resolved the port and SENT THE
        # COMMAND AGAIN. A mutation that may already have executed was replayed.
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            # Nothing was sent. Safe for request() to re-resolve and retry.
            raise BridgeUnavailableError(
                f"Could not reach the Dungeondraft MCP bridge on {self.host}:{self.port}. "
                + (BUSY_HINT if isinstance(exc, TimeoutError) else NOT_RUNNING_HINT)
                + f"({exc})"
            ) from exc

        # Set the moment the command could have reached the mod. A failure
        # before that point cannot have executed anything, so request() is free
        # to re-resolve the port and try again; after it, a replay could run a
        # mutation twice, and last_command is what forbids that.
        command_sent = False
        try:
            with sock:
                nonces = self._handshake(sock, deadline)
                body = json.dumps(payload, ensure_ascii=False)
                auth = self._message_proof(self.token, "request", *nonces, body)
                data = (json.dumps({"payload": body, "seq": 1, "auth": auth}) + "\n").encode()
                self._remaining(sock, deadline)
                command_sent = True
                sock.sendall(data)
                envelope = self._read_line(sock, payload=payload, deadline=deadline)
                received[0] = len(str(envelope.get("payload", "")).encode("utf-8"))
                resp = self._verify_response(envelope, nonces)
        except OSError as exc:
            if not command_sent:
                raise BridgeUnavailableError(
                    f"The bridge stopped responding on {self.host}:{self.port} during the "
                    f"handshake ({exc}); the command was never sent. {BUSY_HINT}"
                ) from exc
            # The request is ALREADY on the wire. A timeout or a reset says
            # nothing about whether the mod ran it, so this carries
            # last_command, which is what stops request() replaying it.
            raise BridgeUnavailableError(
                f"The bridge stopped responding on {self.host}:{self.port} after the "
                f"request was sent ({exc}); it may or may not have been executed.",
                last_command=payload,
            ) from exc

        if not resp.get("ok"):
            raise BridgeCommandError(
                resp.get("error", "unknown bridge error"), cmd=cmd, params=params
            )
        return resp.get("result", {})
