"""BridgeClient behaviour against a real socket speaking the real protocol."""

import json

import pytest

from battlemap_mcp.bridge_client import BridgeClient
from battlemap_mcp.errors import (
    BridgeCommandError,
    BridgePeerUntrustedError,
    BridgeProtocolError,
    BridgeUnavailableError,
)


def client(fake_bridge, **kw):
    return BridgeClient(port=fake_bridge.port, timeout=5.0, token="t", **kw)


def test_successful_request_returns_result(fake_bridge):
    fake_bridge.responses["ping"] = {"ok": True, "result": {"pong": True}}
    assert client(fake_bridge).request("ping") == {"pong": True}


def test_the_token_is_never_sent(fake_bridge):
    """Protocol 24. It used to go in the first message, to whatever answered."""
    fake_bridge.token = "sekrit-token-value"
    BridgeClient(port=fake_bridge.port, timeout=5.0, token="sekrit-token-value").request("ping")

    assert b"sekrit-token-value" not in fake_bridge.raw, "the token went onto the wire"
    sent = fake_bridge.envelopes[0]
    assert "token" not in sent

    hello = json.loads(fake_bridge.raw.split(b"\n")[0])
    assert hello["cmd"] == "hello" and len(hello["nonce"]) == 32
    expected = BridgeClient._message_proof(
        "sekrit-token-value",
        "request",
        hello["nonce"],
        fake_bridge.sent_hello["result"]["nonce"],
        sent["payload"],
    )
    assert sent["auth"] == expected


def test_a_peer_that_cannot_prove_the_token_gets_nothing(fake_bridge):
    """An impostor on the port must not be handed anything to replay."""
    fake_bridge.mode = "impostor"
    with pytest.raises(BridgePeerUntrustedError, match="could not prove"):
        client(fake_bridge).request("place_object", asset="a.png")
    assert fake_bridge.received == [], "a command was sent to an unverified peer"
    assert b"place_object" not in fake_bridge.raw


def test_an_impostor_is_not_retried(fake_bridge):
    fake_bridge.mode = "impostor"
    with pytest.raises(BridgePeerUntrustedError):
        client(fake_bridge).request("ping")
    hellos = [row for row in fake_bridge.raw.split(b"\n") if b"hello" in row]
    assert len(hellos) == 1, f"retried a peer that failed the challenge: {len(hellos)}"


def test_a_pre_24_mod_is_named_as_the_problem(fake_bridge):
    """An old mod answers hello with 'bad or missing token', which is a
    confusing thing to report as an auth failure."""
    fake_bridge.mode = "old_mod"
    with pytest.raises(BridgeProtocolError, match="older than this package"):
        client(fake_bridge).request("ping")


def test_params_are_forwarded(fake_bridge):
    client(fake_bridge).request("place_object", asset="a.png", x=1, y=2)
    sent = fake_bridge.received[0]
    assert sent["asset"] == "a.png"
    assert sent["x"] == 1


def test_command_error_raises_with_cmd_and_params(fake_bridge):
    fake_bridge.responses["place_object"] = {"ok": False, "error": "no map open"}
    with pytest.raises(BridgeCommandError) as exc:
        client(fake_bridge).request("place_object", asset="a.png")
    assert "no map open" in str(exc.value)
    assert exc.value.cmd == "place_object"
    assert exc.value.params["asset"] == "a.png"


def test_malformed_response_raises_protocol_error(fake_bridge):
    fake_bridge.mode = "malformed"
    with pytest.raises(BridgeProtocolError):
        client(fake_bridge).request("ping")


def test_empty_response_raises_protocol_error(fake_bridge):
    fake_bridge.mode = "empty"
    with pytest.raises(BridgeProtocolError):
        client(fake_bridge).request("ping")


def test_death_mid_request_names_the_last_command(fake_bridge):
    fake_bridge.mode = "die"
    with pytest.raises(BridgeUnavailableError) as exc:
        client(fake_bridge).request("draw_wall", points=[[0, 0], [1, 1]])
    assert exc.value.last_command is not None
    assert exc.value.last_command["cmd"] == "draw_wall"
    assert "draw_wall" in str(exc.value)


def test_refused_connection_reports_unavailable():
    c = BridgeClient(port=1, timeout=1.0, token="t")
    with pytest.raises(BridgeUnavailableError):
        c.request("ping")


def test_a_silent_listener_is_reported_as_a_busy_editor_not_a_missing_one():
    """Telling the user to check whether Dungeondraft is running sent them the
    wrong way; it was running, and the window was what needed looking at.
    """
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        c = BridgeClient(port=listener.getsockname()[1], timeout=0.3, token="t")
        with pytest.raises(BridgeUnavailableError) as exc:
            c.request("ping")
    message = str(exc.value)
    assert "not answering" in message
    assert "Is Dungeondraft running" not in message
