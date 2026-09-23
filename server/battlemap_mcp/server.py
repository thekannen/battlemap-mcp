"""MCP server exposing Dungeondraft map operations for AI-assisted map building.

Runs over stdio (the standard transport for Claude Desktop / Claude Code) and
forwards each tool call to the in-app bridge mod over localhost TCP.

Coordinates are in world "woxel" (pixel) space. Call get_status() for the map
size and center. Elements are referenced by integer `id` (returned by create
and list calls). Discover asset paths with list_asset_categories() +
list_assets(category, search=...).
"""

from __future__ import annotations

import functools
import hashlib
import io
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TypeVar
from uuid import uuid4

import pydantic_core
from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from . import arrangement, installer, timing
from .asset_packs import build_manifest, prepare_map_file, unknown_ids
from .asset_search import DEFAULT_MIN_SCORE, MATCH_MODES, rank_assets
from .bridge_client import BridgeClient, BridgeUnavailableError, _state_file
from .errors import BridgeProtocolError, ValidationError
from .floorplan import WOXELS_PER_TILE, analyse
from .placement import (
    DEFAULT_TOLERANCE,
    find_adrift_fixtures,
    find_intrusions,
    find_stacks,
)
from .scene import DEFAULT_EMITTER_REACH, find_bare_ground, find_unexplained_lights
from .validation import (
    reject_smart_tiles,
    require_bare_filename,
    require_choice,
    require_finite,
    require_hex_color,
    require_one_of,
    require_points,
    require_positive,
    require_rect,
    require_within,
)

# How long to let Dungeondraft settle after an operation it finishes
# asynchronously. Generation is the only one so far; walls keep changing for
# about a second after Generate() returns.
SETTLE_SECONDS = 2.0

HOST = os.environ.get("DD_BRIDGE_HOST", "127.0.0.1")
# Left as None unless explicitly set, so BridgeClient reads the port the mod
# published. Defaulting it to 8787 here silently overrode that discovery: every
# map load moves the bridge to the next port, and the server kept knocking on
# an orphaned listener that accepts connections and answers none.
_PORT_ENV = os.environ.get("DD_BRIDGE_PORT")
PORT = int(_PORT_ENV) if _PORT_ENV else None

INSTRUCTIONS = """\
Build maps in a live Dungeondraft. Call ping, then get_status: most tools need
an open map, and get_status gives map_center and map_size_woxels. If ping
fails, ask the user to start Dungeondraft; do not retry blindly.

The map is shared: the user and other AI clients can change it between your
turns. Re-read it before saying what is on it; never answer from memory.

Coordinates are woxels: 256 woxels = 1 tile, origin top-left, y grows DOWN.
Rects are [x, y, w, h]; rotation is degrees.

NEVER GUESS an asset path. Pass back one that list_assets returned, verbatim.

Order: build_room (walls + floor) -> add_portal -> floors and terrain ->
place_prefab / place_objects -> scatter_objects -> add_light -> look -> save_map.

Batch: place_objects and delete_elements take many in one undo step;
list_assets takes `searches`.

Floors: place_pattern tiles a room; fill_region / paint_terrain paint blended
ground; paint_material makes an edged patch; dig_cave carves cave floor.

Use scatter_objects for incidental detail; hand-placed rows read as a grid.
Establish a focal area, routes and quiet space; vary scale and rotation; run
shadow paths along walls.

Only draw_wall walls, add_portal doors and add_light lights carry into a VTT.

Look at your work: fit_elements() then screenshot. You see images; the user
does not, so when they ask to see one, give them its saved file path.

save_map(filename=...) after each stage.

No dedicated tool? list_tool_controls, tool_action, set_tool_option.
"""

mcp = MCPServer("battlemap", instructions=INSTRUCTIONS)
bridge = BridgeClient(HOST, PORT)

_Tool = TypeVar("_Tool", bound=Callable[..., Any])


def _model_text(result: Any) -> Any:
    """What a tool result looks like to the model: JSON results sent compact.

    The SDK serialises a returned dict with `indent=2`, which puts every number
    of a nested array on its own line: a 16x16 get_terrain came to 15,900
    characters where 2,857 carry the same data. Same serialiser, same
    fallbacks, no indentation. Images and strings pass through untouched.
    """
    if isinstance(result, list) and any(isinstance(item, Image) for item in result):
        # Image plus caption: content blocks for the client, not a JSON string.
        return result
    if isinstance(result, dict | list):
        return pydantic_core.to_json(result, fallback=str).decode()
    return result


def _result_size(row: dict, sent: Any) -> None:
    blocks = sent if isinstance(sent, list) else [sent]
    chars = sum(len(b) for b in blocks if isinstance(b, str))
    image_bytes = sum(len(b.data) for b in blocks if isinstance(b, Image) and b.data is not None)
    if chars:
        row["result_chars"] = chars
    if image_bytes:
        row["result_image_bytes"] = image_bytes


def tool() -> Callable[[_Tool], _Tool]:
    """Register a tool, returning the function itself unchanged.

    Python callers and tests keep getting dicts; only the MCP boundary sees
    the compact text. `structured_output=False` pins today's wire contract —
    one text block, no structuredContent — so an SDK that starts deriving
    schemas from `-> dict` cannot silently start sending every result twice.
    """

    def register(fn: _Tool) -> _Tool:
        @functools.wraps(fn)
        def for_the_model(*args: Any, **kwargs: Any) -> Any:
            with timing.tool_call(fn.__name__) as row:
                sent = _model_text(fn(*args, **kwargs))
                if row:
                    _result_size(row, sent)
                return sent

        mcp.add_tool(for_the_model, structured_output=False)
        return fn

    return register


# Every name the server asks the bridge to write. A capture path is only read
# when it is one of these, directly inside the output directory.
_CAPTURE_NAME = re.compile(
    r"(?:screenshot-[0-9a-f]{32}\.png|export-[0-9a-f]{32}\.(?:png|jpg|jpeg|webp)|asset_preview\.png)\Z"
)
CAPTURE_RETENTION_KEEP = max(0, int(os.environ.get("BATTLEMAP_MCP_CAPTURE_RETENTION", "20")))


def _capture_root() -> Path:
    """Resolve capture containment locally, independently of credential overrides."""
    override = os.environ.get("BATTLEMAP_MCP_CAPTURE_DIR")
    if override:
        path = Path(override)
        if not path.is_absolute():
            raise BridgeProtocolError("BATTLEMAP_MCP_CAPTURE_DIR must be absolute")
        return path
    return _state_file("mcp_output")


def _generated_capture_files() -> list[Path]:
    """Regular capture files this server is permitted to remove, newest first.

    A matching name is necessary but not sufficient: the bridge never writes
    directories or symlinks, so leave either alone even if a user gives one a
    capture-shaped name.  `unlink` below never follows a symlink, but excluding
    it here also keeps user-created links intact.
    """
    captures: list[tuple[int, Path]] = []
    try:
        for path in _capture_root().iterdir():
            if not _CAPTURE_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            captures.append((path.stat().st_mtime_ns, path))
    except OSError:
        # Retention must not turn a completed capture into an error if another
        # process changes the output directory while we inspect it.
        pass
    return [
        path
        for _, path in sorted(
            captures, key=lambda capture: (capture[0], capture[1].name), reverse=True
        )
    ]


def _remove_captures(captures: list[Path]) -> int:
    """Delete the listed regular capture files, tolerating concurrent cleanup."""
    removed = 0
    for path in captures:
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def _prune_captures(keep: int = CAPTURE_RETENTION_KEEP) -> int:
    """Keep the newest configured number of generated captures in mcp_output."""
    return _remove_captures(_generated_capture_files()[keep:])


def _capture_path(reported: object, expected_name: str | None = None) -> str:
    """`reported`, provided it is a capture file this server could have asked for."""
    root = _capture_root().resolve()
    candidate = Path(str(reported))
    resolved = candidate.resolve()
    inside = candidate.is_absolute() and os.path.normcase(str(resolved.parent)) == os.path.normcase(
        str(root)
    )
    named = (
        resolved.name == expected_name
        if expected_name is not None
        else bool(_CAPTURE_NAME.match(resolved.name))
    )
    if not (inside and named):
        raise BridgeProtocolError(
            f"the bridge reported a capture at {reported!r}, which is not a file it was "
            f"asked to write in {root}; refusing to read it. If Dungeondraft is running, "
            "something else may be listening on the bridge port."
        )
    return str(resolved)


def _downscale(data: bytes, max_px: int | None, fmt: str) -> bytes:
    """Shrink a capture's LONG EDGE to `max_px`, or return it untouched.

    The default is untouched on purpose: how small an image can get before a
    material or a scale mistake stops being visible is a question about the map,
    not about tokens, and nobody has measured it here. This is the knob for a
    caller who has — a progress check does not need delivery resolution — and
    never an upscale.
    """
    if not max_px:
        return data
    with PILImage.open(io.BytesIO(data)) as rendered:
        width, height = rendered.size
        if max(width, height) <= max_px:
            return data
        scale = max_px / float(max(width, height))
        resized = rendered.convert("RGB") if fmt in ("jpeg", "jpg") else rendered.copy()
        resized = resized.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            PILImage.Resampling.LANCZOS,
        )
        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG" if fmt in ("jpeg", "jpg") else fmt.upper())
        return buffer.getvalue()


def _require_max_px(max_px: int | None) -> None:
    if max_px is None:
        return
    if isinstance(max_px, bool) or not isinstance(max_px, int) or max_px < 64:
        raise ValidationError("max_px must be an integer of at least 64, or omitted")


def _wait_for_file(path: str, timeout: float = 60.0) -> bytes:
    """Wait for a verifiable, fully decodable image and return those exact bytes.

    A writer can pause indefinitely mid-file. Equal sizes alone prove nothing;
    validate the container and decode pixels from the same immutable snapshot.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = Path(path).read_bytes()
            with PILImage.open(io.BytesIO(data)) as rendered:
                rendered.verify()
            with PILImage.open(io.BytesIO(data)) as rendered:
                rendered.load()
            return data
        except (OSError, ValueError, SyntaxError):
            # Missing/partial files are normal while the engine writes.
            pass
        time.sleep(min(0.3, max(0.0, deadline - time.monotonic())))
    raise BridgeUnavailableError(f"render did not complete within {timeout:.0f}s ({path})")


# --------------------------------------------------------------------------
# Read / query
# --------------------------------------------------------------------------


def _package_bridge_sha256() -> str | None:
    """SHA-256 of this package's bridge source, prepared the way the bridge hashes itself.

    Dungeondraft compiles a mod from its text with a header of its own
    prepended; the bridge hashes what was compiled minus that header, which is
    this file's text. Carriage returns are dropped on both sides so a CRLF
    checkout agrees.
    """
    script = Path(str(installer.payload_root())) / "scripts" / "tools" / "mcp_bridge.gd"
    try:
        text = script.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return hashlib.sha256(text.replace("\r", "").encode("utf-8")).hexdigest()


@tool()
def ping() -> dict:
    """Check the bridge is up, and whether it is the bridge in this package.

    `bridge_current` compares a hash of the source Dungeondraft is actually
    RUNNING with this package's mcp_bridge.gd. It is the only reliable answer to
    "is Dungeondraft on the latest bridge?", because Dungeondraft loads mods from
    a folder the user chooses and a file check can look in the wrong one.

    False: Dungeondraft is running other code. Restart it to load a change, or
    reinstall into the folder it loads (inspect_dungeondraft_installation).
    None: the running bridge is too old to report its source.
    New bridges also report bridge_root (Dungeondraft's Global.Root for the
    executing mod) and process_id. These identify the running copy and process;
    they do not imply that files subsequently changed on disk are already loaded.
    """
    result = bridge.request("ping")
    if not isinstance(result, dict):
        return result
    running = result.get("bridge_sha256") or None
    expected = _package_bridge_sha256()
    if running is None or expected is None:
        result["bridge_current"] = None
    else:
        result["bridge_current"] = running == expected
        if running != expected:
            result["bridge_note"] = (
                "Dungeondraft is running a different bridge from this package. "
                "Restart Dungeondraft to load the current one; if that does not "
                "change this, the mods folder it loads holds an old copy — see "
                "inspect_dungeondraft_installation."
            )
    return result


@tool()
def get_status() -> dict:
    """Report the current map: whether one is open, its size and center in woxels,
    per-type element counts, and level info.

    Call this first — map_center is the default placement point, and counts
    tell you what's already on the map.

    `map_file` is the path the map was loaded from, "" if it has never been
    saved. open_map replaces what is loaded, so read this before opening
    another map if you mean to come back.

    `saving.in_flight` is true while Dungeondraft is writing the file. Writes
    are refused during that window because edits made mid-save are dropped from
    it — wait and retry rather than treating the refusal as an error.
    """
    return bridge.request("get_status")


@tool()
def list_asset_categories() -> dict:
    """List asset categories, with how many assets each actually holds.

    Read `populated` — a category can exist and be empty. "Patterns" ships empty
    in a vanilla Dungeondraft and fills from asset packs, so choosing it by name
    gets you nothing and no explanation. `counts` gives the full picture.

    Counts depend on which packs THIS MAP includes, not on what is installed.
    On a map that includes none, every category is core-only. See
    list_asset_packs.
    """
    return bridge.request("list_asset_categories")


@tool()
def list_asset_packs() -> dict:
    """Which asset packs are installed, and which this map can actually use.

    Dungeondraft scopes packs per MAP: a map includes a set of packs, chosen when
    it was created, and `list_assets` only ever offers assets from those. A map
    that includes none sees roughly 1800 core assets however large the user's
    library is — which is easy to miss, because nothing fails. It just quietly
    builds everything from vanilla.

    Check `installed_but_not_in_this_map` at preflight. If it is non-empty, say
    so before building: those assets are unreachable here, and anything placed
    from one would not survive a reload. `get_status.asset_packs` carries the
    same signal as two numbers.

    To USE them, the map has to include them — see prepare_map_with_packs, which
    writes a copy of the open map that includes the packs and opens it.
    """
    return bridge.request("list_asset_packs")


@tool()
def prepare_map_with_packs(filename: str, packs: list[str] | None = None) -> dict:
    """Copy the open map into one that INCLUDES asset packs, and open it.

    Dungeondraft scopes packs per map and a map's set is fixed when it is
    created, so a map made without packs can never reach them — list_assets on
    it returns only the ~1800 core assets. This writes a copy whose header
    includes the packs and opens that copy, which is how a map gets a library.

    Do this BEFORE building. The copy carries the open map across untouched, so
    running it on an empty scratch map costs nothing, while running it on a
    finished map means continuing in the copy from here on.

    filename: bare name for the new map, in the configured save directory.
    packs: pack ids to include, from list_asset_packs. REQUIRED — choose them.
      Including every installed pack is costly on a large library, and one pack
      can dominate the catalogue. Pick by subject against the brief (a forest
      pack for a forest); a map's set cannot be changed afterwards.

    The open map is saved first so the copy is current. Assets from a pack the
    map does not include are not merely hidden: placing one produces an object
    Dungeondraft erases on load, so include the packs rather than reaching past
    them.
    """
    name = require_bare_filename(filename)
    if not name.endswith(".dungeondraft_map"):
        name += ".dungeondraft_map"

    installed = bridge.request("list_asset_packs")["installed"]
    if not installed:
        raise ValidationError(
            "no asset packs are installed, so there is nothing to include; "
            "install packs in Dungeondraft first"
        )
    if packs is None:
        catalogue = "\n".join(
            f"  {p.get('id')}  {p.get('name') or '(name unavailable)'}"
            for p in sorted(installed, key=lambda p: str(p.get("name") or p.get("id")))
        )
        raise ValidationError(
            "choose which packs this map includes. Omitting them used to mean "
            "every installed pack, which is wrong for a large library: a map's "
            "set is fixed at creation, and one pack alone can carry 129,098 of "
            "141,197 objects. Pick the ones whose subject matches what you are "
            f"building:\n{catalogue}"
        )
    else:
        missing = unknown_ids(installed, packs)
        if missing:
            available = ", ".join(sorted(p["id"] for p in installed))
            raise ValidationError(f"not installed: {missing}. Installed ids: {available}")
    manifest = build_manifest(installed, packs)

    status = bridge.request("get_status")
    if not status.get("map_open"):
        raise ValidationError("no map open to copy")
    source = map_file_path(status)
    if not source:
        raise ValidationError(
            "this map has never been saved, so there is no file to copy; "
            "save_map(filename=...) first"
        )

    save_directory = Path(bridge.request("get_save_directory")["effective"])
    destination = require_within(save_directory, save_directory / name)
    if destination == Path(source).resolve():
        raise ValidationError(
            f"{name} IS the open map. This prepares a copy and leaves the original "
            "untouched — choose a different filename"
        )
    if destination.exists():
        raise ValidationError(f"{name} already exists; choose another name")

    before = int((status.get("saving") or {}).get("saves_seen", 0))
    saved = bridge.request("save_map")
    if saved.get("started") is False:
        raise ValidationError("could not save the open map before copying it")
    _wait_for_save(expected_path=str(saved.get("path") or ""), saves_before=before)

    report = prepare_map_file(Path(source), destination, manifest)
    answering = _status_before_open()
    bridge.request("open_map", path=str(destination))
    # This used to report opened: True the moment the command was sent, so a
    # placement made straight afterwards could reach the map being replaced.
    arrived = _wait_for_map(str(destination), previous=answering)
    report["opened"] = arrived["opened"]
    report["note"] = (
        "the prepared copy is now the open map; list_assets here offers every "
        "asset from the included packs"
        if arrived["opened"]
        else arrived["note"]
    )
    return report


ELEMENT_READ_BUDGET = 20000

# Most cells validate_floorplan will flood-fill. Past this the analysis is not
# slow but unbounded, and it runs in this process rather than the editor's.
MAX_ANALYSIS_CELLS = 400_000


def _read_all(
    kind: str, *, include_points: bool = False, budget: int = ELEMENT_READ_BUDGET
) -> tuple[list, dict]:
    """Every element of one kind, paged, plus how much it actually covered."""
    elements: list = []
    total = 0
    offset = 0
    while True:
        page = bridge.request(
            "list_elements",
            kind=kind,
            limit=500,
            offset=offset,
            include_points=include_points,
        )
        batch = list(page.get("elements", []))
        total = int(page.get("total", len(batch)))
        elements.extend(batch)
        offset += len(batch)
        if not batch or offset >= total or len(elements) >= budget:
            break
    return elements, {
        "kind": kind,
        "total": total,
        "read": len(elements),
        "complete": len(elements) >= total,
    }


def _with_coverage(report: dict, coverages: list[dict]) -> dict:
    """Attach read coverage, and refuse to call a partly-read map clean."""
    report["coverage"] = {
        cover["kind"]: {k: cover[k] for k in ("total", "read", "complete")} for cover in coverages
    }
    missed = [cover for cover in coverages if not cover["complete"]]
    report["complete"] = not missed
    if missed:
        report["ok"] = False
        short = ", ".join(f"{c['kind']} {c['read']} of {c['total']}" for c in missed)
        warning = (
            f"INCOMPLETE: only {short} could be read, so this verdict does not cover "
            "the whole map and is NOT a clean result."
        )
        report["note"] = f"{warning} {report['note']}" if report.get("note") else warning
    return report


def map_file_path(status: dict) -> str:
    """The map's file path, or \"\" when it has never been saved."""
    value = str(status.get("map_file") or "").strip()
    return "" if value in ("", "Null", "null", "<null>") else value


