"""Proves the pytest harness runs with Dungeondraft closed."""

import asyncio
from pathlib import Path

import pytest

from battlemap_mcp import server


def test_package_imports_without_a_bridge():
    from battlemap_mcp import bridge_client

    assert bridge_client.BridgeClient(port=1, token="test").port == 1


def test_server_module_imports_and_registers_all_tools():
    """Safe with Dungeondraft closed: `BridgeClient.token` is a lazy
    `cached_property` (see bridge_client.py), so building the module-level
    `bridge` object never touches the filesystem or the socket.
    """
    from battlemap_mcp import server

    tools = asyncio.run(server.mcp.list_tools())
    tool_names = {t.name for t in tools}

    assert len(tools) >= 64
    # Spot-check a handful spanning read, create, and async-render tools
    # rather than trust the count alone.
    for expected in (
        "ping",
        "get_status",
        "get_composition_snapshot",
        "place_object",
        "draw_wall",
        "export_map",
        "scatter_objects",
        "inspect_dungeondraft_installation",
        "install_dungeondraft_bridge",
    ):
        assert expected in tool_names, f"tool {expected!r} did not register"


def test_composition_snapshot_forwards_a_read_only_request(monkeypatch):
    """The aesthetics workflow needs a compact map fact summary, not a score."""
    expected = {
        "map_size_woxels": [2048, 1536],
        "grid": {"columns": 3, "rows": 3},
        "by_kind": {"objects": {"count": 2, "bounds": [100, 200, 400, 500]}},
    }
    seen = {}

    def request(command, **params):
        seen["command"] = command
        seen["params"] = params
        return expected

    monkeypatch.setattr(server.bridge, "request", request)

    assert server.get_composition_snapshot() == expected
    assert seen == {"command": "get_composition_snapshot", "params": {}}


def test_list_assets_can_request_only_vanilla_assets(monkeypatch):
    """Large custom libraries must not crowd vanilla assets out of a colour scan."""
    from battlemap_mcp import server

    seen = {}

    def request(command, **params):
        seen["command"] = command
        seen["params"] = params
        return {"assets": []}

    monkeypatch.setattr(server.bridge, "request", request)

    assert server.list_assets("Objects", "carpet", 200, vanilla_only=True) == {"assets": []}
    assert seen == {
        "command": "list_assets",
        "params": {
            "category": "Objects",
            "search": "carpet",
            "limit": 200,
            "vanilla_only": True,
        },
    }


def test_render_timeout_raises_bridge_unavailable(tmp_path):
    """export_map's wait for the async render (server.py) must surface as the
    specific `BridgeUnavailableError`, not the bare base — the same class of
    bug fixed for the token-file reads in bridge_client.py."""
    from battlemap_mcp.errors import BridgeUnavailableError
    from battlemap_mcp.server import _wait_for_file

    with pytest.raises(BridgeUnavailableError):
        _wait_for_file(str(tmp_path / "never-appears.png"), timeout=0.05)


def test_server_instructions_cover_the_traps():
    """The server-level `instructions` string is the only cross-cutting guidance
    a model gets — per-tool docstrings cannot tell it that floors come in four
    systems, or that guessing an asset path is what to avoid. Each rule below
    corresponds to a mistake actually made against this bridge, so if one is
    dropped the guidance has regressed.
    """
    from battlemap_mcp.server import INSTRUCTIONS

    for rule in (
        "NEVER GUESS",  # a bad asset path destabilised the app
        "256 woxels",  # coordinate system
        "scatter_objects",  # the furnished-vs-placed distinction
        "screenshot",  # build, look, adjust
        "shadow",  # supports visual depth along relevant structure
        # C6: after another client undid a rock, Claude said it was still there
        # without a tool call, reasoning that it had made no edits itself.
        "never answer from memory",
        "y grows DOWN",  # C6: Codex called y=390 the lower-left corner
        "saved file path",  # S3: the image reached the model, never the user
    ):
        assert rule in INSTRUCTIONS, f"guidance lost its {rule!r} rule"


