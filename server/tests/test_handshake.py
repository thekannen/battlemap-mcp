"""Runtime behavior and validation."""

import io
import json
import os
import subprocess
import sys

import pytest

from battlemap_mcp import handshake

# Claude Code 2.1.277's opening probe, as captured from its stdin.
DISCOVER = {
    "jsonrpc": "2.0",
    "id": "probe-1",
    "method": "server/discover",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "claude-code", "version": "2.1.277"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    },
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "cold-start", "version": "1"},
    },
}


def lines(*messages):
    return b"".join(json.dumps(m).encode() + b"\n" for m in messages)


def test_discover_before_initialize_is_answered_not_forwarded():
    forwarded, replied = [], []
    later_discover = dict(DISCOVER, id="probe-2")
    handshake.relay(
        io.BytesIO(lines(DISCOVER, INITIALIZE, later_discover)),
        forwarded.append,
        replied.append,
    )
    assert [json.loads(r)["id"] for r in replied] == ["probe-1"]
    assert json.loads(replied[0])["error"]["code"] == handshake.METHOD_NOT_FOUND
    # Everything after the first real request passes untouched, discover included.
    assert [json.loads(f)["id"] for f in forwarded] == [1, "probe-2"]


def test_notifications_and_noise_pass_through():
    forwarded = []
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    handshake.relay(io.BytesIO(lines(notification) + b"not json\n"), forwarded.append, None)
    assert len(forwarded) == 2


def test_a_stale_probe_no_longer_locks_out_initialize(tmp_path):
    """What a cold start looks like: the probe and initialize already queued."""
    env = {**os.environ, "BATTLEMAP_MCP_UPDATE_CHECK": "0", "HOME": str(tmp_path)}
    process = subprocess.run(
        [sys.executable, "-m", "battlemap_mcp"],
        input=lines(DISCOVER, INITIALIZE),
        capture_output=True,
        timeout=60,
        env=env,
    )
    replies = {r["id"]: r for r in map(json.loads, process.stdout.splitlines())}
    assert replies["probe-1"]["error"]["code"] == handshake.METHOD_NOT_FOUND
    assert "serverInfo" in replies[1]["result"], replies[1]


@pytest.mark.skipif(sys.platform == "win32", reason="select() cannot wait on a pipe on Windows")
def test_a_waiting_client_gets_its_answer_before_sending_initialize(tmp_path):
    """A warm start: the client waits for the probe's answer, then falls back.

    The SDK points fd 1 at stderr once it is serving, so an answer written to
    fd 1 then never reaches the client, which waits out its probe timeout.
    """
    import select

    env = {**os.environ, "BATTLEMAP_MCP_UPDATE_CHECK": "0", "HOME": str(tmp_path)}
    process = subprocess.Popen(
        [sys.executable, "-m", "battlemap_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        import time

        time.sleep(1.5)  # let the SDK start serving first, as on a warm start
        process.stdin.write(lines(DISCOVER))
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "no answer to the probe: the client would wait out its timeout"
        answer = json.loads(process.stdout.readline())
        assert answer["id"] == "probe-1" and answer["error"]["code"] == handshake.METHOD_NOT_FOUND
        process.stdin.write(lines(INITIALIZE))
        process.stdin.flush()
        assert "serverInfo" in json.loads(process.stdout.readline())["result"]
    finally:
        process.kill()
        process.wait(timeout=10)
