#!/usr/bin/env python3
"""Exercise bridge commands against a running Dungeondraft.

Use --help for capture and mutation options; mutating runs require an
explicitly named disposable map."""

import json
import pathlib
import re
import sys
import time

from disposable import NotDisposable, require_disposable_map

from battlemap_mcp.bridge_client import BridgeClient, BridgeError
from battlemap_mcp.errors import (
    BridgeCommandError,
    BridgeProtocolError,
    BridgeUnavailableError,
    ValidationError,
)

CAPTURE = "--capture" in sys.argv
FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"

bridge = BridgeClient()
created_ids: list[int] = []
passed = 0
failed = 0

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]")

# Which label a capture run has already written each fixture filename for.
# Sanitisation is many-to-one ("foo bar", "foo/bar", and "foo_bar" all map to
# "foo_bar"), so record() uses this to catch two different labels silently
# clobbering the same fixture. Keyed by sanitized name -> the label that
# claimed it this run; reset per-process (a capture run is one process).
_recorded_labels: dict[str, str] = {}

_USERNAME_FIELDS = {"username", "user_name", "user", "author", "owner"}
_SAVE_DIRECTORY_FIELDS = {"configured", "effective"}
_FILESYSTEM_PATH_FIELDS = {"path", "last_saved", "stale_path", "opening"}
_FILESYSTEM_PATH_COMMANDS = {
    "export_map",
    "get_operation",
    "get_status",
    "open_map",
    "preview_assets",
    "save_map",
    "screenshot",
    "set_trace_image",
}
_SAVE_DIRECTORY_COMMANDS = {"get_save_directory", "set_save_directory"}


def _is_absolute_local_path(value: str) -> bool:
    """Whether ``value`` is an OS path rather than a stable ``res://`` asset reference."""
    normalized = re.sub(r"[\\/]+", "/", value)
    return normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/+", normalized))


def _is_path_inside_home(value: str) -> bool:
    """Whether an arbitrary response string is an absolute path in this user's home."""
    path = re.sub(r"[\\/]+", "/", value).rstrip("/").casefold()
    home = re.sub(r"[\\/]+", "/", str(pathlib.Path.home())).rstrip("/").casefold()
    return path == home or path.startswith(f"{home}/")


def _scrub_value(key: str, value: object, command: str) -> object:
    if key == "map_file" and isinstance(value, str) and value:
        return "<MAP_FILE>"
    if key in _USERNAME_FIELDS and isinstance(value, str) and value:
        return "<USERNAME>"
    if key == "text" and isinstance(value, str) and value:
        return "<MAP_TEXT>"
    if command == "list_asset_packs" and key == "name" and isinstance(value, str) and value:
        return "<ASSET_PACK_NAME>"
    if command in _SAVE_DIRECTORY_COMMANDS and isinstance(value, str) and value:
        if key in _SAVE_DIRECTORY_FIELDS or key == "save_directory":
            return "<SAVE_DIRECTORY>"
        if key == "config_file":
            return "<CONFIG_FILE>"
    if isinstance(value, str) and (
        _is_path_inside_home(value)
        or (
            command in _FILESYSTEM_PATH_COMMANDS
            and key in _FILESYSTEM_PATH_FIELDS
            and _is_absolute_local_path(value)
        )
        or (key.endswith("_path") and _is_absolute_local_path(value))
    ):
        return "<PATH>"
    nested_command = "list_asset_packs" if key == "asset_packs" else command
    return scrub_fixture(value, command=nested_command)


def scrub_fixture(value: object, *, command: str) -> object:
    """Replace recorder-specific data in a live response with stable fixture values.

    Captured replies are tracked in Git. Paths, map text, account names, and
    personal asset-pack metadata therefore must not be written verbatim.
    Protocol data such as ids, coordinates, and ``res://`` asset references is
    deliberately retained for the offline contract tests.
    """
    if isinstance(value, dict):
        return {str(key): _scrub_value(str(key), item, command) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_fixture(item, command=command) for item in value]
    if isinstance(value, str):
        # List items and free-form diagnostics do not have field names. Check
        # those too, without persisting the recorder's home path in a fixture.
        normalized = re.sub(r"[\\/]+", "/", value).casefold()
        home = re.sub(r"[\\/]+", "/", str(pathlib.Path.home())).rstrip("/").casefold()
        if home and home in normalized:
            return "<PATH>"
        if command in _FILESYSTEM_PATH_COMMANDS and _is_absolute_local_path(value):
            return "<PATH>"
    return value


