"""The client must read the token file and fail loudly when it is absent."""

import pathlib
import sys

import pytest

from battlemap_mcp import bridge_client
from battlemap_mcp.bridge_client import BridgeClient, _state_file
from battlemap_mcp.errors import (
    BridgeCommandError,
    BridgePeerUntrustedError,
    BridgeUnavailableError,
)


def test_explicit_token_is_used():
    client = BridgeClient(token="abc123")
    assert client.token == "abc123"


def test_token_read_from_file(tmp_path, monkeypatch):
    token_file = tmp_path / "mcp_bridge_token"
    token_file.write_text("deadbeef" * 8)
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(token_file))
    assert BridgeClient().token == "deadbeef" * 8


def test_missing_token_file_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(tmp_path / "absent"))
    with pytest.raises(BridgeUnavailableError) as exc:
        _ = BridgeClient().token
    assert "token" in str(exc.value).lower()
    assert str(tmp_path / "absent") in str(exc.value)


def test_empty_token_file_fails_loudly(tmp_path, monkeypatch):
    """A zero-byte token file is a distinct failure mode from a missing one
    (e.g. the mod crashed mid-write) and must raise the same specific type,
    not the base — see errors.py's split rationale."""
    token_file = tmp_path / "mcp_bridge_token"
    token_file.write_text("")
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(token_file))
    with pytest.raises(BridgeUnavailableError) as exc:
        _ = BridgeClient().token
    assert str(token_file) in str(exc.value)


def test_construction_does_not_require_token_file(tmp_path, monkeypatch):
    """Regression check: importing/building the MCP server must not touch the
    filesystem before the mod has written the token file — the normal state
    when an MCP client starts the server before Dungeondraft is running."""
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(tmp_path / "absent"))
    client = BridgeClient()  # must not raise
    assert client is not None


def _fake_home(monkeypatch, home: pathlib.Path) -> None:
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)


def test_default_token_file_on_windows_prefers_localappdata(tmp_path, monkeypatch):
    """A hardcoded macOS-only path is the exact regression this guards against
    (Task 15): fake the platform rather than reading the host OS, or this
    would happily pass on a Mac while Windows stayed broken."""
    fake_home = tmp_path / "home"
    appdata = tmp_path / "local"
    _fake_home(monkeypatch, fake_home)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))

    path = _state_file("mcp_bridge_token", _platform="win32")

    assert path == appdata / "battlemap-mcp" / "mcp_bridge_token"


def test_default_token_file_on_windows_falls_back_without_localappdata(tmp_path, monkeypatch):
    """If %LOCALAPPDATA% is unset (unusual, but happens on stripped-down runners or
    service accounts), fall back to the conventional Local profile layout
    under the home directory rather than refusing to resolve a path."""
    fake_home = tmp_path / "home"
    _fake_home(monkeypatch, fake_home)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    path = _state_file("mcp_bridge_token", _platform="win32")

    assert path == fake_home / "AppData" / "Local" / "battlemap-mcp" / "mcp_bridge_token"