# Rules that belong to one tool live in that tool's description, where the
# model reads them when it is about to make that call. The instructions carry
# only what applies before or without a call: the session contract, routing,
# and the shared-map warning. Claude Code defers MCP tools until a schema is
# fetched, so the instructions also serve as the index of which tools exist.
RULES_ON_TOOLS = {
    "place_object": ("baked at placement", "modulate", "flat red"),
    "modify_object": ("color is REFUSED", "modulate"),
    "scatter_objects": ("baked at placement",),
    "undo": ("terrain / cave", "1000 steps"),
    "delete_element": ("undo()", "cannot be deleted"),
    "set_camera": ("LARGER = zoomed OUT",),
    "fit_elements": ("woxels-per-pixel",),
    "save_map": ("DROPS edits",),
    "get_status": ("saving.in_flight",),
    "export_map": ("Universal VTT",),
    "screenshot": ("give them that",),
    "set_ambient_light": ("look at a render", "has to read"),
}


def test_tool_specific_rules_live_on_their_tool():
    """Moving a rule out of the instructions must not lose it."""
    tools = {t.name: t.description or "" for t in asyncio.run(server.mcp.list_tools())}
    missing = [
        f"{name}: {rule!r}"
        for name, rules in RULES_ON_TOOLS.items()
        for rule in rules
        if rule.lower() not in tools[name].lower()
    ]
    assert not missing, missing


def test_server_instructions_fit_the_client_budget():
    """A client was observed cutting instructions at 2048 characters, mid-word.

    Everything past that point — colour, saving, undo, the working order — never
    reached the model, so the guidance above only counts if it arrives whole.
    This is a project compatibility target, not an MCP protocol limit: detail
    belongs in the tool descriptions and skills, which load on their own.
    """
    from battlemap_mcp.server import INSTRUCTIONS

    assert len(INSTRUCTIONS) < 2000, f"instructions are {len(INSTRUCTIONS)} characters"


def test_verify_live_covers_every_tool_that_can_be_checked_live():
    """The live check must not fall behind the tool surface.

    It once exercised 15 of 40 tools while its own header claimed to cover
    every command. A tool that silently fails is worse than a missing one: the
    model gets a success response and builds on a false premise.
    """
    import re

    src = (Path(__file__).resolve().parents[1] / "tools/verify_live.py").read_text()
    covered = set(re.findall(r'bridge\.request\(\s*"(\w+)"', src))
    assert "clear_captures" not in covered, "capture cleanup is not a bridge command"
    tools = {t.name for t in asyncio.run(server.mcp.list_tools())}

    # Excluded on purpose, each because running it would destroy the user's work
    # rather than because nobody got to it.
    cannot_check = {
        "open_map",  # replaces the current map; unsaved work is lost
        "save_map",  # overwrites the map file on disk
        "set_verbose",  # debugging aid; exercised by the audit itself
        "log_marker",  # debugging aid; exercised by the audit itself
        # Both change editor state the person at the keyboard can see, and
        # verify_live is meant to be safe to run against a map in progress.
        # The UAT's tool-lifecycle cases exercise them instead.
        "select_tool",  # changes which tool the UI has selected
        "set_tool_layer",  # changes where a tool draws next
        # Neither sends a bridge command of its own: both are server-side
        # analyses composed from get_status and list_elements, all exercised
        # here, and their geometry has unit tests over synthetic maps. There is
        # no "validate_floorplan", "validate_placements" or "validate_scene"
        # command to call.
        # What IS live-checkable about them is the data they read, so the
        # list_elements case below asserts the texture_size that
        # validate_placements measures footprints from.
        "validate_floorplan",
        "validate_placements",
        "validate_scene",
        # Installer tools inspect local filesystem state or can install a mod;
        # they do not belong in a live map mutation verification.
        "inspect_dungeondraft_installation",
        "install_dungeondraft_bridge",
        "prepare_map_with_packs",
        # Server-side wait that sends only get_operation, which is exercised
        # here; its polling, failure and timeout paths have unit tests.
        "get_export",
        # Python-only cleanup, not a bridge command. Do not erase the user's
        # existing captures during live verification; covered with temp files.
        "clear_captures",
    }
    missing = tools - covered - cannot_check
    assert not missing, (
        f"verify_live.py does not exercise {sorted(missing)} — add them, or add "
        f"them to cannot_check with the reason"
    )