def _wait_for_save(
    expected_path: str = "",
    saves_before: int = -1,
    timeout: float = 60.0,
    strict: bool = True,
) -> dict:
    """Block until Dungeondraft has DEMONSTRABLY finished writing the map.

    What settles it is `last_saved`, the path Dungeondraft reports it finished
    writing: a backup goes to `user://backups/...` and will not match.

    `strict` chooses what an unconfirmed save means. A caller about to COPY the
    file (prepare_map_with_packs) must not proceed on a maybe, so it raises. A
    caller that merely waited for its own save gets `{\"completed\": False}` and
    the reason: the save may still be running, and the one thing that must not
    follow an uncertain save is another save.
    """
    deadline = time.time() + timeout
    state: dict = {}
    while time.time() < deadline:
        state = bridge.request("get_status")["saving"]
        if state.get("last_result") == "stale":
            raise ValidationError(
                f"Dungeondraft started saving {state.get('stale_path') or 'the map'} "
                f"and never reported finishing it, so the file is probably incomplete "
                f"and must not be copied. {state.get('note') or ''}"
            )
        if not state.get("in_flight"):
            settled = int(state.get("saves_seen", 0)) > saves_before
            if expected_path:
                settled = settled and str(state.get("last_saved") or "") == expected_path
            if settled:
                return {**state, "completed": True}
            if not state.get("tracked"):
                if strict:
                    raise ValidationError(
                        "this Dungeondraft is not reporting save events, so a finished "
                        "save cannot be confirmed; the file must not be treated as written"
                    )
                return {
                    **state,
                    "completed": False,
                    "reason": "untracked",
                    "note": (
                        "this Dungeondraft is not reporting save events, so the save "
                        "cannot be confirmed from here. Check the file's timestamp before "
                        "relying on it; do not assume it was not written."
                    ),
                }
        time.sleep(0.5)
    if strict:
        raise ValidationError(
            f"the map did not finish saving within {timeout}s "
            f"(last_saved={state.get('last_saved')!r}, saves_seen={state.get('saves_seen')!r}); "
            "not copying a file that may be partial"
        )
    return {
        **state,
        "completed": False,
        "reason": "still_saving",
        "note": (
            f"the save had not finished after {timeout:.0f}s. It is probably still "
            "running — do NOT call save_map again, which would start a second write of "
            "the same file. Poll get_status until saving.in_flight is false and "
            "saving.last_saved names this path."
        ),
    }


MAX_SEARCHES = 8
# The most assets one multi-term call returns in total. A term's own `limit`
# still applies; this is what stops several generous terms compounding into one
# enormous result. Measured: four terms at limit=40 returned 160 paths in a
# single 25,700-character block — compact, and still more than a caller
# choosing between assets can use. A search is for picking a handful.
MAX_MULTI_RESULTS = 80


# How many candidate paths a ranked search pulls back to score locally. The
# whole category used to come across so the server could rank it, which on a
# 141,197-asset library exceeded the bridge's own buffer cap: it dropped the
# connection mid-response and every tokens/fuzzy search failed outright
# (measured 2026-09-14). The bridge now filters to candidates first.
RANK_CANDIDATE_LIMIT = 2000
# Fuzzy has to tolerate a typo, and a misspelt term cannot be its own filter.
# A prefix can: "barrle" prefixed to "bar" still reaches barrel. Short terms
# are sent whole.
FUZZY_PREFIX = 3


def _candidate_terms(query: str, mode: str) -> list[str]:
    """What the bridge filters on for this query, given how it will be scored."""
    words = [word for word in re.split(r"[^A-Za-z0-9]+", query.lower()) if word]
    if mode == "fuzzy":
        return [word[:FUZZY_PREFIX] for word in words]
    return words


def _candidates(category: str, query: str, mode: str, vanilla_only: bool) -> dict:
    """Paths worth scoring for this query, filtered in the bridge."""
    request: dict = {
        "category": category,
        "terms": _candidate_terms(query, mode),
        "limit": RANK_CANDIDATE_LIMIT,
    }
    if vanilla_only:
        request["vanilla_only"] = True
    return bridge.request("list_assets", **request)


def _colorable_indices(assets: list[str], colourable: set[str]) -> list[int]:
    """Which of `assets` carry a colour mask, as positions rather than paths.

    Repeating the paths is what made `colorable` 47% of a listing. The caller
    already has the list; an index into it says the same thing in three
    characters.
    """
    return [index for index, path in enumerate(assets) if path in colourable]


def _colorable_paths(answer: dict) -> list[str]:
    """`colorable` as paths, whichever way the bridge reported it.

    The bridge reports indices into `assets` — repeating the paths was 47% of a
    listing's bytes. Older bridges reported the paths themselves, and a mixed
    pair is exactly what a partial upgrade looks like.
    """
    assets = list(answer.get("assets", []))
    out = []
    for entry in answer.get("colorable", []):
        if isinstance(entry, int) and not isinstance(entry, bool):
            if 0 <= entry < len(assets):
                out.append(assets[entry])
        else:
            out.append(str(entry))
    return out


def _distinct_terms(searches: list[str]) -> list[str]:
    """The terms as given, minus blanks and repeats, order preserved."""
    seen: set[str] = set()
    terms: list[str] = []
    for raw in searches:
        term = str(raw).strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        terms.append(term)
    return terms