def sanitize_fixture_name(label: str) -> str:
    """Turn a check() label into a safe, flat fixture filename stem.

    Labels are free-text ("undo/redo", "list levels") meant for humans, not
    filesystems: a `/` resolves into a subdirectory that may not exist, and
    other characters can be equally hostile depending on the OS. Anything
    that isn't alphanumeric, `_`, `-`, or `.` becomes `_`, so the mapping is
    obvious from the label and stays stable across runs (fixtures are
    committed and may be referenced by name in tests). Leading dots are then
    stripped too, so a label can never sanitize to a dotfile that a plain
    `*.json` glob would silently skip.
    """
    safe = _UNSAFE_CHARS.sub("_", label).strip("_").lstrip(".")
    if not safe:
        raise ValueError(f"label {label!r} sanitizes to an empty filename")
    return safe


def record(cmd: str, result: dict) -> None:
    """Persist a real bridge response so tests run against recorded data.

    Hand-written fixtures encode beliefs about the protocol; tests then pass
    against a fiction while production drifts. These are captured from a live
    bridge instead.

    Sanitisation is many-to-one, so two different labels could otherwise
    silently overwrite each other's fixture with no warning. Re-recording the
    *same* label (e.g. running --capture twice) is fine and expected.
    """
    if not CAPTURE:
        return
    FIXTURES.mkdir(parents=True, exist_ok=True)
    name = sanitize_fixture_name(cmd)
    other_label = _recorded_labels.get(name)
    if other_label is not None and other_label != cmd:
        raise ValueError(
            f"labels {other_label!r} and {cmd!r} both sanitize to fixture "
            f"filename {name}.json; rename one of the check() labels so "
            f"they no longer collide"
        )
    _recorded_labels[name] = cmd
    (FIXTURES / f"{name}.json").write_text(
        json.dumps(scrub_fixture(result, command=cmd), indent=2, sort_keys=True), encoding="utf-8"
    )


def check(label, fn):
    global passed, failed
    try:
        result = fn()
    except ValidationError:
        # This script builds every request itself, so a ValidationError means
        # a bug in this script's own params — not a bridge fault. Misreporting
        # it as a bridge FAIL would hide that distinction from whoever reads
        # the PASS/FAIL summary, so let it crash loudly instead of counting it
        # against the live bridge.
        print(f"  INVALID {label:16} -> request built by this script failed validation")
        raise
    except (BridgeUnavailableError, BridgeProtocolError, BridgeCommandError) as exc:
        print(f"  FAIL  {label:18} -> {exc}")
        failed += 1
        return None
    print(f"  PASS  {label:18} -> {result}")
    passed += 1
    record(label, result)
    return result


def first_asset(category, search=""):
    """First asset in a category, or None when the category holds none.

    An empty category is REFUSED, not returned empty: "Patterns" exists in
    every installation and fills only from asset packs, and it is empty even
    with fourteen packs loaded. Callers here already branch on None (there is a
    "SKIP place_pattern" path), but the refusal came back as an exception and
    took the whole run down before reaching it.
    """
    try:
        res = bridge.request("list_assets", category=category, search=search, limit=1)
    except BridgeCommandError as exc:
        if "holds no assets" in str(exc):
            return None
        raise
    assets = res.get("assets") or []
    return assets[0] if assets else None


