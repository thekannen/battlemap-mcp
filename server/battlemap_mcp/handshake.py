"""Keep every connection on the classic `initialize` handshake.

The MCP SDK serves two protocol eras and lets the client's FIRST request pick
one: a `server/discover` carrying the 2026-07-28 envelope opens a modern
connection, `initialize` opens a classic one, and a connection never changes
era afterwards. Claude Code 2.1.277 opens with that discover probe, and when
the companion is slow to start it gives up on the probe and sends
`initialize` instead. The companion then reads the stale discover first,
locks the connection modern, and refuses the `initialize` that follows:
"connection is serving the 2026-07-28 protocol; the initialize handshake is
not accepted". The SDK's own client re-probes on that answer; Claude Code
does not, so the server shows as failed.

A first launch is exactly when the companion is slow: a fresh download or a
freshly unpacked bundle waits while macOS checks every library. Measured on
2026-10-05 (macOS, mcp 2.2.0 and 2.3.0): three of three cold starts failed,
every warm start connected.

So this answers `server/discover` itself, with "method not found", until the
first other request arrives, and passes every other line through untouched.
A client treats that answer as a classic server and sends `initialize`; a
probe it already abandoned is simply ignored. Nothing the companion offers
needs the newer era.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from typing import BinaryIO

DISCOVER = "server/discover"
METHOD_NOT_FOUND = -32601


def _request(line: bytes) -> dict | None:
    try:
        message = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(message, dict) and "method" in message and "id" in message:
        return message
    return None


def refusal(request_id: object) -> bytes:
    """The answer to a discover probe: a classic server, not an error state."""
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": METHOD_NOT_FOUND,
                    "message": f"{DISCOVER} is not served; use the initialize handshake",
                },
            }
        ).encode("utf-8")
        + b"\n"
    )


def relay(
    source: BinaryIO, forward: Callable[[bytes], None], reply: Callable[[bytes], None]
) -> None:
    """Copy `source` to `forward` line by line, answering early discover probes.

    Only requests before the first non-discover one are inspected, so the SDK
    is still the only writer once it has anything to say.
    """
    opened = False
    for line in iter(source.readline, b""):
        if not opened:
            request = _request(line)
            if request is not None and request.get("method") == DISCOVER:
                reply(refusal(request["id"]))
                continue
            if request is not None:
                opened = True
        forward(line)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def install() -> threading.Thread:
    """Put the relay between the process's stdin and the MCP server.

    The real stdin moves to a private descriptor read by a thread; fd 0
    becomes a pipe the server reads. End of input closes the pipe, so the
    server still sees its client leave.
    """
    original = os.dup(0)
    # The SDK points fd 1 at stderr once it starts serving, and writes the wire
    # through its own copy, so a probe answered after that would go nowhere.
    # Keep a copy of the real stdout from before then.
    wire = os.dup(1)
    read_end, write_end = os.pipe()
    os.dup2(read_end, 0)
    os.close(read_end)
    lock = threading.Lock()

    def reply(data: bytes) -> None:
        with lock:
            _write_all(wire, data)

    def run() -> None:
        try:
            with os.fdopen(original, "rb") as source:
                relay(source, lambda data: _write_all(write_end, data), reply)
        except OSError:
            pass
        finally:
            os.close(write_end)

    thread = threading.Thread(target=run, name="handshake-relay", daemon=True)
    thread.start()
    return thread