def test_list_assets_substring_mode_is_a_single_unchanged_call(monkeypatch):
    """The default path must not gain a round trip or change its params."""
    from battlemap_mcp import server

    calls = []

    def request(command, **params):
        calls.append(params)
        return {"assets": ["res://textures/portals/door_01.png"], "colorable": []}

    monkeypatch.setattr(server.bridge, "request", request)
    server.list_assets(category="Portals", search="door", limit=5)

    assert len(calls) == 1, "substring mode must not survey the whole category"
    assert calls[0] == {"category": "Portals", "search": "door", "limit": 5}


def test_list_assets_ranked_mode_filters_then_asks_for_the_winners(monkeypatch):
    """Ranking scores CANDIDATES the bridge filtered, then re-queries the winners.

    It used to pull the whole category across to rank it here, which on a
    141,197-asset library crossed the bridge's own buffer cap: the connection
    was dropped mid-response and every ranked search failed. The filter is what
    keeps the transfer bounded; the second call is what keeps `colorable`
    populated for the handful the caller chooses between, because colour is
    baked at placement.
    """
    from battlemap_mcp import server

    library = [
        "res://textures/objects/furniture/tables/round_table_01.png",
        "res://textures/objects/furniture/chairs/bar_chair.png",
    ]
    calls = []

    def request(command, **params):
        calls.append(params)
        if "only" in params:
            return {
                "assets": params["only"],
                "colorable": ["res://textures/objects/furniture/tables/round_table_01.png"],
                "colorable_scanned": True,
                "note": "scanned",
            }
        return {"assets": library, "total": len(library)}

    monkeypatch.setattr(server.bridge, "request", request)
    result = server.list_assets(category="Objects", search="table round", match_mode="tokens")

    assert len(calls) == 2, "expected a candidate call and a by-name detail call"
    assert calls[0]["terms"] == ["table", "round"], "the bridge must do the filtering"
    assert calls[0]["limit"] == server.RANK_CANDIDATE_LIMIT
    assert "search" not in calls[0], "a ranked search filters by terms, not substring"
    assert calls[1]["only"] == result["assets"]
    # word order ignored, and the chair is not dragged in by a partial hit
    assert result["assets"] == ["res://textures/objects/furniture/tables/round_table_01.png"]
    assert result["match_mode"] == "tokens"
    assert result["scores"] and result["colorable_scanned"] is True


def test_list_assets_ranked_miss_explains_itself_without_a_second_call(monkeypatch):
    """An empty ranked result should say why, not look like an empty category."""
    from battlemap_mcp import server

    calls = []

    def request(command, **params):
        calls.append(params)
        return {"assets": ["res://textures/portals/door_01.png"], "total": 1}

    monkeypatch.setattr(server.bridge, "request", request)
    result = server.list_assets(search="bougainvillea", match_mode="fuzzy", min_score=0.9)

    assert len(calls) == 1, "nothing to re-query, so no second round trip"
    assert result["assets"] == []
    assert "string matching, not meaning" in result["note"]


def test_list_assets_rejects_an_unknown_match_mode():
    from battlemap_mcp import server
    from battlemap_mcp.errors import ValidationError

    with pytest.raises(ValidationError):
        server.list_assets(search="door", match_mode="semantic")