def main() -> int:
    # Terrain, cave and water edits are map-wide and cannot be undone by
    # deleting ids, so they are gated rather than skipped silently.
    dirty = "--dirty" in sys.argv
    named_map = ""
    if "--map" in sys.argv:
        index = sys.argv.index("--map")
        if index + 1 < len(sys.argv):
            named_map = sys.argv[index + 1]

    if dirty:
        try:
            confirmed = require_disposable_map(bridge, named_map, "verify_live --dirty")
        except NotDisposable as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(f"mutating map: {confirmed}\n")

    try:
        status = bridge.request("ping")
    except BridgeError as exc:
        print("Cannot reach the bridge:", exc, file=sys.stderr)
        return 1
    print("Bridge reachable:", status, "\n")

    cx, cy = 6400, 6400
    st = check("get_status", lambda: bridge.request("get_status"))
    if st and st.get("map_center"):
        cx, cy = st["map_center"]

    check("list_categories", lambda: bridge.request("list_asset_categories"))
    check("list_asset_packs", lambda: bridge.request("list_asset_packs"))
    check("get_terrain", lambda: bridge.request("get_terrain", samples=3))

    obj_asset = first_asset("Objects")
    wall_asset = first_asset("Walls")
    path_asset = first_asset("Paths")

    # --- create ---
    obj = check("place_object", lambda: bridge.request("place_object", asset=obj_asset, x=cx, y=cy))
    if obj:
        created_ids.append(obj["id"])

    def verify_batch():
        """One call places three, one call deletes them, one undo brings them back."""
        batch = bridge.request(
            "place_objects",
            objects=[
                {"asset": obj_asset, "x": cx + 300 + step * 120, "y": cy - 700} for step in range(3)
            ],
        )
        made = [entry["id"] for entry in batch["objects"]]
        assert batch["placed"] == 3 and len(made) == 3, batch
        for ident in made:
            assert bridge.request("get_element", id=ident)["id"] == ident

        removed = bridge.request("delete_elements", ids=made)
        assert removed["deleted"] == 3, removed
        assert bridge.request("undo")["undone"] is True
        # The bridge detaches on the NEXT frame and reattaches the same way, so
        # read the elements back rather than a count taken in the same breath.
        time.sleep(0.3)
        for ident in made:
            assert bridge.request("get_element", id=ident)["id"] == ident
        created_ids.extend(made)
        return {"placed": batch["placed"], "deleted": removed["deleted"], "restored": made}

    check("place_objects/delete_elements", verify_batch)

    room = [[cx - 200, cy - 200], [cx + 200, cy - 200], [cx + 200, cy + 200], [cx - 200, cy + 200]]
    wall = check(
        "draw_wall",
        lambda: bridge.request("draw_wall", points=room, asset=wall_asset or "", loop=True),
    )
    if wall:
        created_ids.append(wall["id"])

    def verify_merge():
        pair = [
            bridge.request("draw_wall", points=points, asset=wall_asset or "")["id"]
            for points in (
                [[cx - 600, cy - 600], [cx - 400, cy - 600]],
                [[cx - 400, cy - 600], [cx - 400, cy - 400]],
            )
        ]
        created_ids.extend(pair)
        result = bridge.request("merge_walls", ids=pair)
        assert result["id"] == pair[0] and result["removed_ids"] == pair[1:]
        assert bridge.request("undo")["kind"] == "wall_merge"
        return result

    check("merge_walls", verify_merge)

    if path_asset:
        path = check(
            "draw_path",
            lambda: bridge.request(
                "draw_path",
                points=[[cx - 300, cy], [cx, cy - 50], [cx + 300, cy]],
                asset=path_asset,
            ),
        )
        if path:
            created_ids.append(path["id"])
    else:
        print("  SKIP  draw_path          -> no Paths assets")

    light = check("add_light", lambda: bridge.request("add_light", x=cx, y=cy, energy=1.5))
    if light:
        created_ids.append(light["id"])

    # --- query / modify ---
    listed = check(
        "list_elements", lambda: bridge.request("list_elements", kind="objects", limit=5)
    )
    # validate_placements measures every footprint from texture_size, and has
    # no other source for it. If the bridge stops reporting it, that tool goes
    # on answering — reporting a clean map while measuring nothing — so the one
    # live-checkable part of it is asserted here rather than trusted.
    if listed and listed.get("elements"):

        def measured():
            sized = [e for e in listed["elements"] if e.get("texture_size")]
            if not sized:
                raise BridgeCommandError(
                    "no object reported texture_size; validate_placements "
                    "would measure nothing and report a clean map"
                )
            return {"texture_size": sized[0]["texture_size"], "of": len(sized)}

        check("texture_size", measured)
    check("get_composition_snapshot", lambda: bridge.request("get_composition_snapshot"))
    # Safe without force: on a healthy map it reports repaired=false and changes
    # nothing. That still proves the command is wired, which is what matters —
    # the forced path blanks terrain and has no place in a check that is meant
    # to be survivable on a map in progress.
    check("repair_terrain", lambda: bridge.request("repair_terrain", force=False))
    if obj_asset:
        check(
            "preview_assets",
            lambda: bridge.request(
                "preview_assets",
                category="Objects",
                assets=[obj_asset],
                columns=1,
                cell_px=64,
                name="verify_preview.png",
            ),
        )
    else:
        print("  SKIP  preview_assets     -> no Objects assets")
    if obj:
        check("get_element", lambda: bridge.request("get_element", id=obj["id"]))
        check(
            "move_element",
            lambda: bridge.request("move_element", id=obj["id"], x=cx + 80, y=cy + 80),
        )
        check(
            "move_elements",
            lambda: bridge.request("move_elements", ids=[obj["id"]], dx=-80, dy=-80),
        )
        check(
            "modify_object",
            lambda: bridge.request("modify_object", id=obj["id"], scale=1.5, rotation=45),
        )
        dup = check(
            "duplicate_object", lambda: bridge.request("duplicate_object", id=obj["id"], dx=120)
        )
        if dup:
            created_ids.append(dup["id"])

    check("list_levels", lambda: bridge.request("list_levels"))
    if created_ids:
        check("select_elements", lambda: bridge.request("select_elements", ids=created_ids))
        check("clear_selection", lambda: bridge.request("clear_selection"))

    # --- undo / redo round trip: place an object, undo it, redo it ---
    def undo_round_trip():
        before = bridge.request("get_status")["counts"]["objects"]
        bridge.request("place_object", asset=obj_asset, x=cx - 200, y=cy)
        after_create = bridge.request("get_status")["counts"]["objects"]
        bridge.request("undo")
        time.sleep(0.2)
        after_undo = bridge.request("get_status")["counts"]["objects"]
        bridge.request("redo")
        time.sleep(0.2)
        after_redo = bridge.request("get_status")["counts"]["objects"]
        # track whatever exists now so cleanup removes it
        for el in bridge.request("list_elements", kind="objects")["elements"]:
            if el["id"] not in created_ids:
                created_ids.append(el["id"])
        if not (after_create == before + 1 and after_undo == before and after_redo == before + 1):
            raise BridgeCommandError(
                f"counts before={before} create={after_create} undo={after_undo} redo={after_redo}",
                cmd="place_object/undo/redo",
                params={"asset": obj_asset, "x": cx - 200, "y": cy},
            )
        return f"object count {before}->{after_create} undo->{after_undo} redo->{after_redo}"

    check("undo/redo", undo_round_trip)

    # --- structure ---
    # Portals and roofs have no default asset — each needs one from its category.
    portal_asset = first_asset("Portals")
    if portal_asset:
        portal = check(
            "add_portal",
            lambda: bridge.request("add_portal", x=cx, y=cy - 200, width=256, asset=portal_asset),
        )
        if portal:
            created_ids.append(portal["id"])
    else:
        print("  SKIP  add_portal         -> no Portals assets")

    # A roof is defined by its ridge line, not a bounding box.
    roof_asset = first_asset("Roofs")
    if roof_asset:
        roof = check(
            "add_roof",
            lambda: bridge.request(
                "add_roof",
                points=[[cx + 600, cy + 600], [cx + 1100, cy + 600]],
                width=512,
                asset=roof_asset,
            ),
        )
        if roof:
            created_ids.append(roof["id"])
    else:
        print("  SKIP  add_roof           -> no Roofs assets")
    text = check("add_text", lambda: bridge.request("add_text", x=cx, y=cy + 400, text="verify"))
    if text:
        created_ids.append(text["id"])
    scatter = check(
        "scatter_objects",
        lambda: bridge.request(
            "scatter_objects",
            assets=[obj_asset],
            rect=[cx + 400, cy - 400, 512, 512],
            count=6,
            seed=1,
        ),
    )
    if scatter:
        created_ids.extend(scatter.get("ids", []))

    pattern_asset = first_asset("Patterns")
    if pattern_asset:
        pattern = check(
            "place_pattern",
            lambda: bridge.request(
                "place_pattern",
                asset=pattern_asset,
                rect=[cx - 800, cy - 800, 512, 512],
            ),
        )
        if pattern:
            created_ids.append(pattern["id"])
    else:
        print("  SKIP  place_pattern      -> no Patterns assets")

    room_args = {"rect": [cx - 1400, cy - 1400, 768, 768], "wall_asset": wall_asset or ""}
    if pattern_asset:
        room_args["floor_asset"] = pattern_asset
        room_args["floor_category"] = "Patterns"
    else:
        room_args["floor"] = "none"
    room_res = check("build_room", lambda: bridge.request("build_room", **room_args))
    if room_res:
        # build_room reports wall_id / floor_id, not `ids`: reading only `ids`
        # left one wall behind on every non-dirty run.
        created_ids.extend(
            room_res[key] for key in ("wall_id", "floor_id") if room_res.get(key) is not None
        )

    # --- camera and capture ---
    check("get_camera", lambda: bridge.request("get_camera"))
    check("set_camera", lambda: bridge.request("set_camera", x=cx, y=cy, zoom=4.0))
    check("fit_elements", lambda: bridge.request("fit_elements"))
    if obj:
        check("focus_element", lambda: bridge.request("focus_element", id=obj["id"]))
    check("screenshot", lambda: bridge.request("screenshot"))
    started = check(
        "export_map",
        lambda: bridge.request("export_map", name=f"verify-live-{time.time_ns()}.png", ppi=16),
    )

    def export_settles():
        # Everything after this edits the map, and edits are refused while an
        # export renders. Wait for it to settle rather than race it.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status = bridge.request("get_operation", operation_id=started["operation_id"])
            if status["state"] != "rendering":
                if status["state"] != "completed":
                    raise BridgeCommandError(f"export {status['state']}: {status.get('error')}")
                return status
            time.sleep(0.25)
        raise BridgeCommandError("export still rendering after 60s")

    if started:
        check("get_operation", export_settles)

    # --- levels: create, switch, and remove, leaving the map as it was ---
    def level_round_trip():
        before = bridge.request("list_levels")
        made = bridge.request("add_level", label="verify-live")
        switched = bridge.request("set_level", id=before["current_level_id"])
        bridge.request("delete_level", id=made["id"])
        after = bridge.request("list_levels")
        if len(after["levels"]) != len(before["levels"]):
            raise BridgeCommandError(
                f"level count {len(before['levels'])} -> {len(after['levels'])}",
                cmd="add_level/delete_level",
                params={},
            )
        return f"added id {made['id']}, switched to {switched['current_level_id']}, removed"

    check("levels", level_round_trip)

    check("get_save_directory", lambda: bridge.request("get_save_directory"))
    # Set it to its own effective value: exercises the write path without
    # disturbing whatever the user has configured.
    check(
        "set_save_directory",
        lambda: bridge.request(
            "set_save_directory",
            path=bridge.request("get_save_directory")["effective"],
        ),
    )

    check(
        "get_terrain",
        lambda: {
            k: v for k, v in bridge.request("get_terrain", samples=4).items() if k != "weights"
        },
    )

    # --- introspection ---
    check("list_prefabs", lambda: bridge.request("list_prefabs"))
    # 1.2 hooks. get_recent_nodes needs World.OnAssignNode connected, so this
    # doubles as a check that the signal wiring survived the map load.
    check("get_recent_nodes", lambda: bridge.request("get_recent_nodes", since=0, limit=5))
    check("get_tool_layer", lambda: bridge.request("get_tool_layer", tool="ObjectTool"))
    # Read-only whether or not the Custom Snap Mod is installed; the UAT's
    # snap group checks the grid against the mod's own snapping.
    check("get_snap_settings", lambda: bridge.request("get_snap_settings"))
    # A checkpoint rolled back at once reverses nothing, so this is safe on a
    # map in progress; the UAT's checkpoint group rolls back real work.
    check("checkpoint", lambda: bridge.request("checkpoint", label="verify-live"))
    check("list_checkpoints", lambda: bridge.request("list_checkpoints"))
    check(
        "rollback_checkpoint",
        lambda: bridge.request("rollback_checkpoint", label="verify-live"),
    )
    check(
        "list_tool_controls",
        lambda: bridge.request("list_tool_controls", tool="ObjectTool"),
    )

    # --- terrain and caves: map-wide state, so only with --dirty ---
    if dirty:
        terrain_asset = first_asset("Terrain")
        if terrain_asset:
            check(
                "set_terrain_slot",
                lambda: bridge.request("set_terrain_slot", asset=terrain_asset, slot=1),
            )
            check(
                "paint_terrain",
                lambda: bridge.request(
                    "paint_terrain",
                    points=[[cx, cy], [cx + 300, cy]],
                    slot=1,
                    radius=128,
                ),
            )
            check(
                "fill_region",
                lambda: bridge.request("fill_region", rect=[cx - 300, cy - 300, 400, 400], slot=1),
            )
        else:
            print("  SKIP  terrain            -> no Terrain assets")
        check("dig_cave", lambda: bridge.request("dig_cave", points=[[cx, cy]], radius=256))
        check("get_cave", lambda: bridge.request("get_cave"))
        check(
            "set_cave_entrance", lambda: bridge.request("set_cave_entrance", x=cx, y=cy, radius=128)
        )
        check("clear_caves", lambda: bridge.request("clear_caves"))
        # Water and floor shapes are layers, not objects: nothing to select and
        # delete. Both take invert, which erases inside the outline, so each is
        # drawn and then erased again to leave the map as it was found.
        pond = [[cx, cy], [cx + 512, cy], [cx + 512, cy + 512], [cx, cy + 512]]
        check("add_water", lambda: bridge.request("add_water", points=pond))
        check(
            "add_water invert",
            lambda: bridge.request("add_water", points=pond, invert=True),
        )
        slab = [cx - 2200, cy - 2200, 512, 512]
        check("add_floor", lambda: bridge.request("add_floor", rect=slab))
        check(
            "add_floor invert",
            lambda: bridge.request("add_floor", rect=slab, invert=True),
        )
    else:
        print(
            "  SKIP  terrain/caves/water -> map-wide and not cleanly reversible; "
            "re-run with --dirty on a throwaway map"
        )

    if dirty:
        check("set_ambient_light", lambda: bridge.request("set_ambient_light", color="#ffffff"))
        before_style = check("get_map_style", lambda: bridge.request("get_map_style"))
        if before_style:
            changed_style = check(
                "set_map_style",
                lambda: bridge.request(
                    "set_map_style",
                    building_wear="dust" if before_style["building_wear"] != "dust" else "none",
                    grid_style="dotted",
                ),
            )
            if changed_style:
                bridge.request("undo")
                assert bridge.request("get_map_style") == before_style
        # Trace image is per-EDITOR state, not part of the map, so it is gated
        # with the other visible changes and cleared again. Opacity alone
        # exercises the command without needing an image file on disk.
        check("set_trace_image", lambda: bridge.request("set_trace_image", opacity=0.5))
        bridge.request("set_trace_image", clear=True)

        material_asset = first_asset("Materials")
        if material_asset:
            check(
                "paint_material",
                lambda: bridge.request(
                    "paint_material",
                    points=[[cx + 700, cy + 700], [cx + 900, cy + 780]],
                    asset=material_asset,
                    size=2,
                ),
            )
        else:
            print("  SKIP  paint_material     -> no Materials assets")
        # Blending is a per-level setting that changes every terrain edge already
        # painted, so it is gated with the other map-wide edits and put back.
        was_smooth = bool((bridge.request("get_terrain", samples=2) or {}).get("smooth_blending"))
        check(
            "set_terrain_blending",
            lambda: bridge.request("set_terrain_blending", enabled=not was_smooth),
        )
        bridge.request("set_terrain_blending", enabled=was_smooth)
        # Water style is per LEVEL, so it is gated with the other map-wide
        # edits and put back the way it was found.
        before_water = bridge.request("set_water_style", blend_distance=32.0)
        check(
            "set_water_style",
            lambda: bridge.request(
                "set_water_style", deep_color="#12304f", shallow_color="#3a6b72"
            ),
        )
        bridge.request(
            "set_water_style",
            deep_color=before_water.get("deep_color", "#12304f"),
            shallow_color=before_water.get("shallow_color", "#3a6b72"),
            blend_distance=before_water.get("blend_distance", 32.0),
        )
        terrain2 = first_asset("Terrain")
        if terrain2:
            check("fill_terrain", lambda: bridge.request("fill_terrain", asset=terrain2))
        if terrain2:
            check(
                "paint_path",
                lambda: bridge.request(
                    "paint_path",
                    points=[[cx - 900, cy + 900], [cx - 600, cy + 900]],
                    asset=terrain2,
                    slot=1,
                ),
            )

        # Resize and put it straight back, so the map is left as it was found.
        def map_size_round_trip():
            st0 = bridge.request("get_status")["map_size_woxels"]
            w, h = int(st0[0] // 256), int(st0[1] // 256)
            bridge.request("set_map_size", width=w + 2, height=h + 2)
            grew = bridge.request("get_status")["map_size_woxels"]
            bridge.request("set_map_size", width=w, height=h)
            back = bridge.request("get_status")["map_size_woxels"]
            if grew == st0 or back != st0:
                raise BridgeCommandError(
                    f"{st0} -> {grew} -> {back}", cmd="set_map_size", params={}
                )
            return f"{st0} -> {grew} -> restored"

        check("set_map_size", map_size_round_trip)

    prefabs = check("list_prefabs_for_place", lambda: bridge.request("list_prefabs"))
    names = (prefabs or {}).get("prefabs") or []
    if dirty and names:
        placed = check(
            "place_prefab", lambda: bridge.request("place_prefab", name=names[0], x=cx, y=cy)
        )
        if placed:
            created_ids.extend(placed.get("ids", []))
    else:
        print("  SKIP  place_prefab       -> needs --dirty and a saved prefab")

    # Generic tool access, exercised on a control that is safe to read and set
    # back. tool_action presses a button, so it is only run under --dirty.
    controls = check(
        "list_tool_controls_object",
        lambda: bridge.request("list_tool_controls", tool="ObjectTool"),
    )
    # Use a control this tool actually has, read from list_tool_controls rather
    # than guessed. Shadow is a CheckButton, so it is safe to toggle and set back.
    names = [c.split(" : ")[0] for c in (controls or {}).get("controls", [])]
    if dirty and "Shadow" in names:
        check(
            "set_tool_option",
            lambda: bridge.request(
                "set_tool_option", tool="ObjectTool", control="Shadow", pressed=True
            ),
        )
        check(
            "tool_action",
            lambda: bridge.request("tool_action", tool="ObjectTool", control="Shadow"),
        )
    else:
        print("  SKIP  set_tool_option / tool_action -> needs --dirty")

    # The generator replaces the level's whole layout, so it only runs on a
    # map the caller has already declared disposable.
    if dirty:
        check(
            "generate_dungeon",
            lambda: bridge.request("generate_dungeon", design="Dungeon", floor=10, wall=10),
        )
        check("generator_options", lambda: bridge.request("generator_options"))
    else:
        print("  SKIP  generate_dungeon   -> replaces the layout; needs --dirty")

    def delete_round_trip():
        made = bridge.request("place_object", asset=obj_asset, x=cx - 500, y=cy - 500)
        before = bridge.request("get_status")["counts"]["objects"]
        bridge.request("delete_element", id=made["id"])
        # The node leaves the tree on the next frame (call_deferred), so give
        # the editor one before reading the count back.
        time.sleep(0.2)
        after_delete = bridge.request("get_status")["counts"]["objects"]
        bridge.request("undo")
        time.sleep(0.2)
        after_undo = bridge.request("get_status")["counts"]["objects"]
        created_ids.append(made["id"])
        if not (after_delete == before - 1 and after_undo == before):
            raise BridgeCommandError(
                f"counts before={before} delete={after_delete} undo={after_undo}",
                cmd="delete_element/undo",
                params={"id": made["id"]},
            )
        return f"object count {before}->{after_delete} undo->{after_undo}"

    check("delete/undo", delete_round_trip)

    # --- cleanup: delete everything we made ---
    deleted = 0
    for eid in created_ids:
        try:
            if bridge.request("delete_element", id=eid).get("deleted"):
                deleted += 1
        except BridgeError:
            pass
    print(f"\nCleaned up {deleted}/{len(created_ids)} created elements.")
    print(f"\n{passed} passed, {failed} failed.")
    if not dirty:
        print(
            "(Terrain, cave and water edits were skipped: they change map-wide "
            "state that this script cannot cleanly restore. Re-run with --dirty "
            "on a throwaway map to cover them.)"
        )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