def test_default_token_file_on_macos(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    _fake_home(monkeypatch, fake_home)

    path = _state_file("mcp_bridge_token", _platform="darwin")

    assert (
        path == fake_home / "Library" / "Application Support" / "battlemap-mcp" / "mcp_bridge_token"
    )


def test_default_token_file_on_linux(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    _fake_home(monkeypatch, fake_home)

    path = _state_file("mcp_bridge_token", _platform="linux")

    assert path == fake_home / ".local" / "state" / "battlemap-mcp" / "mcp_bridge_token"


def test_env_override_takes_precedence_over_platform_default(tmp_path, monkeypatch):
    """BATTLEMAP_MCP_TOKEN_FILE is the escape hatch for a non-standard
    install and must win regardless of platform."""
    token_file = tmp_path / "mcp_bridge_token"
    token_file.write_text("cafef00d" * 8)
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(sys, "platform", "win32")

    assert BridgeClient().token == "cafef00d" * 8


def test_missing_token_error_names_platform_specific_path(tmp_path, monkeypatch):
    """The error for a missing token must name the path actually searched on
    the running platform, not always the macOS one."""
    monkeypatch.delenv("BATTLEMAP_MCP_TOKEN_FILE", raising=False)
    fake_home = tmp_path / "home"
    _fake_home(monkeypatch, fake_home)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(sys, "platform", "win32")

    with pytest.raises(BridgeUnavailableError) as exc:
        _ = BridgeClient().token

    expected = tmp_path / "local" / "battlemap-mcp" / "mcp_bridge_token"
    assert str(expected) in str(exc.value)


def test_port_is_read_from_the_file_the_mod_publishes(tmp_path, monkeypatch):
    """Opening a map moves the bridge to the next free port; the client follows.

    Before protocol 19 the port was a constant, so the client kept knocking on
    a socket orphaned by the previous map's mod instance and timed out.
    """
    port_file = tmp_path / "mcp_bridge_port"
    port_file.write_text("8791", encoding="utf-8")
    monkeypatch.setattr(bridge_client, "_state_file", lambda name, **kw: tmp_path / name)
    monkeypatch.delenv("BATTLEMAP_MCP_PORT", raising=False)

    assert BridgeClient().port == 8791


def test_port_falls_back_to_the_default_when_unpublished(tmp_path, monkeypatch):
    """A missing file is the normal case for one map and for pre-19 mods, so it
    must not be an error."""
    monkeypatch.setattr(bridge_client, "_state_file", lambda name, **kw: tmp_path / name)
    monkeypatch.delenv("BATTLEMAP_MCP_PORT", raising=False)

    assert BridgeClient().port == bridge_client.DEFAULT_PORT


def test_explicit_port_beats_the_published_one(tmp_path, monkeypatch):
    """An explicit port is a caller's deliberate choice and is never overridden."""
    (tmp_path / "mcp_bridge_port").write_text("8791", encoding="utf-8")
    monkeypatch.setattr(bridge_client, "_state_file", lambda name, **kw: tmp_path / name)

    assert BridgeClient(port=9999).port == 9999


def test_a_rejected_token_is_re_read_once(tmp_path, monkeypatch, fake_bridge):
    """A stale cached token must not poison the client for the whole process.

    The MCP server holds one client for the life of the process, so without
    this a token file rewritten under it (fresh install, wiped user directory,
    a future rotation) would fail every later call until a restart.
    """
    token_file = tmp_path / "mcp_bridge_token"
    token_file.write_text("stale" * 8, encoding="utf-8")
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(token_file))

    fake_bridge.token = "stale" * 8

    def reject_then_accept(req):
        if len(fake_bridge.received) == 1:
            # The mod restarted and wrote a new token between the two attempts.
            token_file.write_text("fresh" * 8, encoding="utf-8")
            fake_bridge.token = "fresh" * 8
            return {"ok": False, "error": "bad or missing token"}
        return {"ok": True, "result": {"pong": True}}

    fake_bridge.handler = reject_then_accept
    client = BridgeClient(port=fake_bridge.port)

    assert client.request("ping") == {"pong": True}
    assert len(fake_bridge.received) == 2, "the client did not retry after rejection"
    # Protocol 24 sends a proof, not the token, so "did it re-read the file?" is
    # answered by which secret the second proof was computed with.
    second = fake_bridge.handshakes[1]
    got = fake_bridge.envelopes[1]["auth"]
    with_new = BridgeClient._message_proof(
        "fresh" * 8,
        "request",
        second["client_nonce"],
        second["server_nonce"],
        fake_bridge.envelopes[1]["payload"],
    )
    with_old = BridgeClient._message_proof(
        "stale" * 8,
        "request",
        second["client_nonce"],
        second["server_nonce"],
        fake_bridge.envelopes[1]["payload"],
    )
    assert got == with_new, "the client retried with the same stale token"
    assert got != with_old


def test_a_handshake_rejection_refreshes_a_changed_file_token_once(
    tmp_path, monkeypatch, fake_bridge
):
    stale = "stale" * 8
    fresh = "fresh" * 8
    token_file = tmp_path / "mcp_bridge_token"
    token_file.write_text(stale, encoding="utf-8")
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(token_file))
    fake_bridge.token = stale
    client = BridgeClient(port=fake_bridge.port)
    assert client.token == stale

    token_file.write_text(fresh, encoding="utf-8")
    fake_bridge.token = fresh

    assert client.request("ping") == {}
    assert len(fake_bridge.handshakes) == 2
    assert len(fake_bridge.received) == 1