def test_list_assets_rejects_an_out_of_range_min_score():
    from battlemap_mcp import server
    from battlemap_mcp.errors import ValidationError

    with pytest.raises(ValidationError):
        server.list_assets(search="door", match_mode="fuzzy", min_score=1.4)


def test_read_all_pages_until_it_has_every_element(monkeypatch):
    """The validators asked for a flat 1000 and used whatever came back."""
    from battlemap_mcp import server

    library = [{"id": i} for i in range(1200)]
    offsets: list[int] = []

    def request(command, **params):
        assert command == "list_elements", command
        offset, limit = params["offset"], params["limit"]
        offsets.append(offset)
        batch = library[offset : offset + limit]
        return {"elements": batch, "count": len(batch), "total": len(library)}

    monkeypatch.setattr(server.bridge, "request", request)
    elements, coverage = server._read_all("objects")
    assert len(elements) == 1200
    assert coverage == {"kind": "objects", "total": 1200, "read": 1200, "complete": True}
    assert len(offsets) > 1, "it has to actually page, not ask once"


def test_a_partly_read_map_is_never_reported_clean():
    """Runtime behavior and validation."""
    from battlemap_mcp import server

    report = server._with_coverage(
        {"ok": True}, [{"kind": "objects", "total": 5000, "read": 1000, "complete": False}]
    )
    assert report["ok"] is False, "an unread remainder cannot be a clean verdict"
    assert report["complete"] is False
    assert "INCOMPLETE" in report["note"]
    assert "objects 1000 of 5000" in report["note"]


def test_incomplete_coverage_keeps_the_reports_own_note():
    from battlemap_mcp import server

    report = server._with_coverage(
        {"ok": True, "note": "these points are still the default terrain"},
        [{"kind": "walls", "total": 9, "read": 2, "complete": False}],
    )
    assert "these points are still the default terrain" in report["note"]
    assert "INCOMPLETE" in report["note"]


def test_a_complete_read_leaves_the_verdict_untouched():
    from battlemap_mcp import server

    report = server._with_coverage(
        {"ok": True}, [{"kind": "objects", "total": 12, "read": 12, "complete": True}]
    )
    assert report["ok"] is True
    assert report["complete"] is True
    assert "note" not in report


def test_ranked_search_says_when_it_scored_only_part_of_what_matched(monkeypatch):
    """A match past the candidate cap returned "nothing scored", advising a
    broader search that could not possibly have helped."""
    from battlemap_mcp import server

    def request(command, **params):
        if params.get("terms"):
            return {
                "assets": [f"res://textures/objects/thing_{i}.png" for i in range(10)],
                "matched": 140000,
                "total": 140000,
            }
        return {"assets": [], "colorable": [], "colorable_scanned": True}

    monkeypatch.setattr(server.bridge, "request", request)
    result = server.list_assets(
        category="Objects", search="bougainvillea", match_mode="fuzzy", min_score=0.9
    )
    assert result["survey_complete"] is False
    assert result["surveyed"] == 10
    assert "NOT a reliable" in result["note"]


def test_a_fuzzy_search_filters_on_prefixes_so_a_typo_still_reaches_the_asset(monkeypatch):
    """ "barrle" cannot filter for itself; "bar" can, and fuzzy scoring does the rest."""
    from battlemap_mcp import server

    seen = {}

    def request(command, **params):
        if params.get("terms"):
            seen["terms"] = params["terms"]
            return {"assets": ["res://textures/objects/barrel_01.png"], "matched": 1}
        return {"assets": params.get("only", []), "colorable": [], "colorable_scanned": True}

    monkeypatch.setattr(server.bridge, "request", request)
    result = server.list_assets(category="Objects", search="barrle", match_mode="fuzzy")

    assert seen["terms"] == ["bar"]
    assert result["assets"] == ["res://textures/objects/barrel_01.png"]


