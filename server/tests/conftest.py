"""A fake bridge that speaks the real wire protocol over a real socket.

Mocking the socket away would leave the framing and buffering code — the part
most likely to be wrong — untested. This runs a real TCP server on an ephemeral
port so tests exercise the actual read path with Dungeondraft closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import socket
import threading
from pathlib import Path

import pytest

from battlemap_mcp.bridge_client import PROTOCOL_VERSION, BridgeClient


def _create_file_symlink_or_skip(link: Path, target: Path) -> None:
    """Create a file link or skip only when Windows denies that capability."""
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires Developer Mode or elevated privileges")
        raise


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    """Tests never reach GitHub; test_updates.py turns the check back on."""
    monkeypatch.setenv("BATTLEMAP_MCP_UPDATE_CHECK", "0")


@pytest.fixture
def create_file_symlink_or_skip():
    return _create_file_symlink_or_skip


class FakeBridge:
    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.05)
        self.port: int = self._sock.getsockname()[1]
        self.responses: dict[str, dict] = {}
        # Set a callable taking the request dict to vary the reply per call —
        # `responses` alone cannot express "fail the first attempt, succeed the
        # retry", which is what the auth-retry path needs.
        self.handler = None
        self.received: list[dict] = []
        self.envelopes: list[dict] = []
        self.mode: str = "normal"
        # The shared secret this fake proves it knows. Tests that want an
        # impostor set mode="impostor" (answers hello with a wrong proof) or
        # mode="old_mod" (refuses hello, like a pre-24 bridge).
        self.token: str = "t"
        # Every byte the client ever sent, so a test can assert the token was
        # not among them.
        self.raw: bytes = b""
        # The hello reply this fake sent, so a test can recompute the expected proof.
        self.sent_hello: dict = {}
        # One entry per handshake: the nonces and the token used for it.
        self.handshakes: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                # Either the accept-loop timeout expired (harmless — loop
                # around and check _stop again) or close() tore the socket
                # down from under us. Either way this is not a real failure.
                continue
            with conn:
                buf = b""
                authenticated = False
                while True:
                    while b"\n" not in buf:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        self.raw += chunk
                        buf += chunk
                    if b"\n" not in buf:
                        break
                    line, _, buf = buf.partition(b"\n")
                    try:
                        req = json.loads(line)
                    except json.JSONDecodeError:
                        break
                    if req.get("cmd") == "hello":
                        reply = self._hello(req)
                        authenticated = reply.get("ok", False)
                        conn.sendall((json.dumps(reply) + "\n").encode())
                        if not authenticated:
                            break
                        continue
                    self.envelopes.append(req)
                    session = self.handshakes[-1]
                    expected = BridgeClient._message_proof(
                        session["token"],
                        "request",
                        session["client_nonce"],
                        session["server_nonce"],
                        req.get("payload", ""),
                    )
                    if req.get("seq") != 1 or not hmac.compare_digest(
                        req.get("auth", ""), expected
                    ):
                        break
                    req = json.loads(req["payload"])
                    self.received.append(req)
                    if not self._reply(conn, req):
                        break
                    break

    def _hello(self, req: dict) -> dict:
        """Protocol 25: prove we know the token, over both nonces."""
        if self.mode == "old_mod":
            return {"ok": False, "error": "bad or missing token"}
        server_nonce = secrets.token_hex(16)
        proof = self.proof("server", req.get("nonce", ""), server_nonce)
        if self.mode == "impostor":
            proof = "0" * 64
        self.handshakes.append(
            {
                "client_nonce": req.get("nonce", ""),
                "server_nonce": server_nonce,
                "token": self.token,
            }
        )
        self.sent_hello = {
            "ok": True,
            "result": {"protocol": PROTOCOL_VERSION, "nonce": server_nonce, "proof": proof},
        }
        return self.sent_hello

    def proof(self, role: str, client_nonce: str, server_nonce: str) -> str:
        message = f"dd-mcp/{PROTOCOL_VERSION}|{role}|{client_nonce}|{server_nonce}"
        return hmac.new(self.token.encode(), message.encode(), hashlib.sha256).hexdigest()

    def _reply(self, conn, req: dict) -> bool:

        if self.mode == "die":
            return False  # close without replying
        if self.mode == "empty":
            conn.sendall(b"\n")
            return False
        if self.mode == "malformed":
            conn.sendall(b"{not json\n")
            return False

        if self.handler is not None:
            body = self.handler(req)
        else:
            body = self.responses.get(req.get("cmd", ""), {"ok": True, "result": {}})
        session = self.handshakes[-1]
        payload = json.dumps(body)
        envelope = {
            "seq": 1,
            "payload": payload,
            "auth": BridgeClient._message_proof(
                session["token"],
                "response",
                session["client_nonce"],
                session["server_nonce"],
                payload,
            ),
        }
        if self.mode == "bad_response_auth":
            envelope["auth"] = "0" * 64
        conn.sendall((json.dumps(envelope) + "\n").encode())
        return True

    def close(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(timeout=2.0)


@pytest.fixture
def fake_bridge():
    bridge = FakeBridge()
    yield bridge
    bridge.close()
