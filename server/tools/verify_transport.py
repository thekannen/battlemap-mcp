#!/usr/bin/env python3
"""Bounded adversarial checks against an explicitly named disposable live map.

Uses at most one extra socket, 1 KiB of blank frames, and a six-second keepalive.
Run separately from other live suites: python tools/verify_transport.py --port N --map uat-...
No token, request bodies, local paths, or raw responses are printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from battlemap_mcp.bridge_client import BridgeClient  # noqa: E402


def send(peer, value):
    peer.sendall(json.dumps(value).encode() + b"\n")


def read(peer):
    data = bytearray()
    while not data.endswith(b"\n"):
        part = peer.recv(1)
        if not part:
            raise EOFError
        data.extend(part)
    return json.loads(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map", required=True)
    args = parser.parse_args()
    assert pathlib.Path(args.map).name.startswith("uat-")
    client = BridgeClient(port=args.port, timeout=6)
    status = client.request("get_status")
    assert pathlib.Path(status["map_file"]).name == pathlib.Path(args.map).name
    source = (
        pathlib.Path(__file__).resolve().parents[2]
        / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"
    )
    assert (
        client.request("ping")["bridge_sha256"]
        == hashlib.sha256(source.read_bytes().replace(b"\r", b"")).hexdigest()
    )

    def connect():
        return socket.create_connection(("127.0.0.1", args.port), timeout=6)

    identity = client.request("ping")
    assert pathlib.Path(identity["bridge_root"]).is_absolute()
    assert type(identity["process_id"]) is int and identity["process_id"] > 0
    with connect() as peer:
        send(peer, {"cmd": "ping"})
        diagnostic = read(peer)["result"]
        assert diagnostic["pong"] is True
        assert "bridge_root" not in diagnostic and "process_id" not in diagnostic
    print("PASS runtime location requires authenticated ping")

    def handshake(peer):
        return client._handshake(peer, time.monotonic() + 5)

    def envelope(nonces, body):
        return {
            "seq": 1,
            "payload": body,
            "auth": client._message_proof(client.token, "request", *nonces, body),
        }

    with connect() as peer:
        nonces = handshake(peer)
        original = envelope(nonces, json.dumps({"cmd": "get_status"}))
        altered = {**original, "payload": json.dumps({"cmd": "ping"})}
        send(peer, altered)
        assert read(peer).get("ok") is False
        send(peer, original)
        assert client._verify_response(read(peer), nonces)["ok"] is True
    print("PASS modified payload rejected; original request still verifies")

    with connect() as peer:
        nonces = handshake(peer)
        send(peer, original)
        assert read(peer).get("ok") is False
    print("PASS request replay across connections rejected")

    with connect() as peer:
        nonces = handshake(peer)
        body = json.dumps({"cmd": "synthetic-é漢字\n\u0000"}, ensure_ascii=False)
        frame = (json.dumps(envelope(nonces, body), ensure_ascii=False) + "\n").encode()
        # Split inside a multi-byte character, across editor updates.
        split = frame.index("é".encode()) + 1
        peer.sendall(frame[:split])
        time.sleep(0.08)
        peer.sendall(frame[split:] + frame)
        response = client._verify_response(read(peer), nonces)
        assert response["ok"] is False and "é漢字" in response["error"]
        assert peer.recv(1) == b"", "pipelined duplicate was not consumed with the session"
    print("PASS split UTF-8 and NUL round trip; pipelined duplicate receives no second response")

    for frame in (b"\n", b" \t\n"):
        with connect() as peer:
            started = time.monotonic()
            peer.sendall(frame * 256 + b'{"cmd":"ping"}\n')
            assert read(peer)["ok"] is True
            elapsed = time.monotonic() - started
            # 128 updates at the two-frame allowance. A generous threshold
            # permits up to 512 updates/s; the old unbudgeted loop was immediate.
            assert elapsed >= 0.25, "blank frames bypassed the frame allowance"
            print(f"PASS blank-frame allowance: 256 frames drained in {elapsed:.3f}s")

    with connect() as peer:
        started = time.monotonic()
        handshake(peer)
        peer.settimeout(0.15)
        closed = False
        while time.monotonic() - started < 6:
            try:
                peer.sendall(b" \n")
                if peer.recv(1) == b"":
                    closed = True
                    break
            except TimeoutError:
                pass
            except (ConnectionResetError, BrokenPipeError):
                closed = True
                break
        elapsed = time.monotonic() - started
        assert closed and 4.5 <= elapsed < 6, "hello/keepalive bypassed the absolute deadline"
    print(f"PASS unauthenticated hello plus keepalive closed after {elapsed:.3f}s")
    assert client.request("ping")["pong"]
    print("7/7 transport checks passed; bridge remains responsive")


if __name__ == "__main__":
    main()