def test_ranked_search_counts_matches_not_just_what_it_returned(monkeypatch):
    """`matched` was assigned after the limit, so it echoed `returned`."""
    from battlemap_mcp import server

    library = [f"res://textures/objects/round_table_{i:02d}.png" for i in range(12)]

    def request(command, **params):
        if params.get("terms"):
            return {"assets": library, "matched": len(library), "total": len(library)}
        return {"assets": params.get("only", []), "colorable": [], "colorable_scanned": True}

    monkeypatch.setattr(server.bridge, "request", request)
    result = server.list_assets(
        category="Objects", search="round table", limit=3, match_mode="tokens"
    )
    assert result["returned"] == 3
    assert result["matched"] == 12, "12 assets match; only 3 were returned"
    assert result["survey_complete"] is True


def test_a_dead_bridge_error_does_not_leak_the_token():
    """Runtime behavior and validation."""
    from battlemap_mcp.errors import BridgeUnavailableError

    exc = BridgeUnavailableError(
        "The bridge accepted the connection but sent no response.",
        last_command={"cmd": "place_object", "token": "s3cret-token-value", "asset": "x.png"},
    )
    assert "s3cret-token-value" not in str(exc)
    assert "s3cret-token-value" not in repr(exc.last_command)
    assert exc.last_command["token"] == "<redacted>"
    # the diagnostic value is kept: you can still see which command died
    assert "place_object" in str(exc)


class _DeadSocket:
    """Connects, accepts the write, then goes away without replying."""

    def __init__(self):
        self.sent = b""

    def settimeout(self, _timeout):
        pass

    def sendall(self, data):
        self.sent += data

    def recv(self, _n):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_a_connect_failure_re_resolves_a_moved_port(monkeypatch):
    """Runtime behavior and validation."""
    from battlemap_mcp import bridge_client as bc
    from battlemap_mcp.errors import BridgeUnavailableError

    ports = iter([12345, 23456])
    monkeypatch.setattr(bc, "_resolve_port", lambda: next(ports))
    client = bc.BridgeClient(token="t")

    tried: list[int] = []

    def refuse(address, timeout=None):
        tried.append(address[1])
        raise OSError("connection refused")

    monkeypatch.setattr(bc.socket, "create_connection", refuse)
    with pytest.raises(BridgeUnavailableError):
        client.request("ping")
    assert tried == [12345, 23456], "it must re-resolve and try the new port once"


def test_a_failure_after_the_request_was_sent_is_never_replayed(monkeypatch):
    """Runtime behavior and validation."""
    from battlemap_mcp import bridge_client as bc
    from battlemap_mcp.errors import BridgeUnavailableError

    resolves: list[int] = []

    def resolve():
        resolves.append(1)
        return 12345

    monkeypatch.setattr(bc, "_resolve_port", resolve)
    client = bc.BridgeClient(token="t")
    connects: list[int] = []

    def connect(address, timeout=None):
        connects.append(address[1])
        return _DeadSocket()

    monkeypatch.setattr(bc.socket, "create_connection", connect)
    with pytest.raises(BridgeUnavailableError):
        client.request("place_object", asset="x.png")
    assert len(connects) == 1, "a command already on the wire must not be sent twice"


