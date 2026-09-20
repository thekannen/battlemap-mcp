"""A file check once reported a two-day-old bridge \"healthy\" because it looked in
a folder Dungeondraft never loads. Only the running bridge can say what it
loaded, so it hashes the source it was compiled from and the server compares.
"""

import hashlib
from pathlib import Path

from battlemap_mcp import installer, server


def _reply(sha):
    return {"pong": True, "protocol": 23, "bridge_sha256": sha, "bridge_path": "/mods/b.gd"}


def test_the_package_hash_is_the_file_text_without_carriage_returns():
    """What the bridge hashes: the source Dungeondraft compiled, minus its header.

    Dungeondraft prepends `var Global = {}\\nvar Script=null` to every mod before
    compiling it, so the running source is the file plus that. The bridge strips
    it; what is left is the file's text, which is what this must hash.
    """
    script = Path(str(installer.payload_root())) / "scripts" / "tools" / "mcp_bridge.gd"
    text = script.read_bytes().decode("utf-8").replace("\r", "")
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert server._package_bridge_sha256() == expected


def test_a_running_bridge_that_matches_is_current(monkeypatch):
    sha = server._package_bridge_sha256()
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: _reply(sha))
    reply = server.ping()
    assert reply["bridge_current"] is True
    assert "bridge_note" not in reply


def test_a_different_running_bridge_is_flagged(monkeypatch):
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: _reply("0" * 64))
    reply = server.ping()
    assert reply["bridge_current"] is False
    assert "Restart Dungeondraft" in reply["bridge_note"]


def test_a_bridge_too_old_to_say_is_unknown_not_stale(monkeypatch):
    """Not knowing and knowing it is stale are different answers."""
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: {"pong": True, "protocol": 23})
    assert server.ping()["bridge_current"] is None
