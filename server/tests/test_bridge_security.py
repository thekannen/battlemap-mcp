"""Adversarial peers and relays; all sockets and secrets are synthetic."""

import contextlib
import json
import socket
import threading
import time

import pytest

from battlemap_mcp.bridge_client import MAX_HELLO_BYTES, BridgeClient
from battlemap_mcp.errors import (
    BridgePeerUntrustedError,
    BridgeProtocolError,
    BridgeUnavailableError,
)


def read_frame(sock):
    data = bytearray()
    while not data.endswith(b"\n"):
        part = sock.recv(1)
        if not part:
            raise EOFError
        data.extend(part)
    return bytes(data)


def send_frame(sock, body):
    sock.sendall(json.dumps(body).encode() + b"\n")


@contextlib.contextmanager
def endpoint(handler):
    errors = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)

        def serve():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(2)
                    handler(peer)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass  # clients deliberately refuse hostile replies
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            yield listener.getsockname()[1]
        finally:
            worker.join(3)
            assert not worker.is_alive()
            assert not errors, errors


def relay(peer, backend_port, change_request=lambda x: x, change_response=lambda x: x):
    with socket.create_connection(("127.0.0.1", backend_port), timeout=2) as backend:
        backend.sendall(read_frame(peer))
        peer.sendall(read_frame(backend))  # relay the real server's proof unchanged
        send_frame(backend, change_request(json.loads(read_frame(peer))))
        try:
            response = json.loads(read_frame(backend))
        except EOFError:
            return
        send_frame(peer, change_response(response))


def test_relay_cannot_substitute_a_command(fake_bridge):
    def replace(envelope):
        envelope["payload"] = json.dumps({"cmd": "synthetic_mutation"})
        return envelope

    with endpoint(lambda peer: relay(peer, fake_bridge.port, change_request=replace)) as port:
        with pytest.raises(BridgeUnavailableError):
            BridgeClient(port=port, token="t").request("get_status")
    assert fake_bridge.received == [], "altered command reached dispatch"


@pytest.mark.parametrize("attack", ["payload", "unsigned", "sequence", "reflection"])
def test_relay_cannot_forge_a_response(fake_bridge, attack):
    def replace(envelope):
        if attack == "payload":
            envelope["payload"] = json.dumps({"ok": True, "result": {"forged": True}})
        elif attack == "unsigned":
            return {"ok": True, "result": {"forged": True}}
        elif attack == "sequence":
            envelope["seq"] = 2
        else:
            return fake_bridge.envelopes[-1]  # a valid request MAC is not a response MAC
        return envelope

    with endpoint(lambda peer: relay(peer, fake_bridge.port, change_response=replace)) as port:
        with pytest.raises(BridgePeerUntrustedError):
            BridgeClient(port=port, token="t").request("get_status")
    assert len(fake_bridge.received) == 1, "untrusted response caused a retry"


def test_response_from_another_connection_is_rejected(fake_bridge):
    captured = []

    def save(envelope):
        captured.append(envelope)
        return envelope

    with endpoint(lambda peer: relay(peer, fake_bridge.port, change_response=save)) as port:
        BridgeClient(port=port, token="t").request("get_status")
    with endpoint(
        lambda peer: relay(peer, fake_bridge.port, change_response=lambda _: captured[0])
    ) as port:
        with pytest.raises(BridgePeerUntrustedError):
            BridgeClient(port=port, token="t").request("get_status")


def test_unicode_payload_survives_authentication(fake_bridge):
    BridgeClient(port=fake_bridge.port, token="t").request("synthetic", text='é漢字\n"\\')
    assert fake_bridge.received[0]["text"] == 'é漢字\n"\\'


def test_oversized_handshake_is_bounded():
    def hostile(peer):
        read_frame(peer)
        peer.sendall(b" " * (MAX_HELLO_BYTES + 1))

    with endpoint(hostile) as port:
        with pytest.raises(BridgeProtocolError, match="byte limit"):
            BridgeClient(port=port, token="t").request("get_status")


def test_response_reader_stops_at_byte_limit():
    peer, client = socket.socketpair()
    with peer, client:
        peer.sendall(b" " * 129)
        with pytest.raises(BridgeProtocolError, match="byte limit"):
            BridgeClient(token="t")._read_line(
                client, payload={}, deadline=time.monotonic() + 1, limit=128
            )


@pytest.mark.parametrize("phase", ["handshake", "response"])
def test_trickle_cannot_extend_the_overall_deadline(phase):
    def hostile(peer):
        hello = json.loads(read_frame(peer))
        if phase == "response":
            nonce = "a" * 32
            send_frame(
                peer,
                {
                    "ok": True,
                    "result": {
                        "protocol": 25,
                        "nonce": nonce,
                        "proof": BridgeClient._proof("t", "server", hello["nonce"], nonce),
                    },
                },
            )
            read_frame(peer)
        # Every byte arrives inside the old per-recv timeout, but the stream
        # lasts far beyond the complete request's allowed time.
        for _ in range(30):
            peer.sendall(b" ")
            time.sleep(0.025)

    with endpoint(hostile) as port:
        started = time.monotonic()
        with pytest.raises(BridgeUnavailableError) as caught:
            BridgeClient(port=port, token="t", timeout=0.15).request("get_status")
        elapsed = time.monotonic() - started
        assert elapsed < 0.45
        assert (caught.value.last_command is not None) == (phase == "response")