class _SocketThatFailsAfterSending:
    """Handshakes successfully, accepts the command, then fails on the reply.

    Protocol 24 puts a challenge round trip in front of every command, so a
    fake that fails on the first recv never lets the command out — which is a
    different scenario (see the handshake-failure test below). This one answers
    hello correctly with token "t" so the command really does reach the wire.
    """

    def __init__(self, failure):
        self.failure = failure
        self.sent = b""
        self._replies: list[bytes] = []

    def settimeout(self, _timeout):
        pass

    def sendall(self, data):
        import hashlib
        import hmac
        import json

        self.sent += data
        for line in data.split(b"\n"):
            if not line:
                continue
            request = json.loads(line)
            if request.get("cmd") != "hello":
                continue
            server_nonce = "b" * 32
            message = f"dd-mcp/25|server|{request['nonce']}|{server_nonce}"
            proof = hmac.new(b"t", message.encode(), hashlib.sha256).hexdigest()
            self._replies.append(
                json.dumps(
                    {"ok": True, "result": {"protocol": 25, "nonce": server_nonce, "proof": proof}}
                ).encode()
                + b"\n"
            )

    def recv(self, _n):
        if self._replies:
            return self._replies.pop(0)
        raise self.failure

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), ConnectionResetError("reset by peer"), OSError("broken pipe")],
    ids=["timeout", "reset", "oserror"],
)
def test_a_mutation_is_never_replayed_when_the_reply_fails(monkeypatch, failure):
    """The connect and the conversation were wrapped in ONE `except OSError`, so
    a recv timeout looked like a connect failure, the port was re-resolved and
    the command was SENT AGAIN. place_object ran twice."""
    from battlemap_mcp import bridge_client as bc
    from battlemap_mcp.errors import BridgeUnavailableError

    ports = iter([12345, 23456])
    monkeypatch.setattr(bc, "_resolve_port", lambda: next(ports))
    client = bc.BridgeClient(token="t")
    sockets: list[_SocketThatFailsAfterSending] = []

    def connect(_address, timeout=None):
        sockets.append(_SocketThatFailsAfterSending(failure))
        return sockets[-1]

    monkeypatch.setattr(bc.socket, "create_connection", connect)
    with pytest.raises(BridgeUnavailableError) as excinfo:
        client.request("place_object", asset="barrel.png", x=1, y=2)

    assert len(sockets) == 1, "the request must not be sent a second time"
    sent_once = sum(1 for sock in sockets if b"place_object" in sock.sent)
    assert sent_once == 1
    assert excinfo.value.last_command is not None, (
        "a failure after sending must carry last_command; that is what stops the replay"
    )
    assert "token" not in excinfo.value.last_command, "protocol 24 sends no token"


def test_a_handshake_failure_is_safe_to_retry(monkeypatch):
    """The mirror of the test above. If the connection dies during the
    challenge, the command never went out, so re-resolving the port and trying
    again cannot run a mutation twice — and must not be forbidden as if it
    could."""
    from battlemap_mcp import bridge_client as bc
    from battlemap_mcp.errors import BridgeUnavailableError

    ports = iter([12345, 23456])
    monkeypatch.setattr(bc, "_resolve_port", lambda: next(ports))
    client = bc.BridgeClient(token="t")
    sockets: list[_SocketThatFailsAfterSending] = []

    class _DiesDuringHandshake(_SocketThatFailsAfterSending):
        def sendall(self, data):
            self.sent += data  # never answers hello

    def connect(_address, timeout=None):
        sockets.append(_DiesDuringHandshake(ConnectionResetError("reset")))
        return sockets[-1]

    monkeypatch.setattr(bc.socket, "create_connection", connect)
    with pytest.raises(BridgeUnavailableError, match="never sent"):
        client.request("place_object", asset="barrel.png", x=1, y=2)

    assert len(sockets) == 2, "a failure before the command was sent should retry"
    assert not any(b"place_object" in sock.sent for sock in sockets), (
        "the mutation must never reach the wire when the handshake failed"
    )