@pytest.mark.parametrize("explicit_port", [True, False])
def test_a_handshake_rejection_with_unchanged_local_settings_is_not_retried(
    tmp_path, monkeypatch, fake_bridge, explicit_port
):
    token_file = tmp_path / "mcp_bridge_token"
    token_file.write_text("t" * 40, encoding="utf-8")
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(bridge_client, "_resolve_port", lambda: fake_bridge.port)
    fake_bridge.mode = "impostor"

    with pytest.raises(BridgePeerUntrustedError):
        BridgeClient(port=fake_bridge.port if explicit_port else None).request("ping")
    assert len(fake_bridge.handshakes) == 1


def test_a_response_authentication_failure_is_not_retried_after_token_rotation(
    tmp_path, monkeypatch, fake_bridge
):
    stale = "stale" * 8
    fresh = "fresh" * 8
    token_file = tmp_path / "mcp_bridge_token"
    token_file.write_text(stale, encoding="utf-8")
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(token_file))
    fake_bridge.token = stale

    def rotate_after_dispatch(_request):
        token_file.write_text(fresh, encoding="utf-8")
        fake_bridge.token = fresh
        return {"ok": True, "result": {}}

    fake_bridge.handler = rotate_after_dispatch
    fake_bridge.mode = "bad_response_auth"

    with pytest.raises(BridgePeerUntrustedError, match="response authentication failed"):
        BridgeClient(port=fake_bridge.port).request("synthetic_mutation")
    assert len(fake_bridge.received) == 1


def test_changed_port_recovers_from_another_bridge_without_sending_it_commands(
    monkeypatch, fake_bridge
):
    from tests.conftest import FakeBridge

    other = FakeBridge()
    other.token = "another-instance"
    try:
        monkeypatch.setattr(bridge_client, "_resolve_port", lambda: other.port)
        client = BridgeClient(token=fake_bridge.token)
        assert client.port == other.port
        monkeypatch.setattr(bridge_client, "_resolve_port", lambda: fake_bridge.port)

        assert client.request("synthetic_mutation") == {}
        assert len(other.handshakes) == 1
        assert other.received == []
        assert len(fake_bridge.received) == 1
    finally:
        other.close()


def test_other_command_errors_are_not_retried(tmp_path, monkeypatch, fake_bridge):
    """Only auth failures retry. Retrying a real error would run the command twice."""
    (tmp_path / "mcp_bridge_token").write_text("t" * 40, encoding="utf-8")
    monkeypatch.setenv("BATTLEMAP_MCP_TOKEN_FILE", str(tmp_path / "mcp_bridge_token"))
    fake_bridge.token = "t" * 40
    fake_bridge.handler = lambda req: {"ok": False, "error": "no element with id 7"}

    with pytest.raises(BridgeCommandError):
        BridgeClient(port=fake_bridge.port).request("get_element", id=7)
    assert len(fake_bridge.received) == 1


def test_the_mcp_server_does_not_pin_the_port(monkeypatch):
    """The server module must let the client discover the published port.

    Constructing it with an explicit port silently defeats port discovery:
    every map load moves the bridge to the next port, and the server keeps
    knocking on an orphaned listener that accepts connections and answers none
    — which reads as a hang, not a misconfiguration.
    """
    import importlib

    from battlemap_mcp import server

    monkeypatch.delenv("DD_BRIDGE_PORT", raising=False)
    importlib.reload(server)
    assert server.PORT is None
    assert server.bridge._explicit_port is None


def test_an_explicit_port_env_var_still_wins(monkeypatch):
    import importlib

    from battlemap_mcp import server

    monkeypatch.setenv("DD_BRIDGE_PORT", "9001")
    importlib.reload(server)
    assert server.bridge._explicit_port == 9001
    monkeypatch.delenv("DD_BRIDGE_PORT")
    importlib.reload(server)