def _list_assets_many(
    category: str,
    searches: list[str],
    search: str,
    limit: int,
    vanilla_only: bool,
    match_mode: str,
    min_score: float,
) -> dict:
    """Several searches in one call, surveying the category at most once.

    The saving is a round trip per term for the model, and — in the ranked
    modes — one whole-category survey instead of one per term for the editor,
    which is the expensive half. Every term still reports its own matches,
    because merging them would hide which term found nothing.
    """
    if search:
        raise ValidationError(
            "pass either search or searches, not both — searches already takes a list"
        )
    terms = _distinct_terms(searches)
    if not terms:
        raise ValidationError("searches must hold at least one non-empty term")
    if len(terms) > MAX_SEARCHES:
        raise ValidationError(
            f"{len(terms)} searches is past the {MAX_SEARCHES} one call runs; "
            "split them, or search a broader term and read the listing"
        )
    require_positive(limit, "limit")
    per_term = min(limit, max(1, MAX_MULTI_RESULTS // len(terms)))

    out: dict = {"category": category, "match_mode": match_mode, "terms": terms}
    results: dict[str, dict] = {}

    if match_mode == "substring":
        # The bridge filters substrings over the whole category, so each term is
        # its own cheap request; there is nothing to reuse between them.
        for term in terms:
            params = {"category": category, "search": term, "limit": per_term}
            if vanilla_only:
                params["vanilla_only"] = True
            answer = bridge.request("list_assets", **params)
            results[term] = {
                "matched": answer.get("matched", 0),
                "returned": answer.get("returned", 0),
                "assets": answer.get("assets", []),
                "colorable": _colorable_indices(
                    list(answer.get("assets", [])), set(_colorable_paths(answer))
                ),
                "colorable_scanned": answer.get("colorable_scanned", False),
            }
            for shared in ("total", "total_unfiltered", "hidden_unusable"):
                out.setdefault(shared, answer.get(shared, 0))
    else:
        # One candidate filter per term, each bounded, instead of one transfer
        # of the whole category for the call: the category is the thing that
        # does not fit.
        survey_complete = True
        chosen: list[str] = []
        for term in terms:
            everything = _candidates(category, term, match_mode, vanilla_only)
            surveyed = list(everything.get("assets", []))
            for shared in ("total", "total_unfiltered", "hidden_unusable"):
                out.setdefault(shared, everything.get(shared, 0))
            if int(everything.get("matched", len(surveyed))) > len(surveyed):
                survey_complete = False
            matches = rank_assets(surveyed, term, mode=match_mode, min_score=min_score)
            ranked = matches[:per_term]
            results[term] = {
                "matched": len(matches),
                "returned": len(ranked),
                "assets": [match.path for match in ranked],
                "scores": [round(match.score, 3) for match in ranked],
            }
            chosen.extend(path for path in results[term]["assets"] if path not in chosen)

        # One colour-mask scan for every winner, not one per term: the same asset
        # can win for two terms, and the mask is a property of the asset.
        colorable: set[str] = set()
        scanned = True
        if chosen:
            detail = bridge.request(
                "list_assets", category=category, only=chosen, limit=len(chosen)
            )
            colorable = set(_colorable_paths(detail))
            scanned = bool(detail.get("colorable_scanned", False))
        for entry in results.values():
            entry["colorable"] = _colorable_indices(entry["assets"], colorable)
            entry["colorable_scanned"] = scanned

        out["survey_complete"] = survey_complete
        if not survey_complete:
            out["note"] = (
                f"at least one term matched more than the {RANK_CANDIDATE_LIMIT} "
                "candidates a ranked search scores, so better matches may exist that "
                "were never scored. A term with no matches here is NOT a reliable "
                "'not found' — use match_mode='substring', which filters in the bridge "
                "over the whole category."
            )

    out["results"] = results
    out["colorable_are"] = "indices into that term's assets"
    out["per_term_limit"] = per_term
    empty = [term for term, found in results.items() if not found["assets"]]
    if empty:
        shortfall = (
            f"no asset matched {empty}. This is string matching, not meaning: widen the "
            "term, or list the category to see what vocabulary it uses."
        )
        out["note"] = f"{out['note']} {shortfall}" if out.get("note") else shortfall
    return out


@tool()
def list_assets(
    category: str = "Objects",
    search: str = "",
    limit: int = 100,
    vanilla_only: bool = False,
    match_mode: str = "substring",
    min_score: float = DEFAULT_MIN_SCORE,
    searches: Annotated[
        list[str] | None,
        Field(
            max_length=MAX_SEARCHES,
            description=(
                f"Up to {MAX_SEARCHES} terms looked up in one call, instead of `search`. "
                "They share one budget of results, so more terms means fewer each."
            ),
        ),
    ] = None,
) -> dict:
    """List asset paths in a category, optionally filtered by a case-insensitive substring.

    category: e.g. 'Objects', 'Walls', 'Paths', 'Terrain', 'Lights', 'Portals', 'Roofs'.
    search: substring matched against the asset path ('chair', 'door', 'grass').
    Pass a returned path, verbatim, as the 'asset' of the create tools.

    searches: up to 8 terms in one call instead of `search` — tables AND chairs
    AND barrels. More than 8 is refused; split the call. Results come back
    under `results`, keyed by term. Terms SHARE a budget of 80 paths, reported
    as `per_term_limit`, so this is for choosing a handful, not reading the
    catalogue. Pass `searches` or `search`, not both.

    Results depend on the packs THIS MAP includes: none gives the ~1800 core
    assets, a full library over a hundred thousand. If a search comes up thin,
    check list_asset_packs before concluding an asset does not exist.

    `colorable` lists INDEXES into `assets` of assets with an unpainted colour
    mask. They render flat RED unless you pass `color` at placement, and colour
    cannot be changed afterwards — check before choosing. `colorable_scanned`
    false means the result was too large to scan: narrow the search.

    match_mode: 'substring' (default, contiguous); 'tokens' (every word appears
    anywhere, any order: "table round" finds round_table_01); 'fuzzy' (tokens
    plus resemblance, so "barrle" lands; ranked, with `scores`). min_score is
    the 0..1 cutoff for 'fuzzy'. None of these understand meaning — "mug" will
    not find a tankard — so widen a term or list the category before
    concluding something is absent.

    vanilla_only: exclude optional packs, when native assets would otherwise be
    crowded out of the result page.
    """
    require_choice(match_mode, list(MATCH_MODES), "match_mode")
    if not 0.0 <= min_score <= 1.0:
        raise ValidationError(f"min_score must be between 0 and 1, got {min_score}")
    if searches is not None:
        return _list_assets_many(
            category, searches, search, limit, vanilla_only, match_mode, min_score
        )

    if match_mode == "substring" or not search:
        params = {"category": category, "search": search, "limit": limit}
        if vanilla_only:
            params["vanilla_only"] = True
        return bridge.request("list_assets", **params)

    # Ranked modes need the whole category to rank over, which is more than the
    # colour-mask scan will cover — so pull the paths, rank here, then ask for
    # the winners BY NAME. That second call is what keeps `colorable` populated
    # for the handful the caller actually chooses between, which matters
    # because colour is baked at placement and cannot be fixed afterwards.
    everything = _candidates(category, search, match_mode, vanilla_only)
    surveyed = list(everything.get("assets", []))
    survey_complete = int(everything.get("matched", len(surveyed))) <= len(surveyed)

    all_matches = rank_assets(surveyed, search, mode=match_mode, min_score=min_score)
    ranked = all_matches[:limit]

    result: dict = {
        "category": category,
        "match_mode": match_mode,
        "total": everything.get("total", 0),
        "total_unfiltered": everything.get("total_unfiltered", 0),
        "hidden_unusable": everything.get("hidden_unusable", 0),
        "surveyed": len(surveyed),
        "survey_complete": survey_complete,
        "matched": len(all_matches),
        "returned": len(ranked),
        "assets": [match.path for match in ranked],
        "scores": [round(match.score, 3) for match in ranked],
        "matched_terms": [list(match.matched) for match in ranked],
    }
    if not ranked:
        result["colorable"] = []
        result["colorable_scanned"] = True
        if not survey_complete:
            # Never advise broadening a search that was never scored in full:
            # the missing match may simply be past the candidate cap.
            result["note"] = (
                f"no asset scored at or above {min_score} for {search!r}, but only "
                f"{len(surveyed)} of {everything.get('matched')} candidate paths in "
                f"{category} were scored (the cap is {RANK_CANDIDATE_LIMIT}). This is "
                "NOT a reliable 'not found' — narrow the search, or use "
                "match_mode='substring', which filters in the bridge over the whole "
                "category."
            )
            return result
        result["note"] = (
            f"no asset scored at or above {min_score} for {search!r} in {category}. "
            "This is string matching, not meaning — try a broader term, or list "
            "the category without a search to see what vocabulary it uses."
        )
        return result

    detail = bridge.request(
        "list_assets", category=category, only=result["assets"], limit=len(ranked)
    )
    result["colorable"] = _colorable_indices(result["assets"], set(_colorable_paths(detail)))
    result["colorable_are"] = "indices into assets"
    result["colorable_scanned"] = detail.get("colorable_scanned", False)
    result["note"] = detail.get("note", "")
    if not survey_complete:
        incomplete = (
            f"only {len(surveyed)} of {everything.get('matched')} candidate paths in "
            f"{category} were scored (the cap is {RANK_CANDIDATE_LIMIT}), so better "
            "matches may exist that were never scored."
        )
        result["note"] = f"{incomplete} {result['note']}".strip()
    return result


@tool()
def preview_assets(
    assets: list[str],
    category: str = "Objects",
    columns: int = 4,
    cell_px: int = 128,
) -> Image:
    """LOOK at candidate assets before committing to one. Read-only.

    Asset names are not reliable descriptions: `bench_01` is a stone bench, and
    that is easy to miss until it is placed in a timber tavern.

    Returns ONE contact sheet, so comparing N candidates costs one image. Cells are laid out
    row-major **in the order you passed them**, so you already know which is
    which — pass the candidates in a deliberate order.

    Assets drawn on a BLUE-GREY ground are colourable: what you are seeing is
    the unpainted red mask, not the asset's real colour. It will render in
    whatever `color` you pass at placement, and flat red if you pass none.
    Everything else sits on neutral grey and is showing its actual art.

    Use this when CHOOSING a material family — the structural, supporting and
    accent families a map commits to — not before every placement. A map uses
    few distinct assets and repeats each many times, so the decisions worth
    looking at are a handful per map.

    A thumbnail on a plain ground will not tell you how something reads against
    your floor under your lighting. It catches the gross mistake (stone where
    you wanted wood); the map render still settles the subtle one.

    assets: paths from list_assets, at most 32. category must match them.
    columns: 1-8. cell_px: 32-256, the size each asset is fitted into.
    """
    if not assets:
        raise ValidationError("assets must not be empty — pass paths from list_assets")
    if len(assets) > 32:
        raise ValidationError(
            f"{len(assets)} assets is more than one sheet can show usefully (max 32). "
            "Narrow the candidates with list_assets first — the point is to choose "
            "between a few, not to browse the library."
        )
    require_choice(columns, list(range(1, 9)), "columns")
    if not 32 <= cell_px <= 256:
        raise ValidationError(f"cell_px must be between 32 and 256, got {cell_px}")
    result = bridge.request(
        "preview_assets",
        category=category,
        assets=list(assets),
        columns=columns,
        cell_px=cell_px,
        name="asset_preview.png",
    )
    # Read and decoded here, not handed to Image(path=...), which base64s any
    # file at all without looking at it.
    data = _wait_for_file(_capture_path(result.get("path"), "asset_preview.png"), timeout=10.0)
    _prune_captures()
    return Image(data=data, format="png")


@tool()
def repair_terrain(force: bool = False) -> dict:
    """Rebuild a level's terrain splat when the engine dropped it. Destructive.

    Only needed on a map whose terrain has already been lost. Symptom: every
    terrain call answers "the terrain splat image is empty", and Dungeondraft's
    log carries `Expected data size of N bytes in Image::create()` at load.

    That happens when a map was resized while its terrain was not. The splat
    keeps the pixel dimensions it was created with, the mismatch is silent
    until the map is next opened, and Godot then refuses the image and drops
    every painted stroke — while the save that produced it reported success.
    set_map_size now resizes the rasters with the map, so new maps do not reach
    this state; this repairs one that already did.

    It does not recover anything. The painted terrain is gone before this runs;
    all it restores is a usable surface to paint on, so the terrain has to be
    laid down again afterwards. Nothing else on the map is touched.

    force: blank a splat that is already usable. This throws away working
      terrain, so it is off by default.
    """
    status = bridge.request("get_status")
    if not status.get("map_open"):
        raise ValidationError("no map open")
    return bridge.request("repair_terrain", force=force)


@tool()
def validate_scene(samples: int = 48, emitter_reach: float = DEFAULT_EMITTER_REACH) -> dict:
    """Check that the map has ground and that its light has causes. Read-only.

    Two failures that a render shows but cannot diagnose, and that no element
    count can show at all:

      bare_ground   open ground with no terrain painted on it. Terrain is the
                    one part of a map with no element count, so a building
                    standing in an unpainted void reports as a complete,
                    correct map everywhere else. Cells occupied or enclosed by
                    walls are skipped — an interior is floored with patterns,
                    not terrain, and would otherwise read as bare on a
                    perfectly finished map.
      lights        every light, split into `explained` (something nearby could
                    be emitting it) and `unexplained` (nothing could). A pool
                    of warm light on bare boards with no candle, hearth or
                    lantern reads as a mistake immediately, and a viewer
                    notices before they can say why.

    The light half matches emitters on asset NAME. That makes it a prompt to
    look rather than a verdict: an oddly named source reads as unexplained, and
    an unlit lantern placed as decor reads as an explanation. Read `explained`
    too — it names the asset it credited, so a wrong match is visible.

    `arrangement` is advice and never affects `ok`: how many objects sit at
    scale 1.0 on quarter turns, and how much of the map the build covers.

    Outdoors, remember the global condition is itself a source. Under daylight
    the open ground needs no local sources at all; at night it wants the light
    to come from things that are in the scene.

    samples: grid resolution per side for the terrain read, 2-64. Higher is
      slower and finds smaller gaps.
    emitter_reach: how close (in woxels) an emitter must be to account for a
      light. One tile by default — a light is meant to sit on its source.
    """
    if samples < 2 or samples > 64:
        raise ValidationError("samples must be between 2 and 64")
    if emitter_reach <= 0:
        raise ValidationError("emitter_reach must be positive")
    status = bridge.request("get_status")
    if not status.get("map_open"):
        raise ValidationError("no map open")
    map_size = tuple(status.get("map_size_woxels", [0, 0]))

    wall_list, wall_cover = _read_all("walls", include_points=True)
    terrain = bridge.request("get_terrain", samples=samples)
    object_list, object_cover = _read_all("objects")
    light_list, light_cover = _read_all("lights")

    ground = find_bare_ground(
        map_size,
        list(terrain.get("weights", [])),
        wall_list,
        slots=terrain.get("slots"),
    )
    lit = find_unexplained_lights(light_list, object_list, reach=emitter_reach)
    return _with_coverage(
        {
            "bare_ground": ground,
            "lights": lit,
            "arrangement": arrangement.review(map_size, object_list, wall_list, light_list),
            "ok": ground["ok"] and lit["ok"],
            "level_id": status.get("level_id"),
        },
        [wall_cover, object_cover, light_cover],
    )


@tool()
def validate_floorplan(cell_woxels: int = 64, min_room_tiles: float = 1.0) -> dict:
    """Check a floorplan's structure BEFORE furnishing it. Read-only.

    Answers the questions element counts cannot: is every room reachable, does
    every door open onto something, and is there a way in from outside. A sealed
    room and a connected one have identical counts.

    Returns the enclosed regions with their area and bounds, which portals each
    touches, and `findings`:

      sealed_regions         enclosed areas with no route from outside, even
                             with every door treated as open. Usually a missing
                             door, or one that missed its wall.
      portals_not_in_a_wall  a door touching no wall — what a failed wall-mount
                             looks like. It cuts no opening in anything.
      portals_to_nowhere     a door whose two sides are the same region, so it
                             connects nothing.
      exterior_openings      portals connecting a region to the outside. Note
                             this cannot tell a door from a window — both are
                             portals — so a building listed here may still have
                             no way IN. Check the assets before trusting it.

    `ok` is true when nothing in the first three lists appeared. Treat it as a
    gate: no furniture, foliage or dressing until it passes, because repairing
    structure after furnishing means moving everything twice.

    Doors are analysed as openings regardless of their `closed` flag — that
    controls light, not movement.

    cell_woxels: analysis resolution, 64 (a quarter tile) by default. Smaller
      is more exact and slower; a value above a door's width can seal doorways
      and report false failures.
    min_room_tiles: ignore enclosed areas below this, so the sliver between two
      nearly-touching walls is not reported as a room.
    """
    require_positive(cell_woxels, "cell_woxels")
    if cell_woxels > WOXELS_PER_TILE:
        raise ValidationError(
            f"cell_woxels={cell_woxels} is coarser than one tile ({WOXELS_PER_TILE}); "
            "a doorway would be sealed by rounding and every room would read as "
            "unreachable. Use 128 or less."
        )
    status = bridge.request("get_status")
    if not status.get("map_open"):
        raise ValidationError("no map open")
    size = list(status.get("map_size_woxels") or [0, 0])
    cells = (float(size[0]) / cell_woxels) * (float(size[1]) / cell_woxels)
    if cells > MAX_ANALYSIS_CELLS:
        raise ValidationError(
            f"cell_woxels={cell_woxels} divides this {int(size[0])}x{int(size[1])} map into "
            f"{int(cells):,} cells, past the {MAX_ANALYSIS_CELLS:,} this analysis will "
            "attempt. Use a larger cell; 64 (a quarter tile) is the default and is "
            "finer than any doorway."
        )
    wall_list, wall_cover = _read_all("walls", include_points=True)
    portal_list, portal_cover = _read_all("portals")
    report = analyse(
        tuple(status.get("map_size_woxels", [0, 0])),
        wall_list,
        portal_list,
        cell=cell_woxels,
        min_room_tiles=min_room_tiles,
    )
    report["level_id"] = status.get("level_id")
    report["level_count"] = status.get("level_count")
    return _with_coverage(report, [wall_cover, portal_cover])


@tool()
def validate_placements(tolerance_woxels: float = DEFAULT_TOLERANCE) -> dict:
    """Find objects that intrude on the architecture. Read-only.

    Use it after furnishing, before judging the render by eye. These defects
    look correct in every element count and placement response.

    What it reports:

      crossing_walls    an object with real footprint on BOTH sides of a wall.
                        Sitting flush against a wall is correct placement and
                        is never reported.
      blocking_portals  an object standing in a doorway or across a window.
      unmeasurable      objects the bridge returned no texture_size for, so
                        nothing could be checked. Not the same as clean; if
                        this is non-empty the map is only partly validated.
      stacked           two LARGE objects in one place on one layer — crates
                        inside crates, a tent through a wagon. Deliberate pairs
                        land here too (a spit over a fire), so look before
                        moving anything. Advice; never changes `ok`.
      adrift_fixtures   torches, tapestries, hearths and the like standing away
                        from any wall. Matched by asset name, so read the
                        reported distance and decide.

    Dressing a surface is NOT reported: a tankard on a table, bread on a
    bench, a lantern on a post. Those sit on a higher layer than what they
    rest on, which is how `stacked` tells the two apart — same layer, both
    large, heavily overlapping.

    Footprints are rotation-aware; `fit_elements` bounds are not, so every
    rotated object would read as a defect if you checked from those.

    A finding is evidence, not a verdict — read the position and decide. A
    hearth set INTO a thick wall is a deliberate choice this will report.

    tolerance_woxels: how far past a wall's centre line an object may reach on
      both sides before it counts as crossing. The default (24) keeps flush
      furniture quiet; lower it to catch shallower intrusions.
    """
    if tolerance_woxels < 0:
        raise ValidationError("tolerance_woxels cannot be negative")
    status = bridge.request("get_status")
    if not status.get("map_open"):
        raise ValidationError("no map open")
    object_list, object_cover = _read_all("objects")
    wall_list, wall_cover = _read_all("walls", include_points=True)
    portal_list, portal_cover = _read_all("portals")
    report = find_intrusions(
        object_list,
        wall_list,
        portal_list,
        tolerance=tolerance_woxels,
    )
    report["stacked"] = find_stacks(object_list)
    report["adrift_fixtures"] = find_adrift_fixtures(object_list, wall_list)
    report["level_id"] = status.get("level_id")
    return _with_coverage(report, [object_cover, wall_cover, portal_cover])


@tool()
def list_elements(
    kind: str = "objects", limit: int = 200, include_points: bool = False, offset: int = 0
) -> dict:
    """List elements currently on the map with their ids, positions, rotation, scale and asset.

    kind: one of 'objects', 'walls', 'lights', 'paths', 'portals', 'roofs', 'texts'.
    Use the returned ids with move_element / modify_object / delete_element / select_elements.

    include_points: also return each wall's and path's polyline. Walls and paths
      are shapes, not points — without this they report a meaningless single
      position (a real hand-built map lists every wall at [0, 0]). Off by
      default because a map can hold hundreds of paths and the coordinates
      swamp the listing; get_element always includes them for one element.
    offset: skip this many before returning, for paging through a large map.

    `total` is how many elements of this kind exist, `count` how many came back,
    and `truncated` says plainly that there are more. Read `total`, not `count`,
    before concluding anything about the whole map.
    """
    return bridge.request(
        "list_elements", kind=kind, limit=limit, include_points=include_points, offset=offset
    )


@tool()
def get_composition_snapshot() -> dict:
    """Describe the current map's spatial structure for generation or review.

    Returns map bounds, a fixed 3-by-3 grid, every kind's element count,
    occupied grid cells, and geometric bounds. It is a compact factual summary
    of the map currently open in Dungeondraft, not an aesthetic score or a
    substitute for a whole-map export and focused screenshot.
    """
    return bridge.request("get_composition_snapshot")


@tool()
def get_element(id: int) -> dict:
    """Get details (kind, position, rotation, scale, asset) for a single element by id."""
    return bridge.request("get_element", id=id)


@tool()
def list_levels() -> dict:
    """List the map's levels (floors) with their index, id and label, plus the current index."""
    return bridge.request("list_levels")


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------


@tool()
def place_object(
    asset: str,
    x: float | None = None,
    y: float | None = None,
    scale: float = 1.0,
    rotation: float = 0.0,
    sorting: int = 0,
    layer: int = 100,
    color: str = "",
    modulate: str = "",
    block_light: bool | None = None,
) -> dict:
    """Place an object (prop) on the current map. Returns the new element id.

    If you place a colourable asset WITHOUT a colour, the response comes back
    with `colorable: true` and says so: the object is on the map as a flat red
    shape. Colour is baked at placement, so the fix is to delete it and place
    it again with `color`.

    asset: an Objects asset path from list_assets(category='Objects').
    x, y: woxel coordinates; defaults to map center. rotation: degrees.
    sorting: 0=over, 1=under.

    Two different tints, do not confuse them:

    color: '#rrggbb', Dungeondraft's own colourable-asset colour — the same
      thing the app's colour picker sets. Only assets carrying the colourable
      attribute respond to it (including colorable carpets and crystals). On any
      other asset it is stored and never renders.
    modulate: retained for compatibility, but nonempty values are refused because
      Dungeondraft does not preserve this tint when saving and reopening.

    layer: which layer the object is drawn on — a VALUE, a multiple of 100 from
      -500 to 900, not a menu index. 100 is the default and where most objects
      belong. Raise it to put something ON a surface: a floor pattern sits on
      100, so a mug placed on 100 can be buried by it, while 200 puts the mug
      above. `sorting` only reorders siblings within one layer and cannot do
      this. The response reports the layer the object actually landed on.
    """
    require_positive(scale, "scale")
    require_choice(sorting, [0, 1], "sorting")
    require_choice(layer, list(range(-500, 1000, 100)), "layer")
    require_finite(x, "x")
    require_finite(y, "y")
    require_finite(rotation, "rotation")
    require_hex_color(color, "color")
    require_hex_color(modulate, "modulate")
    if modulate:
        raise ValidationError(
            "modulate is unavailable because Dungeondraft does not preserve it when saving "
            "and reopening. No changes were made."
        )
    params = {
        "asset": asset,
        "scale": scale,
        "rotation": rotation,
        "sorting": sorting,
        "layer": layer,
    }
    if x is not None:
        params["x"] = x
    if y is not None:
        params["y"] = y
    if color:
        params["color"] = color
    if modulate:
        params["modulate"] = modulate
    if block_light is not None:
        params["block_light"] = block_light
    return bridge.request("place_object", **params)


BATCH_LIMIT = 100


class PlacedObject(BaseModel):
    """One entry of a place_objects batch: place_object's arguments for one object."""

    model_config = ConfigDict(extra="forbid")

    asset: str
    x: float | None = None
    y: float | None = None
    scale: float = 1.0
    rotation: float = 0.0
    sorting: int = 0
    layer: int = 100
    color: str = ""
    modulate: str = ""
    block_light: bool | None = None


@tool()
def place_objects(objects: list[PlacedObject]) -> dict:
    """Place many objects at chosen positions in ONE call and ONE undo step.

    Use it whenever you know where several things go: a row of tables, the
    dressing on a bar, eight trees ringing a clearing. Each entry takes the
    same arguments as place_object and behaves identically.

    `scatter_objects` is for RANDOM arrangement over an area; this is for
    deliberate positions.

    Up to 100 entries. Every asset is checked before anything is placed, and if
    one entry fails the whole batch is rolled back, so the map never holds a
    half-finished batch whose ids you were not told.

    Returns `objects`: one {id, position, layer} per entry, in the order you
    passed them, plus `ids`. Entries placed from a colourable asset with no
    color are listed in the note: those are flat red, and colour cannot be
    added afterwards.

    One undo() reverses the whole batch while it is the latest operation.

    A batch placed entirely at scale 1.0 on quarter turns comes back with an
    `arrangement_note`: most placements read better with slight variation.
    """
    if not objects:
        raise ValidationError("objects must not be empty")
    if len(objects) > BATCH_LIMIT:
        raise ValidationError(
            f"{len(objects)} objects is past the {BATCH_LIMIT} one call places; "
            "split it, or use scatter_objects for incidental detail"
        )
    items: list[dict] = []
    for index, entry in enumerate(objects):
        where = f"objects[{index}]"
        # An MCP caller's entries arrive validated; a Python caller's are plain
        # dicts, and both have to behave the same way.
        if isinstance(entry, PlacedObject):
            item = entry
        else:
            try:
                item = PlacedObject.model_validate(entry)
            except PydanticValidationError as invalid:
                raise ValidationError(f"{where}: {invalid.errors()[0]['msg']}") from invalid
        if not item.asset:
            raise ValidationError(f"{where} needs an asset path from list_assets")
        require_positive(item.scale, f"{where}.scale")
        require_choice(item.sorting, [0, 1], f"{where}.sorting")
        require_choice(item.layer, list(range(-500, 1000, 100)), f"{where}.layer")
        require_finite(item.x, f"{where}.x")
        require_finite(item.y, f"{where}.y")
        require_finite(item.rotation, f"{where}.rotation")
        require_hex_color(item.color, f"{where}.color")
        require_hex_color(item.modulate, f"{where}.modulate")
        if item.modulate:
            raise ValidationError(
                f"{where}.modulate is unavailable because Dungeondraft does not preserve it "
                "when saving and reopening. No changes were made."
            )
        params: dict = {
            "asset": item.asset,
            "scale": item.scale,
            "rotation": item.rotation,
            "sorting": item.sorting,
            "layer": item.layer,
        }
        if item.x is not None:
            params["x"] = item.x
        if item.y is not None:
            params["y"] = item.y
        if item.color:
            params["color"] = item.color
        if item.modulate:
            params["modulate"] = item.modulate
        if item.block_light is not None:
            params["block_light"] = item.block_light
        items.append(params)
    result = bridge.request("place_objects", objects=items)
    note = arrangement.batch_note(items)
    if note and isinstance(result, dict):
        result["arrangement_note"] = note
    return result


@tool()
def draw_wall(
    points: list[list[float]],
    asset: str = "",
    loop: bool = False,
    shadow: bool = True,
    type: int = 0,
    joint: int = 1,
    color: str = "",
) -> dict:
    """Draw a wall through a list of [x, y] woxel points. Returns the new element id.

    asset: optional Walls asset path. loop: close into a loop (e.g. a room).
    type: 0=auto, 1=manual, 2=cave. joint: 0=sharp, 1=bevel, 2=round.
    """
    require_points(points, minimum=2)
    require_choice(type, [0, 1, 2], "type")
    require_choice(joint, [0, 1, 2], "joint")
    require_hex_color(color, "color")
    return bridge.request(
        "draw_wall",
        points=points,
        asset=asset,
        loop=loop,
        shadow=shadow,
        type=type,
        joint=joint,
        color=color,
    )


@tool()
def merge_walls(ids: list[int]) -> dict:
    """Join two matching open walls sharing one endpoint, in ONE undo step.

    The first ID survives; the second is removed. Mounted doors/windows retain
    their IDs, appearance and positions. Returns id, removed_ids, portal_ids,
    point_count. Supports automatic/manual wall runs and corners. Both walls
    must be on the current level with matching styles. Rejects loops, cave walls,
    T-junctions, overlaps and self-intersections before changing the map.
    Each input wall may contain up to 512 points. Undo restores both original
    walls and portal attachments; switch to their level before undo/redo.
    """
    if len(ids) != 2 or len(set(ids)) != 2:
        raise ValidationError("ids must contain exactly two distinct wall IDs")
    if any(isinstance(ident, bool) or not isinstance(ident, int) or ident < 0 for ident in ids):
        raise ValidationError("wall IDs must be nonnegative integers")
    return bridge.request("merge_walls", ids=list(ids))


@tool()
def draw_path(
    points: list[list[float]],
    asset: str,
    layer: int = 0,
    sorting: int = 0,
    smoothness: float | None = None,
    width: float | None = None,
    fade_in: bool = False,
    fade_out: bool = False,
    grow: bool = False,
    shrink: bool = False,
) -> dict:
    """Draw a path/road/river through a list of [x, y] woxel points. Returns the new element id.

    asset: a Paths asset path from list_assets(category='Paths').
    smoothness: optional curve smoothing. width: optional width scale multiplier.

    A wall-textured path looks like a wall but carries no line of sight into a
    VTT export. Where vision matters, run a real draw_wall along it too.

    End treatments, which are what make a path read as part of the world rather
    than a strip laid on top of it:

    fade_in / fade_out: the path's opacity fades at its start / end. Use where a
      trail should disappear into undergrowth or run off the map edge, instead
      of stopping at a hard rectangular cut.
    grow / shrink: the path's WIDTH tapers at its start / end. A stream that
      narrows upstream, a track that widens as it approaches a gate.

    Set these per path, here: changing the PathTool's own options beforehand
    does not affect what this draws.
    """
    require_points(points, minimum=2)
    require_choice(sorting, [0, 1], "sorting")
    params = {
        "points": points,
        "asset": asset,
        "layer": layer,
        "sorting": sorting,
        "fade_in": fade_in,
        "fade_out": fade_out,
        "grow": grow,
        "shrink": shrink,
    }
    if smoothness is not None:
        params["smoothness"] = smoothness
    if width is not None:
        params["width"] = width
    return bridge.request("draw_path", **params)


@tool()
def add_light(
    x: float | None = None,
    y: float | None = None,
    color: str = "",
    energy: float = 1.0,
    range: float = 1.0,
    shadows: bool = True,
    asset: str = "",
) -> dict:
    """Add a light at a woxel position. Returns the new element id.

    color: '#rrggbb' (default warm). energy: brightness. range: radius scale.
    asset: optional Lights gradient/cookie texture path.
    """
    require_hex_color(color, "color")
    require_finite(x, "x")
    require_finite(y, "y")
    require_finite(energy, "energy")
    require_finite(range, "range")
    params = {"color": color, "energy": energy, "range": range, "shadows": shadows, "asset": asset}
    if x is not None:
        params["x"] = x
    if y is not None:
        params["y"] = y
    return bridge.request("add_light", **params)


@tool()
def add_portal(
    asset: str,
    x: float | None = None,
    y: float | None = None,
    closed: bool = False,
    radius: float = 64.0,
    mount: str = "wall",
    snap_max: float = 256.0,
    flip: bool = False,
    fallback_free: bool = True,
    rotation: float = 0.0,
) -> dict:
    """Add a door/window portal at a woxel position. Returns the new element id.

    By default the portal MOUNTS on the nearest wall and the wall cuts a gap
    around it (like placing a door by hand).

    asset: a Portals asset path. closed: blocks light.
    radius: door half-width (~128 ≈ 1-tile door, ~256 ≈ 2-tile door).
    mount: 'wall' (snap to nearest wall, cut gap) or 'free' (freestanding).
    snap_max: max woxel distance a wall may be and still capture the portal.
    flip: reverse the door's facing. fallback_free: if mount='wall' but no wall
    is within snap_max, place a freestanding portal instead of erroring.
    rotation: degrees, freestanding only.
    """
    require_choice(mount, ["wall", "free"], "mount")
    params = {
        "asset": asset,
        "closed": closed,
        "radius": radius,
        "mount": mount,
        "snap_max": snap_max,
        "flip": flip,
        "fallback_free": fallback_free,
        "rotation": rotation,
    }
    if x is not None:
        params["x"] = x
    if y is not None:
        params["y"] = y
    return bridge.request("add_portal", **params)


@tool()
def add_roof(
    points: list[list[float]],
    asset: str,
    width: float = 256.0,
    type: int = 0,
    sorting: int = 0,
    sunlight: bool | None = None,
    sun_angle: float = 315.0,
    sun_contrast: float = 0.25,
) -> dict:
    """Add a roof from its RIDGE LINE. Returns the new element id.

    sunlight: shade the roof's faces from a sun direction. This is what makes a
      roof read as a solid volume rather than a flat patch of tiles, and it is
      worth setting on any exterior building.
    sun_angle: degrees the light comes FROM. Use ONE angle for every roof on a
      map — two buildings lit from different directions read as a mistake
      immediately.
    sun_contrast: 0 is flat, higher is starker.

    IMPORTANT: `points` is the roof's ridge (the peak line), NOT a footprint to
    trace. DD builds a complete, self-closing roof that slopes down `width`
    woxels perpendicular to each side of the ridge, with hips/gables off the
    ridge ends. The footprint covered = the ridge's bounding box expanded by
    `width` on every side.

    To roof a building W x H: put the ridge along the LONG axis, centered, and
    set width = half the SHORT dimension so the eaves reach the side walls. The
    ridge should be shorter than the long wall by ~width at each end (so the end
    hips land on the short walls). Two points that are close together give a
    near-pyramid (a square hip roof).

    asset: a Roofs asset path (list_assets('Roofs')). type: 0=gable, 1=hip,
    2=dormer. Roofs render above everything (z 800). Undoable as a create.
    """
    require_points(points, minimum=2)
    require_choice(type, [0, 1, 2], "type")
    require_choice(sorting, [0, 1], "sorting")
    return bridge.request(
        "add_roof",
        points=points,
        asset=asset,
        width=width,
        type=type,
        sorting=sorting,
        **(
            {"sunlight": sunlight, "sun_angle": sun_angle, "sun_contrast": sun_contrast}
            if sunlight is not None
            else {}
        ),
    )


@tool()
def place_pattern(
    asset: str,
    rect: list[float] | None = None,
    points: list[list[float]] | None = None,
    category: str = "Patterns",
    color: str = "",
    rotation: float | None = None,
    z: int = -100,
) -> dict:
    """Place a tiled floor/pattern shape (the Building Tool's "Floor" / Pattern Shape).

    Draws an actual tiled floor (wood planks, tile, brick, ...) that renders
    BELOW objects, distinct from terrain. Provide ONE of:
      rect: [x, y, w, h] axis-aligned rectangle, or
      points: [[x,y], ...] a polygon (>= 3 points), all in woxels.
    asset: a pattern asset path from list_assets(category=...).
    category: which asset bank — 'Patterns', 'Patterns Colorable', 'Materials',
      'Simple Tiles', or 'Smart Tiles'.
    color: '#rrggbb' tint. Omit to use the tileset's own default tint (wood is
      brown, etc.) instead of white — match the UI by leaving it unset.
    rotation: pattern rotation in degrees.
    z: persistent layer VALUE, a multiple of 100 from -500 to 900.
      Default -100 sits below objects. Arbitrary z offsets cannot survive saving.
    """
    if points is not None:
        require_points(points, minimum=3)
    if rect is not None:
        require_rect(rect)
    require_one_of(rect=rect, points=points)
    require_choice(z, list(range(-500, 901, 100)), "z")
    require_hex_color(color, "color")
    reject_smart_tiles(category)
    params: dict = {"asset": asset, "category": category, "z": z}
    if rect is not None:
        params["rect"] = rect
    if points is not None:
        params["points"] = points
    if color:
        params["color"] = color
    if rotation is not None:
        params["rotation"] = rotation
    return bridge.request("place_pattern", **params)


@tool()
def build_room(
    rect: list[float] | None = None,
    points: list[list[float]] | None = None,
    wall_asset: str = "",
    floor: str = "pattern",
    floor_asset: str = "",
    floor_category: str = "Simple Tiles",
    floor_color: str = "",
    floor_slot: int = 1,
    wall_type: int = 0,
    wall_joint: int = 1,
) -> dict:
    """Build a room in one call: a looped wall AND a matching floor on the SAME path.

    Because the wall and floor share the boundary, the floor meets the wall
    exactly (no gap) — like the UI's combined wall+floor trace. Provide ONE of:
      rect: [x, y, w, h] axis-aligned rectangle, or
      points: [[x,y], ...] a polygon (>= 3 points), all in woxels (the wall
      centerline; the wall covers the floor's outer edge).

    wall_asset: a Walls asset path (omit for the default).
    floor: 'pattern' (a tiled floor; floor_asset + floor_category), 'terrain'
      (paints terrain into floor_slot; floor_asset assigns the slot texture),
      or 'none' for walls only.
    floor_asset: the floor texture. floor_category: pattern bank for floor=
      'pattern' (e.g. 'Simple Tiles', 'Smart Tiles', 'Materials').
    floor_color: optional '#rrggbb' tint (pattern floors).
    wall_type: 0=auto, 1=manual, 2=cave. wall_joint: 0=sharp, 1=bevel, 2=round.

    Returns { wall_id, floor_id?, points }.
    """
    if points is not None:
        require_points(points, minimum=3)
    if rect is not None:
        require_rect(rect)
    require_choice(floor, ["pattern", "terrain", "none"], "floor")
    if floor == "pattern" and not floor_asset:
        raise ValidationError(
            "floor='pattern' needs a floor_asset — without one the walls are "
            "built and the floor is silently skipped. Pass one from "
            "list_assets(category=floor_category), or use floor='terrain'/'none'."
        )
    if floor == "pattern":
        reject_smart_tiles(floor_category, "floor_category")
    require_one_of(rect=rect, points=points)
    require_choice(wall_type, [0, 1, 2], "wall_type")
    require_choice(wall_joint, [0, 1, 2], "wall_joint")
    require_choice(floor, ["pattern", "terrain", "none"], "floor")
    require_hex_color(floor_color, "floor_color")
    params: dict = {
        "floor": floor,
        "floor_category": floor_category,
        "floor_slot": floor_slot,
        "wall_type": wall_type,
        "wall_joint": wall_joint,
    }
    if rect is not None:
        params["rect"] = rect
    if points is not None:
        params["points"] = points
    if wall_asset:
        params["wall_asset"] = wall_asset
    if floor_asset:
        params["floor_asset"] = floor_asset
    if floor_color:
        params["floor_color"] = floor_color
    return bridge.request("build_room", **params)


@tool()
def scatter_objects(
    assets: list[str],
    rect: list[float],
    count: int = 12,
    scale_min: float = 0.9,
    scale_max: float = 1.1,
    rotation_min: float = 0.0,
    rotation_max: float = 360.0,
    min_gap: float = 0.0,
    color: str = "",
    sorting: int = 0,
    layer: int = 100,
    seed: int | None = None,
) -> dict:
    """Scatter objects randomly over a rectangular area, with jittered scale and rotation.

    This is the tool to reach for when a space should look furnished or lived-in
    rather than placed-at-coordinates: foliage, rubble, crates, clutter, debris.
    Placing twenty objects individually reads as a grid; this does not.

    assets: one or more Objects asset paths from list_assets(category='Objects').
      Each placement picks one at random, so pass a few related assets for variety.
    rect: [x, y, w, h] in woxels. 256 woxels = 1 tile.
    count: how many to place (1-500).
    scale_min / scale_max: random scale range per object.
    rotation_min / rotation_max: random rotation range in degrees.
    min_gap: minimum woxel distance between placements. Use it to stop clumping;
      too large for the area and you get fewer than `count` (the response says so).
    color: optional '#rrggbb' applied to every placement, baked at placement
      and never changeable afterwards. Only colourable assets respond — see
      place_object.
    seed: fixes the arrangement so a run is reproducible. Pass one when you want
      to adjust a single parameter and compare, rather than reshuffling everything.
    layer: layer VALUE for every placement (multiple of 100, -500..900). Same
      meaning as in place_object; 100 is the default.

    Returns the ids placed, how many attempts it took, and a note if it could not
    fit the requested count.
    """
    require_rect(rect)
    if not assets:
        raise ValidationError("assets must not be empty")
    if len(rect) != 4:
        raise ValidationError("rect must be [x, y, w, h]")
    require_positive(scale_min, "scale_min")
    require_positive(scale_max, "scale_max")
    if scale_max < scale_min:
        raise ValidationError("scale_max must be >= scale_min")
    if rotation_max < rotation_min:
        raise ValidationError("rotation_max must be >= rotation_min")
    if not 1 <= count <= 500:
        raise ValidationError("count must be between 1 and 500")
    require_hex_color(color, "color")
    require_choice(sorting, [0, 1], "sorting")
    require_choice(layer, list(range(-500, 1000, 100)), "layer")
    params: dict = {
        "assets": assets,
        "rect": rect,
        "count": count,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "rotation_min": rotation_min,
        "rotation_max": rotation_max,
        "min_gap": min_gap,
        "sorting": sorting,
        "layer": layer,
    }
    if color:
        params["color"] = color
    if seed is not None:
        params["seed"] = seed
    return bridge.request("scatter_objects", **params)


@tool()
def add_text(
    text: str,
    x: float | None = None,
    y: float | None = None,
    size: int | None = None,
    color: str = "",
    font: str = "",
) -> dict:
    """Add a text label at a woxel position. Returns the new element id and size.

    size: font size in points (default ~32). color: '#rrggbb' (default black).
    font: a DD font name; omit to keep the default font.
    """
    require_hex_color(color, "color")
    params: dict = {"text": text}
    if x is not None:
        params["x"] = x
    if y is not None:
        params["y"] = y
    if size is not None:
        params["size"] = size
    if color:
        params["color"] = color
    if font:
        params["font"] = font
    return bridge.request("add_text", **params)


# --------------------------------------------------------------------------
# Terrain
# --------------------------------------------------------------------------


@tool()
def generator_options(name: str = "", value: float | None = None) -> dict:
    """Read or set the Map Wizard's generator dials.

    Call with no arguments to list them: each dial's current value, min, max and
    step, plus which design is selected. Only dials the current design actually
    shows are listed — a cave has Boundary, Complexity and Density; a dungeon
    adds the Floor and Wall pickers — so list them AFTER choosing the design.

    name + value sets a "number" dial — Boundary, Complexity and Density —
    to a value inside its min..max. The response reports what it became.

    "list" dials (Floor and Wall) are reported here but set through
    generate_dungeon's floor= and wall= arguments, not here. Enabling the
    generator resets the wizard's pickers, so a selection made beforehand is
    discarded.

    Effects, strongest first: Complexity and Density transform a cave; on a
    dungeon both raise room and corridor count substantially; Boundary trades
    map coverage for compactness.

    Set these before generate_dungeon; they are the difference between a
    sprawling open cavern and a tight warren.
    """
    params: dict = {}
    if name:
        params["name"] = name
        if value is None:
            raise ValidationError("value is required when setting a dial")
        params["value"] = value
    return bridge.request("generator_options", **params)


@tool()
def generate_dungeon(design: str = "", floor: int | None = None, wall: int | None = None) -> dict:
    """Run Dungeondraft's own procedural generator: a whole layout in one call.

    design: "Dungeon" for rooms and corridors, "Cave" for organic caverns.
      Omit to use whatever the app's Map Wizard currently has selected.
    floor / wall: texture indices from generator_options. They must be passed
      HERE rather than set beforehand — enabling the generator resets the
      wizard's pickers, so a choice made earlier is discarded. Set the numeric
      dials with generator_options first; those do survive.

    The response reports the design actually generated, read back from the
    wizard — not the one requested.

    This REPLACES the level's layout, so run it FIRST, on an empty map, after
    set_map_size and before placing anything by hand. Re-generating works, but
    Dungeondraft's own UI does not offer it: treat it as a do-over on an
    undecorated map, not a way to iterate on work.

    It gives structure, not a finished map. Character comes from scatter,
    shadow paths along the walls, floor shapes and terrain.
    """
    if design and design not in ("Dungeon", "Cave"):
        raise ValidationError("design must be 'Dungeon' or 'Cave'")
    params: dict = {"design": design} if design else {}
    if floor is not None:
        params["floor"] = floor
    if wall is not None:
        params["wall"] = wall
    result = bridge.request("generate_dungeon", **params)

    # The generator finalises walls asynchronously: counts read immediately
    # after it returns catch it mid-settle (30 walls one moment, 3 the next).
    # Wait, then report what the map actually ended up with, so the caller is
    # not handed a number that is about to change under them.
    time.sleep(SETTLE_SECONDS)
    status = bridge.request("get_status")
    result["after"] = status["counts"]
    result["layers"] = status["layers"]
    return result


@tool()
def add_floor(
    rect: list[float] | None = None,
    points: list[list[float]] | None = None,
    invert: bool = False,
    smart_tile_id: int | None = None,
    wall_asset: str = "",
    wall_color: str = "",
    bevel: bool | None = None,
) -> dict:
    """Draw a solid floor shape — the bordered room floors a built map is made of.

    rect: [x, y, w, h] in woxels, or points: [[x,y], ...] for any outline.
    invert: cut a hole in the floor instead of adding to it.

    This is a different system from terrain and from patterns. Terrain is the
    painted ground beneath everything; a pattern is a tiled surface; a floor
    shape is a solid slab with an outlined edge, which is what makes a room read
    as a built interior rather than a patch of ground. Reach for it when walling
    a room, and paint terrain outside it.

    Like terrain and water it is a layer, not an object: there is nothing to
    select or delete, so use invert to take one back.

    A native floor is not a pattern: it carries its own border WALL and can use
    Dungeondraft's smart tiles. Unset options keep whatever the tool holds.

    smart_tile_id: which floor style. Read the options from
      list_tool_controls('FloorShapeTool') — they are ids, not names.
    wall_asset: the Walls asset used for this floor's own border wall.
    wall_color: hex tint for that border wall.
    bevel: bevel the border wall's corners.
    """
    if points is not None:
        require_points(points, minimum=3)
    if rect is not None:
        require_rect(rect)
    require_one_of(rect=rect, points=points)
    params: dict = {"invert": invert}
    if rect is not None:
        if len(rect) != 4:
            raise ValidationError("rect must be [x, y, w, h]")
        params["rect"] = rect
    else:
        params["points"] = points
    if smart_tile_id is not None:
        params["smart_tile_id"] = smart_tile_id
    if wall_asset:
        params["wall_asset"] = wall_asset
    if wall_color:
        params["wall_color"] = wall_color
    if bevel is not None:
        params["bevel"] = bevel
    return bridge.request("add_floor", **params)


@tool()
def set_verbose(on: bool = True) -> dict:
    """Turn per-command log bracketing on or off inside Dungeondraft.

    When on, the mod writes `>>> cmd {args}` before each command and
    `<<< cmd ok|ERR ...` after. Godot writes engine errors to the same log with
    no indication of what provoked them, so this is what lets an error line be
    attributed to the command that caused it. Use it when auditing or
    debugging; leave it off otherwise.
    """
    return bridge.request("set_verbose", on=on)


@tool()
def log_marker(text: str) -> dict:
    """Write a line into Dungeondraft's log to separate phases of a test run.

    Pairs with set_verbose: mark a phase, run some commands, then read the log
    between markers to see exactly what the engine reported for that phase.
    """
    return bridge.request("log_marker", text=text)


@tool()
def paint_material(
    points: list[list[float]],
    asset: str,
    size: int = 2,
    layer: int = -400,
    smooth: bool = True,
    erase: bool = False,
) -> dict:
    """Paint a MATERIAL patch along a brush stroke. Returns what it painted.

    Materials are their own system — irregular patches of stone, earth, lava or
    moss with their own borders — and they are not terrain and not patterns.
    A Materials asset passed to place_pattern makes a PATTERN, not a material.

    Choose between them deliberately:
      terrain   ground that must BLEND into neighbouring ground
      pattern   a tiled floor inside a building
      material  a sculpted patch with its own edge, sitting on top of ground
      water     actual water

    points: the stroke, in woxels. One point is a single dab.
    asset: a Materials path from list_assets(category='Materials').
    size: brush radius in mesh CELLS, 1-20. A cell is typically one tile, so
      size 6 paints roughly twelve tiles across PER DAB. Start at 1-2 and look.
    layer: which material layer to paint into. Materials on different layers
      stack rather than merge.
    smooth: smooth the patch's edge, versus following the material's own
      texture.
    erase: remove this material along the stroke instead of adding it.

    The response reports `cell_size_woxels` and `covered_woxels` so the brush
    size can be reasoned about on the ground. There is no "did it land" flag,
    because the engine offers no reliable one: verify a stroke by looking at it.
    """
    require_points(points, minimum=1)
    if size < 1 or size > 20:
        raise ValidationError(f"size must be between 1 and 20 cells, got {size}")
    require_choice(layer, list(range(-500, 1000, 100)), "layer")
    return bridge.request(
        "paint_material",
        points=points,
        asset=asset,
        size=size,
        layer=layer,
        smooth=smooth,
        erase=erase,
    )


@tool()
def set_trace_image(
    path: str = "",
    scale: float | None = None,
    opacity: float | None = None,
    center: bool = False,
    clear: bool = False,
) -> dict:
    """Put a reference image under the map to trace over. Returns what applied.

    For reconstructing an approved sketch, a published floor plan, or a
    hand-drawn dungeon. Load it, size it against the grid, drop its opacity so
    your own work reads over it, then build on top — and hide it before the
    final render, because it is a guide, not part of the map.

    path: an ABSOLUTE path to an image on the machine running Dungeondraft.
    scale: size multiplier. Set it so a known distance on the image matches the
      grid; guessing here is what makes a traced plan come out the wrong size.
    opacity: 0 invisible, 1 opaque. Around 0.3-0.5 is usually enough to follow
      without drowning what you are drawing.
    center: centre the image on the map.
    clear: remove the trace image.

    It is per-EDITOR state, not part of the map, so it does not save with the
    map and other people will not see it.
    """
    if opacity is not None and not 0.0 <= opacity <= 1.0:
        raise ValidationError(f"opacity must be between 0 and 1, got {opacity}")
    if scale is not None:
        require_positive(scale, "scale")
    params: dict = {}
    if path:
        params["path"] = path
    if scale is not None:
        params["scale"] = scale
    if opacity is not None:
        params["opacity"] = opacity
    if center:
        params["center"] = True
    if clear:
        params["clear"] = True
    if not params:
        raise ValidationError("give at least one of path, scale, opacity, center or clear")
    return bridge.request("set_trace_image", **params)


@tool()
def get_map_style() -> dict:
    """Read map-wide building wear and grid style from the world's actual textures.

    Returns canonical names, texture paths, and available choices. A custom
    texture with no built-in name is reported as null with its path retained.
    Grid style chooses the line pattern; it does not toggle grid visibility.
    """
    return bridge.request("get_map_style")


@tool()
def set_map_style(building_wear: str | None = None, grid_style: str | None = None) -> dict:
    """Set optional finishing effects across the map, as one undoable edit.

    building_wear: none, dust, grime, noise, scratched. Applies to building
      floors/walls across every level; use only when that global effect fits.
    grid_style: dashes, dotted, narrow_line, thick_line. Changes the grid's
      line pattern, not whether the grid is visible or included in an export.

    Omitted fields keep their current values. Both fields are validated before
    editing, and the response reads actual world textures. Use get_map_style
    before changing a map and inspect a screenshot/export afterwards. Undo and
    redo restore both values together, even after switching levels.
    """
    params: dict = {}
    if building_wear is not None:
        require_choice(
            building_wear, ["none", "dust", "grime", "noise", "scratched"], "building_wear"
        )
        params["building_wear"] = building_wear
    if grid_style is not None:
        require_choice(grid_style, ["dashes", "dotted", "narrow_line", "thick_line"], "grid_style")
        params["grid_style"] = grid_style
    if not params:
        raise ValidationError("give at least one of building_wear or grid_style")
    return bridge.request("set_map_style", **params)


@tool()
def set_water_style(
    deep_color: str = "",
    shallow_color: str = "",
    blend_distance: float | None = None,
    border: bool | None = None,
) -> dict:
    """Style this level's water: what KIND of water it is. Returns the result.

    Geometry first (add_water), then this. A muddy river, a clear shallow, a
    peat swamp and a deep cold pool are the same mesh with different colour.

    Per LEVEL, not per water body: every pool on this level shares it. The
    response reads the values back off the mesh rather than echoing the request.
    """
    require_hex_color(deep_color, "deep_color")
    require_hex_color(shallow_color, "shallow_color")
    if blend_distance is not None:
        require_finite(blend_distance, "blend_distance")
        if blend_distance < 0:
            raise ValidationError("blend_distance cannot be negative")
    params: dict = {}
    if deep_color:
        params["deep_color"] = deep_color
    if shallow_color:
        params["shallow_color"] = shallow_color
    if blend_distance is not None:
        params["blend_distance"] = blend_distance
    if border is not None:
        params["border"] = border
    if not params:
        raise ValidationError(
            "give at least one of deep_color, shallow_color, blend_distance or border"
        )
    return bridge.request("set_water_style", **params)


@tool()
def set_terrain_blending(enabled: bool) -> dict:
    """Choose how terrain slots blend into one another on this level.

    enabled: True for smooth blending (slots fade into each other), False for
      textured (the blend follows the material's own texture, giving a grainier,
      more natural seam).

    This is a per-level setting that affects every terrain edge already painted,
    not just the next one, so choose it before painting rather than after.

    get_terrain reports the current value as `smooth_blending`.
    """
    return bridge.request("set_terrain_blending", enabled=bool(enabled))


@tool()
def get_terrain(rect: list[float] | None = None, samples: int = 16) -> dict:
    """Read the terrain back: sample the painted terrain on a grid.

    rect: [x, y, w, h] in woxels; omit for the whole map.
    samples: grid resolution per side, 2-64 (16 = 256 points).

    Returns a `weights` grid, row-major from the rect's top-left. Each point is
    [slot0, slot1, slot2, slot3], read directly from the splat image's RGBA
    channels and summing to ~1, and `slots`: the texture each of those four
    slots holds.

    Slot 0 is the BASE: whatever slots 1-3 leave unclaimed shows slot 0's
    texture. So [1, 0, 0, 0] means "all slot 0" — and what that looks like
    depends entirely on `slots[0]`. On a new map every slot holds limestone, so
    it is ground nobody chose; after fill_terrain(asset=grass) it is grass. The
    weights cannot tell those apart, which is why `slots` is reported.
    paint_terrain(slot=0) is accepted by the engine but never raises slot 0's
    weight; fill_terrain(slot=0) replaces the base instead.

    Slots 4-7 exist in a second splat image and are NOT reported here.

    This is the only way to check terrain without a screenshot — use it to
    confirm a fill or paint landed where you meant, and to see what ground you
    inherited on a map you did not build.
    """
    if rect is not None:
        require_rect(rect)
    params: dict = {"samples": samples}
    if rect is not None:
        if len(rect) != 4:
            raise ValidationError("rect must be [x, y, w, h]")
        params["rect"] = rect
    return bridge.request("get_terrain", **params)


@tool()
def set_terrain_slot(asset: str, slot: int = 0) -> dict:
    """Assign a Terrain asset to a terrain slot index so it can be filled/painted with that slot."""
    require_choice(slot, list(range(8)), "slot")
    return bridge.request("set_terrain_slot", asset=asset, slot=slot)


@tool()
def fill_terrain(slot: int = 0, asset: str = "") -> dict:
    """Flood-fill the whole current level with a terrain slot.

    If asset is given, it is assigned to the slot first.

    The usual first ground call is fill_terrain(asset=<base material>) on the
    default slot 0: that replaces the base under everything and leaves slots
    1-3 free for roads, yards and worn edges painted on top with fill_region.
    """
    require_choice(slot, list(range(8)), "slot")
    params: dict = {"slot": slot}
    if asset:
        params["asset"] = asset
    return bridge.request("fill_terrain", **params)


@tool()
def fill_region(
    rect: list[float] | None = None,
    points: list[list[float]] | None = None,
    slot: int = 0,
    asset: str = "",
    rate: float = 1.0,
) -> dict:
    """Fill only a region with a terrain slot (e.g. floor a single room), in woxel coords.

    Unlike fill_terrain (whole level), this paints inside a shape. Provide ONE of:
      rect: [x, y, w, h] axis-aligned rectangle, or
      points: [[x,y], ...] a polygon (>= 3 points).
    asset: optional Terrain asset to assign to the slot first.
    rate: paint strength 0..1 (1 = fully replace). Undoable via undo().
    """
    if points is not None:
        require_points(points, minimum=3)
    if rect is not None:
        require_rect(rect)
    require_choice(slot, list(range(8)), "slot")
    require_one_of(rect=rect, points=points)
    params: dict = {"slot": slot, "rate": rate}
    if rect is not None:
        params["rect"] = rect
    if points is not None:
        params["points"] = points
    if asset:
        params["asset"] = asset
    return bridge.request("fill_region", **params)


@tool()
def paint_terrain(
    slot: int = 0,
    x: float | None = None,
    y: float | None = None,
    radius: float = 64.0,
    rate: float = 1.0,
    asset: str = "",
) -> dict:
    """Paint a soft circular terrain brush of a slot at a woxel position.

    radius: brush radius in woxels. rate: peak strength 0..1 at the center, with
    a smooth falloff to the rim so strokes blend. asset: optional Terrain asset
    to assign to the slot first (else set it with set_terrain_slot). Undoable.
    For a hard-edged region instead of a brush, use fill_region.
    """
    require_choice(slot, list(range(8)), "slot")
    params: dict = {"slot": slot, "radius": radius, "rate": rate}
    if x is not None:
        params["x"] = x
    if y is not None:
        params["y"] = y
    if asset:
        params["asset"] = asset
    return bridge.request("paint_terrain", **params)


@tool()
def paint_path(
    points: list[list[float]],
    slot: int = 0,
    radius: float = 96.0,
    rate: float = 1.0,
    asset: str = "",
) -> dict:
    """Paint a continuous terrain stroke (a road/trail) along a polyline in one call.

    asset is a TERRAIN asset, not a Paths one — this paints ground, it does not
    lay a Paths element. Use draw_path for that.

    points: a list of [x, y] woxel corners the path runs through (>= 2). The
    bridge rasterizes a uniform ribbon of constant width by measuring each
    pixel's distance to the nearest segment, so the route comes out smooth with
    clean edges — no gaps or double-painted overlaps. Prefer this over stamping
    many paint_terrain dabs for any line/road.

    radius: half-width of the stroke in woxels. rate: peak strength 0..1 with a
    soft falloff to the edges so it blends. asset: optional Terrain asset to
    assign to the slot first (else set it with set_terrain_slot). Undoable.
    """
    require_points(points, minimum=2)
    require_choice(slot, list(range(8)), "slot")
    params = {"points": points, "slot": slot, "radius": radius, "rate": rate}
    if asset:
        params["asset"] = asset
    return bridge.request("paint_path", **params)


@tool()
def get_cave() -> dict:
    """Read the selected level's cave floor/entrance cell counts and actual colours.

    Entrances are a separate blast mask that removes rocky borders; they do not
    carve floor. Counts describe bitmap cells, not distinct rooms or openings.
    """
    return bridge.request("get_cave")


@tool()
def set_cave_entrance(x: float, y: float, radius: float = 256.0, open: bool = True) -> dict:
    """Open or restore a circular section of cave border, as one undoable edit.

    Place the centre at an existing cave edge in woxels. radius is the half-width
    (0 < radius <= 2048), rounded to cave cells. open=False removes the blast
    mask, restoring the border; neither mode digs or fills cave floor. Dig the
    approach first with dig_cave, then inspect a screenshot of the mouth.
    The edit belongs to the selected level. Undo requires that same level and
    unchanged bitmap dimensions. Returns the actual number of changed cells.
    """
    require_finite(x, "x")
    require_finite(y, "y")
    require_positive(radius, "radius")
    if radius > 2048:
        raise ValidationError("radius must be at most 2048 woxels")
    return bridge.request("set_cave_entrance", x=x, y=y, radius=radius, open=open)


@tool()
def dig_cave(
    points: list[list[float]],
    radius: float = 256.0,
    dig: bool = True,
    ground_color: str = "",
    wall_color: str = "",
    texture: str = "",
) -> dict:
    """Carve a cave along a path with the Cave Brush (the dig/blast tool).

    Dungeondraft caves are a separate layer: you dig open floor out of solid
    rock, and DD auto-generates the rocky wall border + debris around the opening.

    points: a list of [x, y] woxel points the cave runs through (>= 1). A single
    point digs one circular chamber; multiple points dig a connected tunnel
    (rasterized as a constant-width ribbon, like paint_path). radius: half-width
    in woxels (default 256 = ~1 tile). dig: True carves open cave; False fills it
    back to rock. ground_color / wall_color: optional cave floor/wall tints
    ("#rrggbb" or [r,g,b]). texture: optional Caves floor asset (see
    list_assets(category="Caves")). The mesh rebuilds automatically.
    """
    # One point is a single circular chamber — documented three lines above,
    # implemented in the mod, and broken by requiring two.
    require_points(points, minimum=1)
    require_hex_color(ground_color, "ground_color")
    require_hex_color(wall_color, "wall_color")
    params = {"points": points, "radius": radius, "dig": dig}
    if ground_color:
        params["ground_color"] = ground_color
    if wall_color:
        params["wall_color"] = wall_color
    if texture:
        params["texture"] = texture
    return bridge.request("dig_cave", **params)


@tool()
def add_water(
    rect: list[float] | None = None,
    points: list[list[float]] | None = None,
    invert: bool = False,
) -> dict:
    """Add a body of water — a pond, pool, river bend, moat, or flooded room.

    rect: [x, y, w, h] in woxels, or points: [[x,y], ...] for a shoreline.
    invert: erase water inside the outline instead of adding it. Water is a
      layer, not an object — there is nothing to select and delete — so this is
      how you take a pond back or cut an island out of one.

    Water is a polygon layer, not a brush stroke: you give it a closed outline
    and the whole enclosed area becomes water. Give exactly one of:

    rect: [x, y, w, h] in woxels, for a rectangular pool.
    points: [[x, y], ...] with at least 3 points, for an irregular shape — a
      pond, a river bend, a cave lake. The outline closes automatically.

    Call it repeatedly to build up several separate bodies of water.
    """
    if points is not None:
        require_points(points, minimum=3)
    if rect is not None:
        require_rect(rect)
    require_one_of(rect=rect, points=points)
    params: dict = {"invert": invert}
    if rect is not None:
        if len(rect) != 4:
            raise ValidationError("rect must be [x, y, w, h]")
        params["rect"] = rect
    if points is not None:
        if len(points) < 3:
            raise ValidationError("points needs at least 3 [x, y] pairs to enclose an area")
        params["points"] = points
    return bridge.request("add_water", **params)


@tool()
def set_ambient_light(color: str) -> dict:
    """Set the map's ambient light colour — the single biggest lever on mood.

    A cold blue-grey reads as night or a dungeon; warm amber reads as lamplight
    or dusk; a neutral grey lets the placed sources carry the colour. A fresh
    map's white is flat glare rather than daylight, so decide rather than leave
    it. Whatever you pick, look at a render afterwards: the mood is yours, but
    every zone that hosts play has to read at the table. This is map-wide, not
    a placed light source (use add_light for those).

    It is also functional, not just cosmetic: Universal VTT exports carry
    lighting into Foundry and similar tools, so this affects the map at its
    destination.

        color: '#rrggbb'.
    """
    require_hex_color(color, "color")
    if not color:
        raise ValidationError("color is required")
    return bridge.request("set_ambient_light", color=color)


@tool()
def list_prefabs(set: str = "") -> dict:
    """List Dungeondraft's pre-composed prefabs — furnished groups, ready to place.

    Prefabs are whole assemblies rather than single objects: a market stall, a
    set of tavern tables, a stack of crates, a well. Placing one is usually far
    better than composing the same thing from a dozen `place_object` calls, and
    it looks composed because a human composed it.

    Returns the available `sets`, the `current_set`, and the `prefabs` in it.

    set: switch to this set before listing (see `sets` in the response).
    """
    params = {"set": set} if set else {}
    return bridge.request("list_prefabs", **params)


@tool()
def place_prefab(
    name: str,
    set: str = "",
    x: float | None = None,
    y: float | None = None,
    rotation: float = 0.0,
) -> dict:
    """Place one of Dungeondraft's pre-composed prefabs by name.

    Call list_prefabs first to see what exists — names must match exactly.

    Reach for this before hand-composing a common furnished unit. A tavern's
    tables, a market stall, a smithing setup or a well already exist as prefabs
    and will look better assembled than placed piece by piece.

    ALWAYS pass x and y. A prefab otherwise lands wherever its author saved it,
    usually near the map's top-left corner. With x and y the prefab's centre
    lands there, and `placement` in the response reports what moved. If it
    still lands wrong, undo() removes the whole prefab in one step while it is
    the latest operation.

    name: exact prefab name from list_prefabs.
    set: optionally switch set first.
    x, y: woxel point to centre the prefab on. Pass both or neither.
    rotation: degrees to turn the whole prefab about its centre.

    Placement transforms walls with their mounted portals, paths, roofs,
    patterns, objects, lights, freestanding portals, and text anchors (labels
    stay upright). Cave-generated walls and unsupported elements are listed
    in placement.skipped with reasons in placement.unsupported. Inspect those
    and the footprint before repeating. To shift or rotate the group afterwards,
    use move_elements with the returned ids — one call, one undo step.
    """
    if not name:
        raise ValidationError("name is required; call list_prefabs first")
    if (x is None) != (y is None):
        raise ValidationError("pass both x and y, or neither")
    params: dict = {"name": name}
    if set:
        params["set"] = set
    if x is not None and y is not None:
        params["x"] = x
        params["y"] = y
    if rotation:
        params["rotation"] = rotation
    return bridge.request("place_prefab", **params)


@tool()
def list_tool_controls(tool: str) -> dict:
    """List a Dungeondraft tool's UI controls — its real, operable surface.

    Every tool exposes its buttons, dropdowns, toggles and colour pickers as
    named controls. This shows their ids and types, which is what `tool_action`
    and `set_tool_option` operate on.

    tool: e.g. 'SelectTool', 'PrefabTool', 'FloorShapeTool', 'MaterialBrush',
      'MapSettings', 'Environment', 'LightTool', 'TraceImage'.
    """
    if not tool:
        raise ValidationError("tool is required")
    return bridge.request("list_tool_controls", tool=tool)


@tool()
def tool_action(tool: str, control: str) -> dict:
    """Press a button control on a Dungeondraft tool.

    This is the escape hatch for capabilities with no dedicated tool. Notably
    SelectTool's batch operations, which act on the current selection (use
    select_elements first): 'Copy', 'Paste', 'Mirror', 'Lock', 'Separate',
    'Merge Walls', 'Make Prefab', 'Delete'.

    Prefer a purpose-built tool where one exists — they validate input and
    return ids. Call list_tool_controls to see what a tool offers.

    Buttons that need a selection will report being disabled rather than
    silently doing nothing.

    Merge Walls can join compatible manual walls (draw_wall type=1). Walls
    with mounted doors/windows are refused because native merging deletes
    portals on absorbed walls. Generic actions do not enter bridge undo history.
    """
    if not tool or not control:
        raise ValidationError("tool and control are both required")
    return bridge.request("tool_action", tool=tool, control=control)


@tool()
def set_tool_option(
    tool: str,
    control: str,
    item: str = "",
    color: str = "",
    pressed: bool | None = None,
    value: float | None = None,
    item_index: int | None = None,
    item_metadata: str = "",
) -> dict:
    """Set a value on a Dungeondraft tool's control.

    Pass exactly one of:
      item          text of an entry in an OptionButton or ItemList, by its
                    visible name
      item_index    that entry's POSITION instead. Texture selectors and
                    FloorShapeTool's SmartTileId have blank labels, so they
                    cannot be named by text at all
      item_metadata substring of an entry's metadata. A texture menu item holds
                    its ASSET PATH there, so this picks a texture by path —
                    which is usually what you actually mean
      color         '#rrggbb' for a colour picker. Some colour controls wrap the
                    picker in a container; this reaches through it
      pressed       true/false for a toggle, e.g. 'Bevel', 'Shadow'
      value         a number for a slider

    Call list_tool_controls first — control ids and types vary per tool, and the
    value kind must match the control.

    This is the DIAGNOSTIC surface, for controls with no typed tool of their
    own. Where a typed tool exists, use it: it validates, reads its result back
    and is undoable, none of which this is.
    """
    given = [
        x for x in (item, color, pressed, value, item_index, item_metadata) if x not in ("", None)
    ]
    if len(given) != 1:
        raise ValidationError(
            "pass exactly one of item, item_index, item_metadata, color, pressed or value"
        )
    if color:
        require_hex_color(color, "color")
    params: dict = {"tool": tool, "control": control}
    if item:
        params["item"] = item
    if color:
        params["color"] = color
    if pressed is not None:
        params["pressed"] = pressed
    if value is not None:
        params["value"] = value
    if item_index is not None:
        params["item_index"] = item_index
    if item_metadata:
        params["item_metadata"] = item_metadata
    return bridge.request("set_tool_option", **params)


@tool()
def save_map(filename: str = "", overwrite: bool = False, wait: bool = True) -> dict:
    """Save the map. Use this often — it is how work survives a crash.

    filename: a bare name (".dungeondraft_map" is added if missing), written
      into the configured save directory — see get_save_directory. Omit it to
      save over the map already open.

    The map you have open can always be overwritten; that is the point, and it
    is how you check in progress as you go. A file that EXISTS and is not your
    open map is refused, so a plausible-sounding name cannot destroy someone
    else's map. Pass overwrite=True only when the user has actually asked to
    replace that file.

    A map that has never been saved has no path, so saving it needs a filename:
    without one Dungeondraft opens a modal Save As dialog, and a modal freezes
    this bridge until a human closes it.

    Writing is asynchronous, so by default this waits until Dungeondraft
    reports it finished writing THIS path and returns `completed: true`. While
    a save is in flight Dungeondraft DROPS edits from the file, so the bridge
    refuses to change the map until it lands.

    `completed: false` means the save did not confirm in time. It is probably
    still running: read `note`, poll get_status, and do NOT call save_map
    again — a second write of the same file is the one thing that cannot help.

    wait=False returns as soon as the save starts, for a caller that tracks
    `saving.in_flight` itself.

    If Dungeondraft does not start a save at all, this raises instead of
    replying. Read the message, because the two causes need opposite action:
    busy (retry in a few seconds), or wedged after a save crashed inside
    Dungeondraft — then nothing can be written this session, a restart is the
    only way out and it loses unsaved work, so stop building and tell the user.
    Any edit made while a save is unfinished also carries a `save_warning`.
    """
    params: dict = {"overwrite": overwrite}
    if filename:
        name = require_bare_filename(filename)
        if not name.lower().endswith(".dungeondraft_map"):
            require_bare_filename(f"{name}.dungeondraft_map")
        params["filename"] = name
    # Read the counter BEFORE saving: an autosave firing during the wait also
    # raises saves_seen, so the number this save has to beat is the one that
    # was true when it started.
    saves_before = -1
    if wait:
        saves_before = int((bridge.request("get_status").get("saving") or {}).get("saves_seen", 0))
    started = bridge.request("save_map", **params)
    if not wait or started.get("started") is False:
        return started
    settled = _wait_for_save(
        expected_path=str(started.get("path") or ""),
        saves_before=saves_before,
        strict=False,
    )
    return {**started, **settled, "in_flight": bool(settled.get("in_flight"))}


@tool()
def get_save_directory() -> dict:
    """Where save_map writes, and whether that directory exists.

    `configured` is the user's setting (may be empty); `effective` is what will
    actually be used, and `exists` describes THAT one. With no setting, it is a
    `battlemap-mcp` folder inside Dungeondraft's own map directory — created
    on demand, so this works with no setup and keeps generated maps separate
    from hand-made ones.

    `configured_missing` means the setting points at a directory that is gone.
    Saving falls back to the default rather than failing, and `note` says so;
    clear the setting with set_save_directory("") or point it somewhere real.
    """
    return bridge.request("get_save_directory")


@tool()
def set_save_directory(path: str) -> dict:
    """Set the directory save_map writes into. Pass "" to clear it.

    Persisted per install, so it survives restarts — a directory inside a
    temporary folder keeps being the answer long after the folder is gone.
    The directory must already exist; this will not create one. If it
    disappears later, saving falls back to Dungeondraft's own map directory
    and both get_save_directory and the save reply say so.
    """
    return bridge.request("set_save_directory", path=path)


@tool()
def open_map(path: str, wait: bool = True) -> dict:
    """Open a .dungeondraft_map file, replacing whatever is currently open.

    Any unsaved work in the current map is lost — call save_map first if it
    matters.

    Loading is asynchronous AND it restarts the bridge: mods load after the map
    does, so the bridge briefly stops answering and can come back on another
    port. By default this waits until the map Dungeondraft reports open is the
    one you asked for, and returns its size and level.

    `opened: false` means that had not happened in time. The load may still be
    running: read `note` and poll get_status rather than opening again.

    wait=False returns as soon as the command is accepted.

    path: absolute path to a .dungeondraft_map file.
    """
    if not path:
        raise ValidationError("path is required")
    before = _status_before_open() if wait else {}
    accepted = bridge.request("open_map", path=path)
    if not wait:
        return accepted
    return {**accepted, **_wait_for_map(path, previous=before)}


def _status_before_open() -> dict:
    """The bridge answering now, so the wait can tell its replacement apart."""
    try:
        return bridge.request("get_status")
    except BridgeUnavailableError:
        return {}


def _is_fresh_instance(status: dict, previous: dict) -> bool:
    """Did this reading come from the bridge that the new map started?

    Every map load starts a new bridge instance, and for a moment the old one
    still answers with the NEW map_file but the OLD map's counts and size —
    twice measured building UAT fixtures (2026-09-20): a blank map reported
    `walls: 7`, and later 50 objects and 9 portals, while get_status a moment
    later showed zeros. So the file path cannot settle it. The instance can.
    """
    was, now = previous.get("bridge_instance"), status.get("bridge_instance")
    if was is not None and now is not None:
        return now != was
    # A bridge too old to report its instance: a freshly loaded one has made no
    # edits, so a reading that carries history belongs to the one being replaced.
    return not (status.get("undo_depth") or status.get("redo_depth"))


def _same_map_file(reported: str, requested: str) -> bool:
    """Is the open map the file that was asked for?

    `map_open: true` on its own still describes the PREVIOUS map for as long as
    the new one is loading, so identity is what settles it. Compared as resolved
    paths, falling back to the file name when a path cannot be resolved (the two
    sides are the same machine, but not necessarily the same spelling of it).
    """
    if not reported:
        return False
    try:
        return Path(reported).resolve() == Path(requested).resolve()
    except OSError:
        return Path(reported).name == Path(requested).name


def _wait_for_map(path: str, timeout: float = 60.0, previous: dict | None = None) -> dict:
    """Block until the requested map is open in a NEW bridge instance.

    Tolerates the reconnect. `previous` is the status read before the open was
    sent; see _is_fresh_instance for why the path alone is not enough.
    """
    previous = previous or {}
    deadline = time.time() + timeout
    status: dict = {}
    unreachable: str = ""
    while time.time() < deadline:
        try:
            status = bridge.request("get_status")
        except BridgeUnavailableError as exc:
            # Expected: the bridge goes away with the old map and comes back
            # with the new one, possibly on another port. BridgeClient
            # re-resolves the port on a connect failure.
            unreachable = str(exc)
        else:
            unreachable = ""
            if (
                status.get("map_open")
                and _same_map_file(map_file_path(status), path)
                and _is_fresh_instance(status, previous)
            ):
                return {
                    "opened": True,
                    "map_file": map_file_path(status),
                    "map_size_woxels": status.get("map_size_woxels"),
                    "map_center": status.get("map_center"),
                    "level_id": status.get("level_id"),
                    "counts": status.get("counts"),
                }
        time.sleep(0.5)
    return {
        "opened": False,
        "map_file": map_file_path(status),
        "note": (
            f"{path} was not the open map after {timeout:.0f}s"
            + (f"; the bridge was unreachable ({unreachable})" if unreachable else "")
            + ". Dungeondraft may still be loading it, or may have refused the file. "
            "Poll get_status rather than opening it again, and check the map is not "
            "waiting on a dialog."
        ),
    }


@tool()
def clear_caves() -> dict:
    """Wipe the entire cave layer back to solid rock.

    Removes all carved caves at once (the whole cave system), rebuilding the
    mesh. Undoable like dig_cave. Use this instead of filling regions back with
    dig_cave(dig=False) when you want to reset all caves.
    """
    return bridge.request("clear_caves")


# --------------------------------------------------------------------------
# Modify / delete
# --------------------------------------------------------------------------


@tool()
def move_element(id: int, x: float, y: float) -> dict:
    """Move any element to a new woxel position by id."""
    return bridge.request("move_element", id=id, x=x, y=y)


MOVE_ELEMENTS_LIMIT = 1000


@tool()
def move_elements(
    ids: list[int],
    dx: float,
    dy: float,
    rotation: float = 0.0,
    pivot_x: float | None = None,
    pivot_y: float | None = None,
) -> dict:
    """Move many elements by the same offset, in one call and ONE undo step.

    Use it for anything that moves as a group: a prefab (its `ids` come back
    from place_prefab), a scattered cluster, a furnished corner. Moving them one
    at a time costs a call and an undo slot each, and the undo history holds 40.

    ids: element ids, up to 1000.
    dx, dy: offset in woxels (256 = one tile).

    rotation: optional degrees around the group geometry's bounding-box centre,
      or around pivot_x/pivot_y when both are supplied; translation follows.
    Walls keep their saved geometry and carry mounted doors/windows with them.
    Duplicate ids move once. Text anchors move while labels stay upright.
    Cave-generated walls and mounted portals without their wall are reported
    in `unsupported`, with reasons. Returns `moved`, `missing`, `unsupported`,
    the applied offset/rotation and pivot. Inspect these before repeating a prefab.
    """
    if not ids:
        raise ValidationError("ids must not be empty")
    if len(ids) > MOVE_ELEMENTS_LIMIT:
        raise ValidationError(f"ids is capped at {MOVE_ELEMENTS_LIMIT} per call")
    for field, value in [
        ("dx", dx),
        ("dy", dy),
        ("rotation", rotation),
        ("pivot_x", pivot_x),
        ("pivot_y", pivot_y),
    ]:
        require_finite(value, field)
    if (pivot_x is None) != (pivot_y is None):
        raise ValidationError("provide both pivot_x and pivot_y")
    params: dict = {"ids": list(ids), "dx": dx, "dy": dy}
    if rotation:
        params["rotation"] = rotation
    if pivot_x is not None:
        params["pivot_x"] = pivot_x
        params["pivot_y"] = pivot_y
    return bridge.request("move_elements", **params)


@tool()
def modify_object(
    id: int,
    scale: float | None = None,
    rotation: float | None = None,
    color: str = "",
    modulate: str = "",
    shadow: bool | None = None,
    layer: int | None = None,
    block_light: bool | None = None,
) -> dict:
    """Modify an existing object's scale, rotation (degrees), color, shadow
    and/or light-blocking by id.

    block_light: whether this object STOPS light passing through it. A drawn
      shadow and a light block are different things — a crate stack with a
      shadow but no block still lets a lantern light the room through it. Set
      it on anything solid enough to stand behind: crates, bookcases, screens,
      a wagon. get_element reports it back.

    modulate: nonempty values are refused because the tint does not survive
      saving and reopening.
    color is REFUSED: colour is baked at placement and cannot be changed
    afterwards, here or in Dungeondraft's own UI. Set it in place_object.

    layer: move an existing object to a layer VALUE (multiple of 100, -500..900).
    Unlike colour this IS changeable after placement, and it is how a map built
    before layers were assigned correctly gets repaired.
    """
    require_hex_color(color, "color")
    require_hex_color(modulate, "modulate")
    if modulate:
        raise ValidationError(
            "modulate is unavailable because Dungeondraft does not preserve it when saving "
            "and reopening. No changes were made."
        )
    if layer is not None:
        require_choice(layer, list(range(-500, 1000, 100)), "layer")
    params: dict = {"id": id}
    if scale is not None:
        params["scale"] = scale
    if rotation is not None:
        params["rotation"] = rotation
    if color:
        params["color"] = color
    if modulate:
        params["modulate"] = modulate
    if shadow is not None:
        params["shadow"] = shadow
    if layer is not None:
        params["layer"] = layer
    if block_light is not None:
        params["block_light"] = block_light
    return bridge.request("modify_object", **params)


@tool()
def duplicate_object(id: int, dx: float = 64.0, dy: float = 0.0) -> dict:
    """Duplicate an object by id, offset by (dx, dy) woxels. Returns the new element id."""
    return bridge.request("duplicate_object", id=id, dx=dx, dy=dy)


@tool()
def delete_element(id: int) -> dict:
    """Delete any element from the map by id. Reversible with undo().

    The element is detached rather than destroyed, so undo() puts it back
    exactly where it was, with its id intact.

    To take back what a place_prefab, scatter_objects or build_room just made,
    call undo() once instead of deleting its pieces: each of those is ONE undo
    step, but only while it is still the latest undoable operation. Anything
    done since has to be undone first, which may not be what you want.

    It leaves the map on the NEXT frame, so a get_status immediately after may
    still count it. Read the count back a moment later, not in the same breath.

    Terrain, water and floor shapes are layers, not elements: they have no id
    and cannot be deleted. Paint over them, or draw them again with invert.
    """
    return bridge.request("delete_element", id=id)


@tool()
def delete_elements(ids: list[int]) -> dict:
    """Delete many elements in ONE call and ONE undo step. Reversible with undo().

    Deleting one at a time costs a call and an undo slot each, and the history
    holds 40 steps — a large group can push everything built before it out of
    reach.

    Before reaching for this on something you just created: a place_prefab,
    scatter_objects, place_objects or build_room call is already a single undo
    step, so undo() takes the whole thing back while it is the latest
    operation. Use this for elements from different calls, or older work.

    Up to 100 ids. Every id is resolved before anything is deleted: if one is
    unknown the batch changes nothing and names it, rather than leaving you to
    work out how far it got.
    """
    if not ids:
        raise ValidationError("ids must not be empty")
    if len(ids) > BATCH_LIMIT:
        raise ValidationError(f"ids is capped at {BATCH_LIMIT} per call")
    for ident in ids:
        if isinstance(ident, bool) or not isinstance(ident, int) or ident < 0:
            raise ValidationError(f"element ids must be nonnegative integers, got {ident!r}")
    return bridge.request("delete_elements", ids=list(ids))


# --------------------------------------------------------------------------
# Levels
# --------------------------------------------------------------------------


@tool()
def add_level(label: str = "Level") -> dict:
    """Add a new level (floor) to the map. Returns its id and label."""
    return bridge.request("add_level", label=label)


@tool()
def set_map_size(width: int, height: int) -> dict:
    """Resize the current map, in TILES (a tile is 256 woxels).

    Dungeondraft's new-map dialog is only reachable before a map is open, which
    is before mods load — so this is the way to get the map dimensions you want.
    Set the size before laying anything out. Existing content is not moved or
    clipped; only the canvas bounds change.
    """
    return bridge.request("set_map_size", width=width, height=height)


@tool()
def delete_level(id: int) -> dict:
    """Delete a level (floor) by its id (see list_levels). Not undoable.

    Refused when it would remove the map's only level.
    """
    return bridge.request("delete_level", id=id)


@tool()
def set_level(id: int) -> dict:
    """Switch the active level (floor) by its **id** (see list_levels).

    Use the `id` field, not `index`: they are different numbers. Adding a level
    puts it at index 0 with a higher id, and deletions leave gaps in the ids.
    """
    return bridge.request("set_level", id=id)


# --------------------------------------------------------------------------
# Capture — let the model see its own work
# --------------------------------------------------------------------------


def _shown(image: Image, path: str, what: str) -> list[Image | str]:
    """The image for the model, and where the file is for the person.

    A client shows an MCP image to the model but typically folds it inside the
    tool call, so "show me" is answered by a description the user cannot check
    unless they expand the call. Naming the saved file lets the model hand it
    over. Found in the first Claude UAT run of C2 (2026-09-21).
    """
    return [
        image,
        f"{what} saved: {path}\nYou can see this image; the user cannot unless they "
        "open that file. If they asked to see it, give them this path.",
    ]


@tool()
def screenshot(max_px: int | None = None) -> list[Image | str]:
    """Capture the current Dungeondraft window (the on-screen view) and return it as an image.

    Fast; shows exactly what's visible including the current camera framing —
    so AIM FIRST, or you photograph whatever the last call left on screen:
    focus_element(id) for one thing, fit_elements() for the whole map. For a
    clean full-map render without UI, use export_map.

    max_px: shrink the image's long edge to this before returning it. Omit for
      the full capture. Worth setting when you are checking placement or
      coverage rather than judging materials and detail — a smaller image is a
      cheaper thing to look at, and every image stays in the conversation.

    The result also names the saved file, at full resolution. The user does not
    see the image you receive, so when they ask to see the map, give them that
    path. Captures are kept until newer ones replace them (20 by default).
    """
    _require_max_px(max_px)
    name = f"screenshot-{uuid4().hex}.png"
    res = bridge.request("screenshot", name=name)
    path = _capture_path(res.get("path"), name)
    data = _wait_for_file(path)
    _prune_captures()
    return _shown(
        Image(data=_downscale(data, max_px, "png"), format="png"), str(path), "Screenshot"
    )


@tool()
def clear_captures() -> dict:
    """Remove every server-generated screenshot, export, and asset preview.

    This only deletes regular files directly in Dungeondraft's `mcp_output`
    directory whose names the server generates. It never recurses into the
    directory or removes other files a user has placed there.
    """
    return {"cleared": _remove_captures(_generated_capture_files())}


EXPORT_WAIT_DEFAULT = 120.0
EXPORT_WAIT_MAX = 600.0


def _wait_for_operation(operation_id: str, timeout: float) -> dict:
    """Poll the bridge until an export settles, and return its final status.

    Polling is a read, so a poll that times out is simply retried: the final
    stitch and encode block Dungeondraft's main thread for seconds at large
    sizes, and the socket is served on that thread.
    """
    deadline = time.monotonic() + timeout
    status: dict = {}
    unreachable: BridgeUnavailableError | None = None
    while time.monotonic() < deadline:
        try:
            status = bridge.request("get_operation", operation_id=operation_id)
        except BridgeUnavailableError as exc:
            unreachable = exc
        else:
            unreachable = None
            if status.get("state") != "rendering":
                return status
            if status.get("overdue"):
                # Waiting longer cannot help: the bridge will not release the
                # lock until it sees the exporter stop, and it has not.
                raise ValidationError(f"export {operation_id} is {status.get('recovery')}")
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    if unreachable is not None:
        raise BridgeUnavailableError(
            f"lost the bridge while export {operation_id} was rendering: {unreachable}"
        )
    raise ValidationError(
        f"export {operation_id} is still rendering after {timeout:.0f}s "
        f"({status.get('chunks_rendered', '?')} chunks so far). Nothing is lost: "
        f"call get_export(operation_id={operation_id!r}) to keep waiting for the image, "
        "or get_operation to check on it. Edits are refused until it settles."
    )


def _export_image(status: dict, max_px: int | None = None) -> list[Image | str]:
    if status.get("state") != "completed":
        raise ValidationError(
            f"export {status.get('operation_id')} {status.get('state')}: "
            f"{status.get('error') or 'no reason reported'}"
        )
    ext = str(status.get("format") or "png")
    # The bridge settles an export when its file appears, and Dungeondraft writes
    # it within one blocking frame; decoding still proves the bytes are whole.
    path = _capture_path(status.get("path"))
    data = _wait_for_file(path, timeout=10.0)
    _prune_captures()
    fmt = "jpeg" if ext in ("jpg", "jpeg") else ext
    # The file on disk keeps the resolution that was asked for; only the copy
    # handed to the model is shrunk, so a delivery render stays deliverable.
    return _shown(Image(data=_downscale(data, max_px, fmt), format=fmt), str(path), "Export")


def _require_wait(timeout: float) -> None:
    require_finite(timeout, "timeout")
    if not 0 < timeout <= EXPORT_WAIT_MAX:
        raise ValidationError(f"timeout must be in (0, {EXPORT_WAIT_MAX:.0f}] seconds")


@tool()
def export_map(
    ppi: int = 40,
    format: str = "png",
    timeout: float = EXPORT_WAIT_DEFAULT,
    max_px: int | None = None,
) -> list[Image | str]:
    """Render the entire current map to a clean image (no UI) and return it.

    ppi controls resolution (pixels per grid cell): higher = sharper but larger/slower.
    Dungeondraft abandons any export wider or taller than 16384 px without a
    word, so one that large is refused up front with the highest ppi this map
    allows.

    format: 'png' (default), 'jpg' or 'webp'.

    The render is a tracked operation: this waits up to `timeout` seconds
    (max 600). If that runs out, the error names the operation; collect the
    image with get_export rather than exporting again. While an export renders,
    edits, camera moves and screenshots are refused — the exporter renders by
    moving the camera, and any of those would corrupt the image.

    max_px: shrink the long edge of the image RETURNED to you. The file written
      to disk keeps the resolution `ppi` asked for, so this costs the delivery
      nothing — it only makes the copy you look at smaller. `ppi` is the knob
      that makes the render itself faster.

    Universal VTT is NOT available here: it only works from Dungeondraft's own
    export window. Tell the user to export from the app and choose
    "Universal VTT".
    """
    require_choice(format.lower(), ["png", "jpg", "jpeg", "webp"], "format")
    if isinstance(ppi, bool) or not isinstance(ppi, int) or ppi < 1:
        raise ValidationError("ppi must be a positive integer")
    _require_wait(timeout)
    _require_max_px(max_px)
    ext = "jpg" if format.lower() == "jpeg" else format.lower()
    started = bridge.request("export_map", name=f"export-{uuid4().hex}.{ext}", ppi=ppi, format=ext)
    return _export_image(_wait_for_operation(str(started["operation_id"]), timeout), max_px)


@tool()
def get_export(
    operation_id: str, timeout: float = EXPORT_WAIT_DEFAULT, max_px: int | None = None
) -> list[Image | str]:
    """Wait for an export that export_map started, and return its image.

    Use it when export_map ran out of time: the render carries on in
    Dungeondraft, and exporting again would only be refused until it finishes.
    Raises if the export failed, with the reason.

    max_px: as in export_map — shrinks only the copy returned to you.
    """
    _require_wait(timeout)
    _require_max_px(max_px)
    return _export_image(_wait_for_operation(operation_id, timeout), max_px)


@tool()
def get_operation(operation_id: str = "") -> dict:
    """Status of an export: `state` is rendering, completed or failed.

    Also reports `chunks_rendered`, `elapsed_ms`, the output `path`, the
    `pixels` it renders to and, on failure, `error`. Without an id, returns the
    `current` export (or null) and the `recent` settled ones. The bridge keeps
    the last 16 and forgets them when a map is opened or Dungeondraft restarts.
    """
    if operation_id:
        return bridge.request("get_operation", operation_id=operation_id)
    return bridge.request("get_operation")


# --------------------------------------------------------------------------
# Camera
# --------------------------------------------------------------------------


@tool()
def get_camera() -> dict:
    """Report the editor camera: world-center position [x,y], zoom, and viewport size.

    zoom is a Camera2D factor where LARGER = zoomed OUT (zoom 0.5 magnifies 2x,
    zoom 2.0 shows twice as much). Use this to read the view before adjusting it.
    """
    return bridge.request("get_camera")


@tool()
def set_camera(
    x: float | None = None,
    y: float | None = None,
    zoom: float | None = None,
) -> dict:
    """Pan and/or zoom the editor camera. Returns the resulting camera state.

    x, y: world (woxel) center to move the view to (omit to keep current).
    zoom: Camera2D factor (LARGER = zoomed OUT; ~0.5 = a close look, ~2 = wide).
    Follow with screenshot() to see the framed view.
    """
    params: dict = {}
    if x is not None:
        params["x"] = x
    if y is not None:
        params["y"] = y
    if zoom is not None:
        params["zoom"] = zoom
    return bridge.request("set_camera", **params)


@tool()
def focus_element(id: int, zoom: float | None = None) -> dict:
    """Center the camera on an element by id (works for any kind, including text).

    zoom: optional Camera2D factor to apply (LARGER = zoomed OUT). Follow with
    screenshot() to verify a specific element (e.g. a door cut into a wall).
    """
    params: dict = {"id": id}
    if zoom is not None:
        params["zoom"] = zoom
    return bridge.request("focus_element", **params)


@tool()
def fit_elements(ids: list[int] | None = None, pad: float = 0.15) -> dict:
    """Frame the whole map, or a group of elements, then screenshot() to see it.

    ids: omit to frame the entire map — this is the normal way to look at your
      work. Pass ids to frame just those elements instead; ids without a
      position are skipped and listed in the 'missing' field.
    pad: extra margin as a fraction (0.15 = 15%).

    Prefer this over set_camera: it computes the zoom for you, and set_camera's
    zoom is woxels-per-pixel, which runs backwards from the intuition that a
    bigger number means closer.
    """
    return bridge.request("fit_elements", ids=ids or [], pad=pad)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


@tool()
def select_elements(ids: list[int]) -> dict:
    """Select the given element ids in Dungeondraft's UI (replaces the current selection)."""
    return bridge.request("select_elements", ids=ids)


@tool()
def clear_selection() -> dict:
    """Clear the current selection in Dungeondraft."""
    return bridge.request("clear_selection")


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


@tool()
def undo() -> dict:
    """Reverse the LATEST undoable edit (create / delete / move / modify / terrain / cave).

    The bridge keeps its own undo/redo stack of 40 steps, independent of
    Dungeondraft's Ctrl+Z. A whole place_prefab, scatter_objects, build_room or
    move_elements call is one step, so one undo reverses all of it — provided
    nothing undoable has happened since. Undo always takes the newest step; it
    cannot target an older one.
    """
    return bridge.request("undo")


@tool()
def redo() -> dict:
    """Re-apply the last edit reversed by undo()."""
    return bridge.request("redo")


# --------------------------------------------------------------------------
# Dungeondraft 1.2 hooks
# --------------------------------------------------------------------------


@tool()
def get_recent_nodes(since: int = 0, limit: int = 200) -> dict:
    """List the ids Dungeondraft has assigned to nodes it created, newest last.

    Use this to learn the ids of things you did NOT place one at a time —
    the contents of a prefab, everything a generated dungeon produced. Without
    it those can only be counted, not moved, modified or deleted.

    Pass `since` from a previous call's `next_since` to get only what is new.
    `dropped_older` means the log wrapped and some ids were lost — read it more
    often, or take the ids straight off `place_prefab` / `generate_dungeon`,
    which report their own.

    since: return assignments after this sequence number (0 = everything held).
    limit: maximum rows to return.
    """
    return bridge.request("get_recent_nodes", since=since, limit=limit)


@tool()
def get_tool_layer(tool: str) -> dict:
    """Read which layer a tool draws on, and the range of layers that exist.

    Layers stack: lower numbers sit under higher ones. Values run from -500 to
    900 in steps of 100 (`min`, `max` and `step` in the response). 100 is the
    default for every tool except MaterialBrush, which starts at -400 so floors
    sit under everything.

    tool: e.g. "ObjectTool", "PathTool", "PatternShapeTool". A tool without
        layers is refused, and the error lists the ones that have them.
    """
    return bridge.request("get_tool_layer", tool=tool)


@tool()
def set_tool_layer(tool: str, layer: int) -> dict:
    """Set which layer a tool draws on, for everything it places afterwards.

    Use it to put a rug under furniture, a bridge over water, or roots below
    the ground. Call get_tool_layer first to see the current layer and the
    range.

    Check `applied` in the response: Dungeondraft silently keeps its current
    layer if it will not accept the one you asked for, and the response reports
    what the tool actually holds rather than what you requested.

    tool: e.g. "ObjectTool", "PathTool", "PatternShapeTool".
    layer: layer VALUE, a multiple of 100 from -500 to 900 — not a menu index.
    """
    return bridge.request("set_tool_layer", tool=tool, layer=layer)


@tool()
def select_tool(tool: str) -> dict:
    """Select a tool in Dungeondraft's UI, as clicking its button would.

    Mostly useful for leaving the editor on a sensible tool when you are done,
    so the person who takes over is not looking at whichever tool your last
    call happened to need.

    tool: exact tool name, e.g. "ObjectTool", "SelectTool", "WallTool".
    """
    return bridge.request("select_tool", tool=tool)


@tool()
def inspect_dungeondraft_installation(live: bool = False) -> dict:
    """Report bridge-install health; by default, no token or live connection is used.

    Check the folder recorded as `[Mods] mods_directory` in config.ini, or the
    platform default when none is set. Dungeondraft can also discover built-in
    mods, so `other_copies` must not be assumed inactive. Multiple discovery
    paths in a log are ambiguous; their order does not identify the loaded copy.

    status: healthy | outdated (unmodified, but older than this package) |
    modified | unknown | missing.

    This compares files on disk and reports historical evidence from the latest
    editor log. Log evidence is not proof of the current process. To learn which
    bridge Dungeondraft is actually
    RUNNING, call ping: its `bridge_current` hashes the live source. This check
    never launches Dungeondraft. With live=True, authenticate a read-only ping
    to report the executing mod's root, process ID and source identity separately
    from historical log evidence. Older bridges may not report their location.
    """
    state_dir = installer.default_state_dir()
    configured = installer.configured_mods_dir(installer.dungeondraft_data_dir() / "config.ini")
    candidates = installer.candidate_mods_dirs()
    loaded = (
        configured
        if configured is not None
        else next((path for path in candidates if path.is_dir()), candidates[0])
    )
    report = installer.doctor(loaded, state_dir=state_dir)
    others = []
    for path in candidates:
        if path == loaded or not (path / "battlemap-mcp-bridge").is_dir():
            continue
        other = installer.doctor(path, state_dir=state_dir)
        others.append({"destination": str(other.destination), "status": other.status})
    evidence = installer.latest_log_evidence(installer.dungeondraft_data_dir())
    return {
        "destination": str(report.destination),
        "status": report.status,
        "recommended_action": report.recommended_action,
        "mods_directory": str(loaded),
        "mods_directory_source": (
            "Dungeondraft config.ini" if configured is not None else "platform default"
        ),
        "other_copies": others,
        "live_identity": (
            vars(installer.live_bridge_identity()) if live else {"status": "not checked"}
        ),
        "latest_log": {
            "status": evidence.status,
            "path": str(evidence.path) if evidence.path is not None else None,
            "mod_path": evidence.mod_path,
            "discovered_mod_paths": list(evidence.mod_paths),
            "protocol": evidence.protocol,
            "live_verified": False,
        },
    }


@tool()
def install_dungeondraft_bridge(mods_dir: str = "", confirm: bool = False) -> dict:
    """Preview bridge installation; apply only when confirm is true.

    Provide an explicit Dungeondraft mods directory. This never starts
    Dungeondraft or changes a map; conflicts must be resolved through the CLI
    with --force so a backup can be reviewed.
    """
    if not mods_dir:
        return {
            "changed": False,
            "requires_mods_dir": True,
            "candidates": [str(path) for path in installer.candidate_mods_dirs()],
        }

    plan = installer.plan_install(
        Path(mods_dir),
        datetime.now(UTC),
        state_dir=installer.default_state_dir(),
    )
    preview = {
        "changed": False,
        "destination": str(plan.destination),
        "actions": list(plan.actions),
        "requires_force": plan.requires_force,
    }
    if not confirm:
        return preview

    try:
        result = installer.apply_install(plan, force=False)
    except installer.InstallConflictError as exc:
        return {**preview, "conflict": str(exc)}
    return {
        "changed": result.changed,
        "destination": str(result.destination),
        "backup_destination": None,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