def test_a_failure_while_sending_is_also_never_replayed(monkeypatch):
    from battlemap_mcp import bridge_client as bc
    from battlemap_mcp.errors import BridgeUnavailableError

    # Two different ports, so the old code WOULD have re-resolved and retried:
    # pinning one port hides the bug, because the retry is skipped when the
    # re-resolved port is unchanged.
    ports = iter([12345, 23456])
    monkeypatch.setattr(bc, "_resolve_port", lambda: next(ports))
    client = bc.BridgeClient(token="t")
    attempts = []

    class _RefusesTheWrite(_SocketThatFailsAfterSending):
        """Completes the challenge, then refuses the write that carries the
        command — which is the write whose outcome is unknowable."""

        def sendall(self, data):
            if b'"hello"' in data:
                super().sendall(data)
                return
            raise BrokenPipeError("gone")

    def connect(_address, timeout=None):
        attempts.append(1)
        return _RefusesTheWrite(OSError("unused"))

    monkeypatch.setattr(bc.socket, "create_connection", connect)
    with pytest.raises(BridgeUnavailableError):
        client.request("delete_element", id=7)
    assert len(attempts) == 1


def test_dig_cave_accepts_a_single_chamber_point(monkeypatch):
    """Its own docstring says ">= 1. A single point digs one circular chamber",
    and the mod implements it — a validator requiring two broke it before it
    reached the bridge."""
    from battlemap_mcp import server

    seen = {}

    def request(command, **params):
        seen["command"] = command
        seen["points"] = params.get("points")
        return {"ok": True}

    monkeypatch.setattr(server.bridge, "request", request)
    server.dig_cave(points=[[256, 256]], radius=128)
    assert seen["command"] == "dig_cave"
    assert seen["points"] == [[256, 256]]


def test_dig_cave_fills_rock_back_in_with_dig_false(monkeypatch):
    """The cave recipe told the model to pass `erase` / `value: false`. Neither
    is a parameter of this tool, and an unknown argument is dropped at the
    boundary — so the request reached the bridge as an ordinary dig and carved
    MORE rock instead of filling it."""
    from battlemap_mcp import server

    seen = {}

    def request(command, **params):
        seen.update({"command": command, **params})
        return {"ok": True}

    monkeypatch.setattr(server.bridge, "request", request)
    server.dig_cave(points=[[256, 256]], radius=128, dig=False)
    assert seen["command"] == "dig_cave"
    assert seen["dig"] is False, "filling rock back in is dig=False"


def test_the_cave_recipe_names_parameters_this_tool_actually_has():
    """A skill that names a parameter which does not exist fails SILENTLY, so
    the prose has to be checked against the real signature."""
    import inspect
    import pathlib
    import re

    from battlemap_mcp import server

    names = set(inspect.signature(server.dig_cave).parameters)
    repo = pathlib.Path(__file__).resolve().parents[2]
    prose = (repo / "skills" / "battlemap-environments" / "SKILL.md").read_text()
    # the recipe's own section, not the whole file
    section = prose.split("## Caves are carved")[1].split("\n## ")[0]
    assert "`dig=False`" in section, "the recipe must name the real parameter"
    # Every backticked ASSIGNMENT in the section has to name a real parameter.
    # Prose may still MENTION a wrong name to warn against it ("the parameter is
    # `dig`, not `erase`"), which is why this checks assignments rather than
    # words — the original defect was an instruction to pass `erase`, and an
    # unknown argument is dropped silently at the boundary.
    assignments = {m.group(1) for m in re.finditer(r"`(\w+)\s*=", section)}
    unknown = sorted(assignments - names)
    assert not unknown, f"the recipe tells the model to pass {unknown}, which dig_cave has no"


def test_colourability_survives_the_bridge_reporting_it_as_indices(monkeypatch):
    """The bridge reports `colorable` as indices into `assets` — repeating the
    paths was 47% of a listing's bytes. Older bridges reported paths."""
    from battlemap_mcp import server

    assets = ["res://a.png", "res://b.png", "res://c.png"]
    assert server._colorable_paths({"assets": assets, "colorable": [0, 2]}) == [
        "res://a.png",
        "res://c.png",
    ]
    assert server._colorable_paths({"assets": assets, "colorable": ["res://b.png"]}) == [
        "res://b.png"
    ]
    assert server._colorable_paths({"assets": assets, "colorable": [9]}) == []
    assert server._colorable_paths({"assets": assets}) == []
