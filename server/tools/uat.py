#!/usr/bin/env python3
"""Run live acceptance checks against an explicitly named disposable map.

Use --help for test groups and map selection. These checks can modify the map."""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

from disposable import NotDisposable, require_disposable_map

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import uat_harness  # noqa: E402
from uat_harness import (  # noqa: E402
    COLORABLE_ASSET_SCAN_LIMIT,
    Uat,
    pixel_difference,
    vanilla_assets,
    vanilla_colourable_assets,
)

from battlemap_mcp.errors import BridgeCommandError, BridgeUnavailableError  # noqa: E402

GROUPS: dict[str, list] = {}


def group(name):
    def deco(fn):
        GROUPS.setdefault(name, []).append(fn)
        return fn

    return deco


# ---------------------------------------------------------------- inspection
@group("inspect")
def inspect(u: Uat) -> None:
    def ping():
        r = u.c.request("ping")
        assert r["pong"] is True, r
        return f"protocol {r['protocol']}, engine {r['engine']['string']}"

    u.check("ping reports protocol and engine", ping)

    def status():
        s = u.c.request("get_status")
        for k in ("map_open", "map_size_woxels", "map_center", "counts", "layers"):
            assert k in s, f"get_status missing {k}"
        assert set(s["layers"]) >= {"water", "cave", "floor_shapes", "tile_cells"}
        return f"{s['map_size_woxels']}, layers reported"

    u.check("get_status reports counts AND layers", status)

    def categories():
        r = u.c.request("list_asset_categories")
        assert "populated" in r and "counts" in r, f"no counts: {r}"
        assert r["populated"], "no category has any assets"
        # regression: names alone hid that "Patterns" ships empty in vanilla
        empty = [c["name"] for c in r["counts"] if c["count"] == 0]
        return f"{len(r['populated'])} populated, empty: {empty}"

    u.check("list_asset_categories reports counts, not just names", categories)

    def assets():
        r = u.c.request("list_assets", category="Objects", search="", limit=5)
        assert len(r["assets"]) == 5, "limit not honoured"
        assert r["matched"] == r["total"], "empty search should match everything"
        f = u.c.request("list_assets", category="Objects", search="barrel", limit=100)
        assert f["matched"] < r["total"], "search did not filter"
        assert all("barrel" in a.lower() for a in f["assets"]), "search returned non-matches"
        return f"{r['total']} objects, {f['matched']} match 'barrel'"

    u.check("list_assets: limit, search and totals", assets)

    # regression: an unknown category threw KeyNotFoundException INSIDE Dungeondraft
    # before the tidy error was returned. The log check is the real assertion.
    u.rejects(
        "list_assets rejects an unknown category", "list_assets", category="NoSuchCategory", limit=5
    )
    u.rejects("list_elements rejects an unknown kind", "list_elements", kind="bogus")
    u.rejects("get_element rejects a missing id", "get_element", id=999999)
    u.rejects("list_tool_controls rejects an unknown tool", "list_tool_controls", tool="NoSuchTool")
    # regression: an unknown set silently returned the CURRENT set's prefabs
    u.rejects("list_prefabs rejects an unknown set", "list_prefabs", set="NoSuchSet")

    def terrain_read():
        t = u.c.request("get_terrain", samples=4)
        assert len(t["weights"]) == 4 and len(t["weights"][0]) == 4, "grid shape"
        assert all(len(p) == 4 for row in t["weights"] for p in row), "4 channels"
        lo = u.c.request("get_terrain", samples=1)["samples"]
        hi = u.c.request("get_terrain", samples=999)["samples"]
        assert lo == 2 and hi == 64, f"samples not clamped: {lo}, {hi}"
        return f"splat {t['splat_size']}, samples clamp 2..64"

    u.check("get_terrain: grid shape and sample clamps", terrain_read)

    # regression: a Dictionary property hung the editor at 100% CPU


# -------------------------------------------------------------------- create
@group("create")
def create(u: Uat) -> None:
    obj = u.asset("Objects", "barrel") or u.asset("Objects")
    if not obj:
        u.skipped.append(("create group", "no Objects assets"))
        return

    def place():
        r = u.c.request(
            "place_object", asset=obj, x=u.cx, y=u.cy, scale=2.5, rotation=45.0, sorting=0
        )
        e = u.c.request("get_element", id=r["id"])
        assert abs(e["scale"] - 2.5) < 0.01, f"scale {e['scale']}"
        assert abs(e["rotation"] - 45.0) < 0.1, f"rotation {e['rotation']}"
        assert e["position"] == [u.cx, u.cy], f"position {e['position']}"
        u.c.request("delete_element", id=r["id"])
        return "scale, rotation and position all read back"

    u.check("place_object applies scale/rotation/position", place)

    def modulate_refused():
        before = u.c.request("get_status")
        for command, params in (
            ("place_object", {"asset": obj, "modulate": "#3366ff"}),
            ("place_objects", {"objects": [{"asset": obj}, {"asset": obj, "modulate": "#3366ff"}]}),
        ):
            try:
                u.c.request(command, **params)
            except BridgeCommandError as exc:
                assert "modulate" in str(exc) and "saving" in str(exc), str(exc)
            else:
                raise AssertionError(f"{command} accepted a nonpersistent tint")
            after = u.c.request("get_status")
            assert after["counts"] == before["counts"], "rejected tint changed map counts"
            assert after["undo_depth"] == before["undo_depth"], "rejected tint changed history"
        return "single and valid-first batch refused without edits or history"

    u.check("placement refuses nonpersistent modulate before edits", modulate_refused)

    # regression: sorting accepted ANY int; a bad hex fell back to white and
    # still reported modulate_applied
    u.rejects(
        "place_object rejects out-of-range sorting",
        "place_object",
        asset=obj,
        x=u.cx,
        y=u.cy,
        sorting=9,
    )
    u.rejects(
        "place_object rejects a malformed modulate",
        "place_object",
        asset=obj,
        x=u.cx,
        y=u.cy,
        modulate="nothex",
    )
    u.rejects(
        "place_object rejects an unknown asset",
        "place_object",
        asset="res://nope/missing.png",
        x=u.cx,
        y=u.cy,
    )

    wall = u.asset("Walls")
    if wall:

        def walls():
            r = u.c.request(
                "draw_wall",
                points=[[u.cx - 400, u.cy - 400], [u.cx + 400, u.cy - 400]],
                asset=wall,
                color="#ff0000",
                shadow=False,
            )
            e = u.c.request("get_element", id=r["id"])
            assert e.get("color") == "#ff0000", f"color {e.get('color')}"
            assert e.get("shadow") is False, f"shadow {e.get('shadow')}"
            pts = e.get("points") or []
            assert len(pts) == 2, f"expected 2 points, got {len(pts)}"
            # regression: wall points are WORLD coordinates
            assert abs(pts[0][0] - (u.cx - 400)) < 2, f"points not world-space: {pts[0]}"
            u.c.request("delete_element", id=r["id"])
            return f"colour, shadow and world-space points: {pts[0]}"

        u.check("draw_wall: colour, shadow, world-space geometry", walls)
        u.rejects(
            "draw_wall rejects a single point", "draw_wall", points=[[u.cx, u.cy]], asset=wall
        )

    path = u.asset("Paths")
    if path:

        def paths():
            r = u.c.request(
                "draw_path",
                points=[[u.cx - 500, u.cy + 500], [u.cx, u.cy + 600], [u.cx + 500, u.cy + 500]],
                asset=path,
            )
            e = u.c.request("get_element", id=r["id"])
            pts = e.get("points") or []
            # regression: path points came back node-LOCAL while walls were world
            near = [p for p in pts if abs(p[0] - u.cx) < 3000 and abs(p[1] - u.cy) < 3000]
            assert len(near) == len(pts), f"points not world-space: {pts[0]}"
            u.c.request("delete_element", id=r["id"])
            return f"{len(pts)} interpolated points, all world-space"

        u.check("draw_path returns world-space geometry", paths)

    def lights():
        r = u.c.request(
            "add_light", x=u.cx - 600, y=u.cy, color="#ff8800", energy=2.5, range=3.0, shadows=False
        )
        e = u.c.request("get_element", id=r["id"])
        # regression: lights reported NONE of these
        assert e.get("color") == "#ff8800", f"color {e.get('color')}"
        assert abs(e.get("energy", 0) - 2.5) < 0.01, f"energy {e.get('energy')}"
        assert e.get("shadows") is False, f"shadows {e.get('shadows')}"
        u.c.request("delete_element", id=r["id"])
        return "colour, energy, range and shadows all readable"

    u.check("add_light properties are readable", lights)

    def scatter():
        rect = [u.cx + 1500, u.cy + 1500, 600, 600]
        a = u.c.request(
            "scatter_objects",
            assets=[obj],
            rect=rect,
            count=6,
            seed=99,
            scale_min=0.5,
            scale_max=2.0,
        )
        els = {
            e["id"]: e for e in u.c.request("list_elements", kind="objects", limit=500)["elements"]
        }
        got = [(round(els[i]["position"][0], 1), round(els[i]["scale"], 2)) for i in a["ids"]]
        for i in a["ids"]:
            u.c.request("delete_element", id=i)
        time.sleep(0.4)
        b = u.c.request(
            "scatter_objects",
            assets=[obj],
            rect=rect,
            count=6,
            seed=99,
            scale_min=0.5,
            scale_max=2.0,
        )
        els = {
            e["id"]: e for e in u.c.request("list_elements", kind="objects", limit=500)["elements"]
        }
        again = [(round(els[i]["position"][0], 1), round(els[i]["scale"], 2)) for i in b["ids"]]
        for i in b["ids"]:
            u.c.request("delete_element", id=i)
        assert got == again, "same seed did not reproduce"
        assert all(0.5 <= s <= 2.0 for _, s in got), f"scale out of range: {got}"
        return f"seed 99 reproduced {len(got)} placements exactly"

    u.check("scatter_objects: seed reproduces, ranges respected", scatter)

    def colourable_is_discoverable():
        carpets = u.c.request(
            "list_assets",
            category="Objects",
            search="carpet",
            limit=COLORABLE_ASSET_SCAN_LIMIT,
            vanilla_only=True,
        )
        assert carpets["colorable_scanned"], "the scan was skipped; the rest proves nothing"
        vanilla_carpets = vanilla_colourable_assets(carpets["assets"], carpets["colorable"])
        assert vanilla_carpets, f"no vanilla carpet reported colourable: {carpets['assets'][:3]}"

        # Optional packs may contain colourable barrels. Restrict this negative
        # assertion to Dungeondraft's own barrel assets instead of treating an
        # arbitrary search result as a stable fixture.
        plain = u.c.request(
            "list_assets",
            category="Objects",
            search="barrel",
            limit=COLORABLE_ASSET_SCAN_LIMIT,
            vanilla_only=True,
        )
        vanilla_barrels = vanilla_assets(plain["assets"])
        assert vanilla_barrels, f"no vanilla barrel found: {plain['assets']}"
        reported = vanilla_colourable_assets(plain["assets"], plain["colorable"])
        assert not set(vanilla_barrels).intersection(reported), (
            f"vanilla barrels reported colourable: {reported}"
        )

        # And placing one untinted says so, while it is still cheap to undo.
        warned = u.c.request("place_object", asset=vanilla_carpets[0], x=u.cx, y=u.cy)
        u.c.request("delete_element", id=warned["id"])
        assert warned.get("colorable") is True, f"no warning on an untinted colourable: {warned}"
        assert "RED" in str(warned.get("note", "")), f"warning does not say why: {warned}"

        quiet = u.c.request("place_object", asset=vanilla_barrels[0], x=u.cx, y=u.cy)
        u.c.request("delete_element", id=quiet["id"])
        assert "colorable" not in quiet, f"warned about a non-colourable asset: {quiet}"
        return f"{len(vanilla_carpets)} vanilla carpets colourable, vanilla barrels not"

    u.check("colourable assets are discoverable before placing", colourable_is_discoverable)

    u.rejects("add_text rejects an empty string", "add_text", text="   ", x=u.cx, y=u.cy)
    u.rejects(
        "add_portal rejects an unknown mount",
        "add_portal",
        asset=u.asset("Portals") or "x",
        x=u.cx,
        y=u.cy,
        mount="sideways",
    )

    def portal_collision_explains_itself():
        # regression: AddPortal refuses a point another portal already occupies
        # and returns null. The bridge reported that verbatim — "Wall.AddPortal
        # returned null" — which names an engine method the caller has never
        # heard of and says nothing about what to do. It cost a real debugging
        # session: the refusal looked geometric (it correlated with a segment's
        # midpoint) until the message was made to name the wall it snapped to,
        # at which point the wall turned out to be a leftover from an earlier
        # run that already had a portal at that exact point.
        wall_asset = u.asset("Walls")
        portal_asset = u.asset("Portals")
        x, y = u.cx + 2000, u.cy + 1200
        wall = u.c.request(
            "draw_wall",
            points=[[x - 400, y], [x + 400, y]],
            asset=wall_asset or "",
        )
        time.sleep(0.6)
        first = u.c.request("add_portal", asset=portal_asset, x=x, y=y)
        try:
            u.c.request("add_portal", asset=portal_asset, x=x, y=y)
            raise AssertionError("a second portal at the same point was accepted")
        except BridgeCommandError as exc:
            msg = str(exc)
            assert "already mounted" in msg, f"unexplained refusal: {msg}"
            assert str(first["id"]) in msg, f"refusal does not name the blocker: {msg}"
        # ... and moving along the wall works, which is what the message says.
        second = u.c.request("add_portal", asset=portal_asset, x=x + 200, y=y)
        u.c.request("delete_element", id=second["id"])
        u.c.request("delete_element", id=first["id"])
        u.c.request("delete_element", id=wall["id"])
        return "a blocked portal names the portal blocking it, and moving along the wall works"

    u.check(
        "add_portal explains a collision instead of returning null",
        portal_collision_explains_itself,
        needs_dirty=True,
    )


# ------------------------------------------------------------------- modify
@group("modify")
def modify(u: Uat) -> None:
    obj = u.asset("Objects", "barrel") or u.asset("Objects")
    if not obj:
        return
    made = u.c.request("place_object", asset=obj, x=u.cx - 1500, y=u.cy - 1500)["id"]

    def modulate_refused():
        before = u.c.request("get_element", id=made)
        depth = u.c.request("get_status")["undo_depth"]
        try:
            u.c.request("modify_object", id=made, shadow=False, scale=2, modulate="#00ff00")
        except BridgeCommandError as exc:
            assert "modulate" in str(exc) and "saving" in str(exc), str(exc)
        else:
            raise AssertionError("modify_object accepted a nonpersistent tint")
        assert u.c.request("get_element", id=made) == before, "refusal partially modified object"
        assert u.c.request("get_status")["undo_depth"] == depth, "refusal changed history"
        return "combined shadow/scale/tint request refused without changes"

    u.check("modify_object refuses nonpersistent modulate before edits", modulate_refused)

    # regression: reported success while the object kept its colour
    u.rejects(
        "modify_object refuses colour on a placed object", "modify_object", id=made, color="#ff0000"
    )

    def duplicate_fidelity():
        u.c.request("modify_object", id=made, shadow=False, scale=2.0)
        d = u.c.request("duplicate_object", id=made, dx=200.0)
        e = u.c.request("get_element", id=d["id"])
        assert e.get("modulate") in (None, "#ffffff"), f"unexpected tint {e.get('modulate')!r}"
        assert e.get("shadow") is False, f"shadow {e.get('shadow')}"
        assert abs(e["scale"] - 2.0) < 0.01, f"scale {e['scale']}"
        u.c.request("delete_element", id=d["id"])
        return "copy retains neutral tint, shadow and scale"

    u.check("duplicate_object copies appearance, not just transform", duplicate_fidelity)

    def move():
        u.c.request("move_element", id=made, x=u.cx - 1200, y=u.cy - 1200)
        e = u.c.request("get_element", id=made)
        assert e["position"] == [u.cx - 1200, u.cy - 1200], e["position"]
        return f"moved to {e['position']}"

    u.check("move_element moves exactly", move)

    def selection():
        u.c.request("select_elements", ids=[made, 999999])
        r = u.c.request("select_elements", ids=[made, 999999])
        assert r["selected"] == 1, f"selected {r['selected']}"
        # regression: only a count was reported
        assert r.get("missing") == [999999], f"missing {r.get('missing')}"
        cleared = u.c.request("clear_selection")
        # regression: guarded on ActiveToolName, so this NEVER cleared
        assert cleared["cleared"] is True, f"clear_selection said {cleared}"
        return "missing ids reported; selection actually cleared"

    u.check("select_elements reports missing; clear_selection clears", selection)

    def delete_undo():
        before = u.c.request("get_status")["counts"]["objects"]
        original = u.c.request("get_element", id=made)
        u.c.request("delete_element", id=made)
        time.sleep(0.35)  # removal is deferred to the next frame
        after = u.c.request("get_status")["counts"]["objects"]
        assert after == before - 1, f"{before} -> {after}"
        u.c.request("undo")
        time.sleep(0.35)
        back = u.c.request("get_status")["counts"]["objects"]
        assert back == before, f"undo did not restore: {back} vs {before}"
        restored = u.c.request("get_element", id=made)
        assert restored == original, f"undo changed the restored object: {original} -> {restored}"
        return f"{before} -> {after} -> {back}"

    u.check("delete_element is undoable", delete_undo)
    try:
        u.c.request("delete_element", id=made)
    except Exception:
        pass


# ------------------------------------------------------------------ terrain
@group("terrain")
def terrain(u: Uat) -> None:
    terr = u.asset("Terrain", "limestone") or u.asset("Terrain")
    if not terr:
        u.skipped.append(("terrain group", "no Terrain assets"))
        return

    def weight(x, y):
        t = u.c.request("get_terrain", rect=[x - 150, y - 150, 300, 300], samples=3)
        return t["weights"][1][1]

    def channels():
        # regression: docs claimed channels were slots 1-4; they are slots 0-3.
        # Slot 0 was originally skipped here, which let four accounts of these
        # four numbers disagree for months — see docs/level-api-ground-truth.md.
        # It does NOT behave like 1-3: it is the unclaimed remainder rather than
        # a paintable channel, so it gets its own assertion rather than being
        # folded into the loop as if the rule were uniform.
        for slot in (1, 2, 3):
            u.c.request("set_terrain_slot", asset=terr, slot=slot)
            x = u.cx + 1000 + slot * 500
            u.c.request("paint_terrain", slot=slot, x=x, y=u.cy - 1500, radius=200.0, rate=1.0)
            w = weight(x, u.cy - 1500)
            assert w[slot] > 0.8, f"slot {slot} landed in channel {w.index(max(w))}: {w}"

        # Slot 0: the engine accepts the paint and reports pixels touched, and
        # the readback does not move. Both halves are asserted, because "the
        # call did nothing" and "the call was rejected" are different findings
        # and only the first is what was measured.
        x0 = u.cx + 1000
        before = weight(x0, u.cy - 2200)
        assert before == [1.0, 0.0, 0.0, 0.0], f"slot-0 probe point is not blank: {before}"
        u.c.request("set_terrain_slot", asset=terr, slot=0)
        r = u.c.request("paint_terrain", slot=0, x=x0, y=u.cy - 2200, radius=200.0, rate=1.0)
        assert r["pixels"] > 0, f"slot 0 paint was not accepted at all: {r}"
        after = weight(x0, u.cy - 2200)
        assert after == before, (
            f"slot 0 moved the readback {before} -> {after}; it is documented "
            f"everywhere as the unpaintable remainder of channels 1-3"
        )
        return "slot N paints channel N for N in 1-3; slot 0 is the unpaintable remainder"

    u.check("terrain slots map to channels 0-3", channels, needs_dirty=True)

    def high_slots():
        u.c.request("set_terrain_slot", asset=terr, slot=4)
        r = u.c.request(
            "paint_terrain", slot=4, x=u.cx - 1500, y=u.cy - 1500, radius=200.0, rate=1.0
        )
        assert r["pixels"] > 0, f"nothing painted: {r}"
        return f"slot 4 painted {r['pixels']} px (second splat image)"

    u.check("terrain slots 4-7 work (second splat image)", high_slots, needs_dirty=True)

    def rate_blend():
        x, y = u.cx - 2200, u.cy + 1800
        rect = [x - 150, y - 150, 300, 300]
        # Reset the region first. Blending is cumulative, so running this case
        # twice in one Dungeondraft session took slot 3 to 0.5 then 0.75 and
        # failed on the second run — a test that only passes once is not a
        # regression test.
        u.c.request("fill_region", rect=rect, slot=0, asset=terr, rate=1.0)
        base = weight(x, y)
        assert abs(base[3]) < 0.05, f"region not reset: {base}"
        u.c.request("fill_region", rect=rect, slot=3, asset=terr, rate=0.5)
        w = weight(x, y)
        assert abs(w[3] - 0.5) < 0.15, f"rate 0.5 gave {w}"
        return f"reset -> rate 0.5 -> {w}"

    u.check("fill_region rate produces a partial blend", rate_blend, needs_dirty=True)

    u.rejects(
        "set_terrain_slot rejects an out-of-range slot", "set_terrain_slot", asset=terr, slot=99
    )
    u.rejects("fill_region rejects neither rect nor points", "fill_region", slot=1)


# ------------------------------------------------------------------- layers
@group("layers")
def layers(u: Uat) -> None:
    def floors():
        # floor_shapes is NOT "one per add_floor call". Dungeondraft
        # re-tessellates the floor polygons, so a single call moved the count by
        # +1, +3 and even -1 in a row, and overlapping shapes merge to no change
        # at all. Asserting `after > before` on a shared map therefore fails for
        # reasons that have nothing to do with add_floor — it read as
        # "floor_shapes 28 -> 28, add_floor is broken" while add_floor was fine.
        #
        # Inverting over the whole map erases every shape, which gives an exact
        # starting point and leaves the map clean for the next run.
        w, h = u.c.request("get_status")["map_size_woxels"]
        whole = [0, 0, w, h]

        def count():
            return u.c.request("get_status")["layers"]["floor_shapes"]

        u.c.request("add_floor", rect=whole, invert=True)
        assert count() == 0, f"inverting the whole map left {count()} shape(s)"
        rect = [u.cx + 2000, u.cy - 2000, 600, 500]
        assert u.c.request("add_floor", rect=rect).get("added") is True, "add_floor refused"
        drawn = count()
        assert drawn > 0, "add_floor reported success but drew nothing"
        r = u.c.request("add_floor", rect=[rect[0] + 100, rect[1] + 100, 200, 200], invert=True)
        assert r.get("inverted") is True, f"invert not reported: {r}"
        holed = count()
        assert holed > 0, "cutting a hole erased the whole floor"
        u.c.request("add_floor", rect=whole, invert=True)  # leave it as we found it
        return f"0 -> {drawn} drawn -> {holed} with a hole -> 0 again"

    u.check("add_floor draws and inverts", floors, needs_dirty=True)

    def water():
        pts = [
            [u.cx - 2500, u.cy - 2500],
            [u.cx - 1900, u.cy - 2500],
            [u.cx - 1900, u.cy - 1900],
            [u.cx - 2500, u.cy - 1900],
        ]
        u.c.request("add_water", points=pts)
        assert u.c.request("get_status")["layers"]["water"] is True, "water layer not set"
        style = u.c.request("set_water_style", deep_color="#3f9fdc", shallow_color="#8fd3f0")
        assert u.c.request("get_status")["layers"]["water"] is True, "styling erased the water"
        assert style.get("bodies", 0) >= 1, f"no bodies read back: {style}"
        assert style.get("deep_color") == "#3f9fdc", f"bodies not restyled: {style}"
        u.c.request("add_water", points=pts, invert=True)
        return f"drawn, styled ({style.get('bodies')} bodies #3f9fdc) and still drawn, erased"

    u.check("add_water draws, styles and inverts", water, needs_dirty=True)

    def caves():
        u.c.request("dig_cave", points=[[u.cx + 2500, u.cy + 2000]], radius=250.0)
        assert u.c.request("get_status")["layers"]["cave"] is True, "cave layer not set"
        u.c.request("clear_caves")
        time.sleep(0.4)
        assert u.c.request("get_status")["layers"]["cave"] is False, "clear_caves left a cave"
        return "dug, then cleared"

    u.check("dig_cave and clear_caves", caves, needs_dirty=True)

    u.rejects(
        "add_water rejects an open outline", "add_water", points=[[u.cx, u.cy], [u.cx + 100, u.cy]]
    )
    u.rejects("add_floor rejects neither shape", "add_floor")


# ------------------------------------------------------------ camera/capture
@group("capture")
def capture(u: Uat) -> None:
    def shapes_match():
        a = u.c.request("fit_elements")
        ids = [e["id"] for e in u.c.request("list_elements", kind="objects", limit=3)["elements"]]
        if not ids:
            made = u.c.request("place_object", asset=u.asset("Objects"), x=u.cx, y=u.cy)["id"]
            ids = [made]
        b = u.c.request("fit_elements", ids=ids)
        # regression: the two paths returned different response shapes
        assert sorted(a) == sorted(b), f"{sorted(a)} vs {sorted(b)}"
        return f"both paths return {sorted(a)}"

    u.check("fit_elements returns one shape either way", shapes_match)

    def camera():
        u.c.request("set_camera", x=u.cx, y=u.cy, zoom=5.0)
        g = u.c.request("get_camera")
        assert g["position"] == [u.cx, u.cy] and abs(g["zoom"] - 5.0) < 0.01, g
        return f"pos {g['position']}, zoom {g['zoom']}"

    u.check("set_camera and get_camera agree", camera)

    def shot():
        r = u.c.request("screenshot")
        p = pathlib.Path(r["path"])
        assert p.exists() and p.stat().st_size > 1000, f"no file at {p}"
        return f"{p.name}, {p.stat().st_size // 1024} KB"

    u.check("screenshot writes a real file", shot)

    def trace_shows():
        import importlib
        import tempfile

        from PIL import Image

        def magenta(path) -> int:
            with Image.open(path) as image:
                raw = image.convert("RGB").tobytes()
            return sum(
                1
                for i in range(0, len(raw), 3)
                if raw[i] - raw[i + 1] > 100 and raw[i + 2] - raw[i + 1] > 100
            )

        u.c.request("set_camera", x=u.cx, y=u.cy, zoom=2.0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            source = pathlib.Path(handle.name)
        Image.new("RGB", (768, 768), (255, 0, 255)).save(source)
        cleared: dict = {}
        try:
            baseline = magenta(u.c.request("screenshot")["path"])
            shown = u.c.request("set_trace_image", path=str(source), opacity=1.0, center=True)
            assert shown.get("visible") is True, f"loaded but not visible: {shown}"
            assert shown.get("image_size") == [768, 768], f"image not loaded: {shown}"
            lit = magenta(u.c.request("screenshot")["path"])
            # A guide must not reach a render. Dungeondraft's exporter hides it.
            server = importlib.import_module("battlemap_mcp.server")
            _, caption = server.export_map(ppi=16, format="png")
            exported = magenta(caption.split("saved: ", 1)[1].split("\n", 1)[0])
            assert exported == 0, f"{exported} trace pixels in an export"
            relit = magenta(u.c.request("screenshot")["path"])
            assert relit > baseline + 2000, f"the trace did not come back after an export: {relit}"
            cleared = u.c.request("set_trace_image", clear=True)
            assert cleared.get("visible") is False, f"cleared but still visible: {cleared}"
            after = magenta(u.c.request("screenshot")["path"])
        finally:
            if not cleared:
                # A trace left loaded shows in every later screenshot and export.
                u.c.request("set_trace_image", clear=True)
            source.unlink(missing_ok=True)
        assert lit > baseline + 2000, (
            f"reported visible, but {lit} trace pixels on screen ({baseline} before)"
        )
        assert after <= baseline, f"{after} trace pixels remain after clear ({baseline} before)"
        return (
            f"trace pixels on screen: {baseline} -> {lit} loaded -> {relit} after an export "
            f"(0 in it) -> {after} cleared"
        )

    u.check("a loaded trace image shows, and clear hides it", trace_shows, needs_dirty=True)

    def exports():
        import base64
        import importlib

        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        server = importlib.import_module("battlemap_mcp.server")
        magic = {"png": b"\x89PNG", "jpg": b"\xff\xd8", "webp": b"RIFF"}
        for fmt, sig in magic.items():
            # The image for the model, then a caption naming the file for the
            # person, since clients fold images inside the tool call (C2).
            img, caption = server.export_map(ppi=16, format=fmt)
            content = img.to_image_content()
            head = base64.b64decode(content.data, validate=True)[:4]
            assert head.startswith(sig), f"{fmt}: got {head!r}"
            expected_mime = "image/jpeg" if fmt == "jpg" else f"image/{fmt}"
            assert content.mime_type == expected_mime, content.mime_type
            named = pathlib.Path(caption.split("saved: ", 1)[1].split("\n", 1)[0])
            assert named.is_file(), f"{fmt}: caption names a missing file {named}"
            assert named.read_bytes()[:4].startswith(sig), f"{fmt}: named file is not {fmt}"
        return "png/jpg/webp carry the right magic bytes, and each caption names that file"

    u.check("export_map produces real image formats", exports, needs_dirty=True)

    def export_ppi(pixels: int) -> tuple[int, int]:
        w, h = u.c.request("get_status")["map_size_woxels"]
        longest = max(w, h) / 256
        return int(pixels // longest), int(16384 // longest)

    def start_export(ppi: int) -> dict:
        return u.c.request("export_map", name=f"uat-op-{time.time_ns()}.png", ppi=ppi)

    def settle(op: dict, limit: float = 120) -> dict:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            try:
                status = u.c.request("get_operation", operation_id=op["operation_id"])
            except BridgeUnavailableError:
                # The final encode blocks the thread that serves this socket.
                time.sleep(0.25)
                continue
            if status["state"] != "rendering":
                return status
            time.sleep(0.25)
        raise AssertionError(f"{op['operation_id']} never settled")

    def export_operation():
        from PIL import Image

        ppi, _ = export_ppi(4000)
        op = start_export(ppi)
        assert op["state"] == "rendering" and op["operation_id"], op
        status = settle(op)
        assert status["state"] == "completed", status
        assert status["chunks_rendered"] > 0, f"no camera stops observed: {status}"
        with Image.open(status["path"]) as image:
            image.load()
            assert list(image.size) == status["pixels"], (image.size, status["pixels"])
        assert u.c.request("get_status")["export"] is None, "export still reported in flight"
        return (
            f"{status['pixels'][0]}x{status['pixels'][1]} px, "
            f"{status['chunks_rendered']} chunks, {status['elapsed_ms']} ms"
        )

    u.check("export_map is an operation that settles with a real image", export_operation)

    def export_is_exclusive():
        ppi, _ = export_ppi(6000)
        camera_before = u.c.request("get_camera")
        op = start_export(ppi)
        refused = []
        for cmd, params in (
            ("export_map", {"name": f"uat-op-overlap-{time.time_ns()}.png", "ppi": 16}),
            ("set_camera", {"x": u.cx + 500, "y": u.cy + 500, "zoom": 1.0}),
            ("screenshot", {"name": f"uat-op-shot-{time.time_ns()}.png"}),
            ("add_light", {"x": u.cx, "y": u.cy}),
        ):
            try:
                u.c.request(cmd, **params)
            except BridgeCommandError as exc:
                assert "still rendering" in str(exc), f"{cmd}: unexplained refusal {exc}"
                refused.append(cmd)
            else:
                raise AssertionError(f"{cmd} was accepted while export rendered")
        in_flight = u.c.request("get_status")["export"]
        assert in_flight and in_flight["operation_id"] == op["operation_id"], in_flight
        guarded = settle(op)
        assert guarded["state"] == "completed", guarded
        assert u.c.request("get_camera") == camera_before, "export left the camera moved"
        solo = settle(start_export(ppi))
        box = pixel_difference(guarded["path"], solo["path"])
        assert box is None, f"guarded export differs from a solo render in {box}"
        return f"refused {', '.join(refused)}; image identical to a solo render"

    u.check("an export refuses what would corrupt it", export_is_exclusive, needs_dirty=True)

    def oversize_export():
        _, most = export_ppi(0)
        try:
            u.c.request("export_map", name=f"uat-op-big-{time.time_ns()}.png", ppi=most + 1)
        except BridgeCommandError as exc:
            msg = str(exc)
            assert "16384" in msg and f"{most} ppi" in msg, f"refusal lacks the limit: {msg}"
        else:
            raise AssertionError(f"{most + 1} ppi was accepted")
        assert u.c.request("get_operation")["current"] is None, "an operation started anyway"
        return f"{most + 1} ppi refused; this map allows {most}"

    u.check("an export Dungeondraft would abandon is refused up front", oversize_export)


# ---------------------------------------------------------------- generator
@group("generator")
def generator(u: Uat) -> None:
    def dials():
        d = u.c.request("generator_options")
        assert "Boundary" in d["dials"], d["dials"].keys()
        b = d["dials"]["Boundary"]
        assert b["kind"] == "number" and b["max"] == 16, b
        return f"{d['design']}: {sorted(d['dials'])}"

    u.check("generator_options lists the current design's dials", dials)

    u.rejects(
        "generator_options rejects an out-of-range value",
        "generator_options",
        name="Complexity",
        value=5.0,
    )
    # regression: setting a picker looked like it worked but Enable() discarded it
    u.rejects(
        "generator_options refuses the texture pickers", "generator_options", name="Wall", value=1
    )

    def design_switch():
        u.c.request("generate_dungeon", design="Cave")
        time.sleep(2.0)
        assert u.c.request("get_status")["layers"]["cave"] is True, "Cave produced no cave"
        d = u.c.request("generator_options")
        # regression: Cave hides the pickers; listing them advertised dials that do nothing
        assert "Wall" not in d["dials"], f"Cave should hide pickers: {sorted(d['dials'])}"
        u.c.request("generate_dungeon", design="Dungeon")
        time.sleep(2.0)
        assert u.c.request("get_status")["layers"]["cave"] is False, "Dungeon left a cave"
        return "Cave and Dungeon both generate; pickers hidden on Cave"

    u.check("generate_dungeon honours the design", design_switch, needs_dirty=True)
    u.rejects("generate_dungeon rejects an unknown design", "generate_dungeon", design="Swamp")


# ---------------------------------------------------------- levels / map I/O
@group("levels")
def levels(u: Uat) -> None:
    def roundtrip():
        start = u.c.request("list_levels")
        made = u.c.request("add_level", label="uat-temp")
        assert made["level_count"] == len(start["levels"]) + 1, made
        u.c.request("set_level", id=start["current_level_id"])
        u.c.request("delete_level", id=made["id"])
        end = u.c.request("list_levels")
        assert len(end["levels"]) == len(start["levels"]), f"{start} -> {end}"
        return "added, switched, removed; map unchanged"

    u.check("levels: add, switch by id, delete", roundtrip, needs_dirty=True)

    def multi_level_coherent():
        made = u.c.request("add_level", label="uat-probe")
        time.sleep(1.0)
        try:
            levels = u.c.request("list_levels")
            assert levels["current_index"] >= 0, (
                f"current_index is a sentinel, not a position: {levels}"
            )
            for lv in levels["levels"]:
                u.c.request("set_level", id=lv["id"])
                time.sleep(0.8)
                st = u.c.request("get_status")
                assert st["level_id"] == lv["id"], (
                    f"asked for level {lv['id']} ({lv['label']}), "
                    f"get_status reports level_id {st['level_id']}"
                )
                back = u.c.request("list_levels")
                assert back["current_level_id"] == lv["id"], (
                    f"asked for level {lv['id']}, "
                    f"list_levels reports current {back['current_level_id']}"
                )
                seen = u.c.request("list_elements", kind="objects", limit=500)["count"]
                assert seen == st["counts"]["objects"], (
                    f"level {lv['id']}: get_status counts {st['counts']['objects']} "
                    f"objects, list_elements sees {seen}"
                )
            return f"{len(levels['levels'])} levels, all three sources agree"
        finally:
            u.c.request("set_level", id=0)
            time.sleep(0.5)
            u.c.request("delete_level", id=made["id"])
            time.sleep(0.5)

    u.check(
        "levels: multi-level status is coherent",
        multi_level_coherent,
        needs_dirty=True,
    )

    u.rejects("set_level rejects an unknown id", "set_level", id=4242)

    # regression: a level change frees the level's node tree, taking the UI
    # tool's Preview with it. Editor._Process kept ticking that tool, which
    # wrote to the disposed Prop every frame — ObjectDisposedException forever,
    # and the bridge stopped answering. It only reproduces when the UI actually
    # has a tool selected, which a freshly created map does not.
    def level_change_keeps_the_tool_alive():
        u.c.request("select_tool", tool="ObjectTool")
        made = u.c.request("add_level", label="uat-tool-survival")["id"]
        time.sleep(0.5)
        u.c.request("set_level", id=made)
        time.sleep(0.5)
        u.c.request("delete_level", id=made)
        time.sleep(1.0)  # several frames of Editor._Process
        for i in range(3):
            assert u.c.request("ping")["pong"] is True, f"bridge died {i + 1} call(s) later"
        # The tool must still be usable, not merely not-crashing.
        obj = u.asset("Objects", "barrel") or u.asset("Objects")
        r = u.c.request("place_object", asset=obj, x=u.cx, y=u.cy)
        u.c.request("delete_element", id=r["id"])
        return "add/set/delete level with ObjectTool selected, tool still places"

    u.check(
        "a level change leaves the UI's tool usable",
        level_change_keeps_the_tool_alive,
        needs_dirty=True,
    )
    u.rejects("delete_level refuses the only level", "delete_level", id=0)
    # regression: a nonexistent path returned {"opening": ..., "async": true}
    u.rejects(
        "open_map rejects a nonexistent path",
        "open_map",
        path="/tmp/definitely-not-a-map.dungeondraft_map",
    )

    def save_directory():
        r = u.c.request("get_save_directory")
        assert "effective" in r and "configured" in r, r
        # Falls back to Dungeondraft's own map directory, so no setup is needed
        assert r["effective"], "no effective save directory at all"
        # regression: Dungeondraft returns this path with backslash separators
        # on every platform, so the fallback resolved to something unusable off
        # Windows. Normalised now, and only offered when it really exists.
        assert "\\" not in r["effective"], f"unnormalised path: {r['effective']}"
        assert r["exists"], f"save directory does not exist: {r['effective']}"
        # With nothing configured it should be our own subdirectory, created on
        # demand, rather than the user's Documents root.
        if not r["configured"]:
            assert r["effective"].endswith("battlemap-mcp"), (
                f"default is not the bridge's own folder: {r['effective']}"
            )
        return f"{r['source']}: {r['effective']}"

    u.check("get_save_directory falls back sensibly", save_directory)

    def save_round_trip():
        asset = u.asset("Objects", "barrel") or u.asset("Objects")
        for i in range(3):
            u.c.request("place_object", asset=asset, x=u.cx + i * 300, y=u.cy)
        u.c.request("add_light", x=u.cx, y=u.cy - 600)
        u.c.request("draw_wall", points=[[u.cx - 900, u.cy - 900], [u.cx - 300, u.cy - 900]])
        time.sleep(2.0)
        before = u.c.request("get_status")["counts"]
        name = f"uat-roundtrip-{int(time.time())}.dungeondraft_map"
        home = u.original_map_file
        saved = u.c.request("save_map", filename=name)
        u.made_file(saved["path"])
        for _ in range(45):
            time.sleep(1.0)
            state = u.c.request("get_status")["saving"]
            if not state["in_flight"]:
                break
        assert not state["in_flight"], (
            f"save never finished: {state} — a save that dies mid-flight leaves "
            f"every write refused until the stale guard expires"
        )
        assert state["saves_seen"] >= 1, f"OnSaveEnd never fired: {state}"
        try:
            u.c.request("open_map", path=saved["path"])
            time.sleep(16.0)
            after = u.c.request("get_status")["counts"]
            for kind in ("objects", "walls", "lights"):
                assert after[kind] == before[kind], (
                    f"{kind}: {before[kind]} placed, {after[kind]} came back from "
                    f"the file — the save reported success and dropped them"
                )
        finally:
            if home is not None:
                u.c.request("open_map", path=str(home))
                time.sleep(16.0)
        return f"3 objects, 1 wall, 1 light survived save and reload ({before})"

    u.check("a saved map holds what was placed in it", save_round_trip, needs_dirty=True)

    def every_created_kind_saves():
        made = []
        path_asset = u.asset("Paths")
        roof_asset = u.asset("Roofs")
        portal_asset = u.asset("Portals")
        if path_asset:
            pts = [[u.cx - 900, u.cy + 700], [u.cx - 300, u.cy + 800]]
            made.append(("path", u.c.request("draw_path", points=pts, asset=path_asset)["id"]))
        if roof_asset:
            ridge = [[u.cx + 300, u.cy + 700], [u.cx + 800, u.cy + 700]]
            r = u.c.request("add_roof", points=ridge, asset=roof_asset, width=200)
            made.append(("roof", r["id"]))
        made.append(("text", u.c.request("add_text", text="uat", x=u.cx, y=u.cy + 1100)["id"]))
        if portal_asset:
            r = u.c.request(
                "add_portal", asset=portal_asset, x=u.cx + 1500, y=u.cy + 1500, mount="free"
            )
            made.append(("freestanding portal", r["id"]))
        before = u.c.request("get_status")["saving"]["saves_seen"]
        name = f"uat-kinds-{int(time.time())}.dungeondraft_map"
        saved = u.c.request("save_map", filename=name)
        u.made_file(saved["path"])
        assert saved.get("started") is True, f"no save started: {saved}"
        assert u.wait_for_save(), "the save never finished — a created kind crashed it"
        after = u.c.request("get_status")["saving"]
        assert after["saves_seen"] > before, f"saves_seen did not rise: {after}"
        assert after.get("last_result") != "stale", f"the save went stale: {after}"
        for _kind, eid in made:
            u.c.request("delete_element", id=eid)
        return "saved with " + ", ".join(kind for kind, _ in made)

    u.check(
        "every kind the bridge creates survives a save", every_created_kind_saves, needs_dirty=True
    )

    def save_named():
        import time as _t

        name = f"uat-scratch-{int(_t.time())}"
        r = u.c.request("save_map", filename=name)
        assert r["path"].endswith(".dungeondraft_map"), r
        u.made_file(r["path"])
        assert u.wait_for_save(), "the first save never finished"
        # It becomes the open map, so a second save over it must be allowed —
        # that is the whole point: checkpointing progress as you go.
        again = u.c.request("save_map", filename=name)
        assert again["path"] == r["path"], f"{again} vs {r}"
        assert u.wait_for_save(), "the second save never finished"
        return f"saved and re-saved {name}.dungeondraft_map"

    u.check("save_map names a file and can re-save it", save_named, needs_dirty=True)

    def save_protects_others():
        # A file that exists and is NOT the open map must be refused.
        import time as _t

        other = f"uat-other-{int(_t.time())}"
        u.made_file(u.c.request("save_map", filename=other)["path"])  # becomes current
        assert u.wait_for_save(), "save did not finish"
        u.made_file(u.c.request("save_map", filename=f"{other}-b")["path"])  # current moves away
        assert u.wait_for_save(), "save did not finish"
        try:
            u.c.request("save_map", filename=other)
        except Exception as exc:
            assert "already exists" in str(exc), f"wrong refusal: {exc}"
            return "refused to overwrite a file it is not working on"
        raise AssertionError("overwrote an unrelated file")

    u.check("save_map refuses to clobber an unrelated map", save_protects_others, needs_dirty=True)

    u.wait_for_save()
    u.rejects(
        "save_map rejects a path in the filename",
        "save_map",
        filename="../../escape.dungeondraft_map",
    )

    def save_behaviour():
        try:
            r = u.c.request("save_map")
        except Exception as exc:
            # Expected on an unsaved map: saving would open a modal Save As
            # dialog, and a modal stops the mod being ticked — that froze this
            # very suite mid-run before the guard existed.
            assert "no path" in str(exc), f"unexpected refusal: {exc}"
            return "refused on an untitled map (a modal would freeze the bridge)"
        assert "had_path" in r or "in_flight" in r, f"save_map said {r}"
        assert u.wait_for_save(), "save did not finish"
        return f"saved to {r['path'].rsplit('/', 1)[-1]}"

    u.check("save_map refuses when it would open a modal", save_behaviour, needs_dirty=True)

    def resize():
        assert u.wait_for_save(), "a save was still running"
        st = u.c.request("get_status")["map_size_woxels"]
        w, h = int(st[0] // 256), int(st[1] // 256)
        u.c.request("set_map_size", width=w + 2, height=h + 2)
        grew = u.c.request("get_status")["map_size_woxels"]
        assert grew != st, f"size unchanged: {st}"
        splat = u.c.request("get_terrain", rect=[0, 0, 256, 256])["splat_size"]
        assert splat == [(w + 2) * 4, (h + 2) * 4], f"splat {splat} after resize to {w + 2}x{h + 2}"
        u.c.request("set_map_size", width=w, height=h)
        back = u.c.request("get_status")["map_size_woxels"]
        assert back == st, f"not restored: {back} vs {st}"
        return f"{st} -> {grew} (splat {splat}) -> restored"

    u.check("set_map_size resizes and restores", resize, needs_dirty=True)

    u.wait_for_save()
    u.rejects("set_ambient_light rejects a malformed colour", "set_ambient_light", color="nothex")


# -------------------------------------------------------------------- colour
# Colour has its own group because it is the only path that drives an editor
# TOOL to place something (colour is baked at placement, so it has to go through
# ObjectTool's Preview). That makes it the riskiest surface in the bridge, and
# it went untested for a long time on the assumption that colourable assets
# needed an asset pack. They do not — vanilla ships plenty — and the first
# vanilla colour placement crashed Dungeondraft.
@group("colour")
def colour(u: Uat) -> None:
    asset, note = u.colourable_asset()
    if not asset:
        u.skipped.append(("colour group", note))
        return
    short = asset.rsplit("/", 1)[-1]

    def bakes_colour():
        before = u.c.request("get_status")["active_tool"]
        r = u.c.request("place_object", asset=asset, x=u.cx, y=u.cy, color="#2e6db4")
        assert r.get("placed_via") == "ObjectTool", f"placed_via {r.get('placed_via')!r}"
        e = u.c.request("get_element", id=r["id"])
        assert e.get("color") == "#2e6db4", f"colour read back as {e.get('color')!r}"
        u.c.request("delete_element", id=r["id"])
        return f"{short} tinted via ObjectTool (UI tool was {before!r})"

    u.check("place_object bakes a custom colour", bakes_colour)

    # regression: the tinted path returned the id of ObjectTool's NEXT Preview
    # rather than the object it committed. get_element on it said "no element
    # with id N" while the real object sat at N-1, so nothing placed with a
    # colour could be moved, modified or deleted afterwards.
    def id_addresses_the_object():
        r = u.c.request("place_object", asset=asset, x=u.cx + 256, y=u.cy, color="#2e6db4")
        e = u.c.request("get_element", id=r["id"])
        assert e["position"] == [u.cx + 256, u.cy], f"id {r['id']} is not that object: {e}"
        assert e.get("asset") == asset, f"id {r['id']} resolved to {e.get('asset')!r}"
        u.c.request("delete_element", id=r["id"])
        return f"id {r['id']} resolves to the object that was placed"

    u.check("a tinted placement returns a usable id", id_addresses_the_object)

    # regression: scale and rotation were applied to the Preview, not to the
    # committed object, so a tinted placement silently came out 1.0 / 0deg.
    # The untinted path had always honoured them, which is what hid this.
    def transform_survives_confirm():
        r = u.c.request(
            "place_object",
            asset=asset,
            x=u.cx - 256,
            y=u.cy,
            color="#2e6db4",
            scale=2.5,
            rotation=45.0,
        )
        e = u.c.request("get_element", id=r["id"])
        assert abs(e["scale"] - 2.5) < 0.01, f"scale {e['scale']} (dropped by Confirm)"
        assert abs(e["rotation"] - 45.0) < 0.1, f"rotation {e['rotation']} (dropped by Confirm)"
        u.c.request("delete_element", id=r["id"])
        return "scale 2.5 and rotation 45 survive the tool path"

    u.check("a tinted placement keeps scale and rotation", transform_survives_confirm)

    def survives_tool_driving():
        # Arrange the crash condition rather than hoping for it. Until
        # select_tool existed this could only be set up by hand, so the
        # regression test for the worst bug in the bridge could not run
        # unattended — and a fresh map reports active_tool None, which is
        # exactly the case that does NOT reproduce it.
        sel = u.c.request("select_tool", tool="ObjectTool")
        assert sel.get("applied") is True, f"could not select ObjectTool: {sel}"
        r = u.c.request("place_object", asset=asset, x=u.cx + 512, y=u.cy, color="#b42e6d")
        time.sleep(1.0)  # several frames of Editor._Process
        for i in range(3):
            assert u.c.request("ping")["pong"] is True, f"bridge died {i + 1} call(s) later"
        after = u.c.request("get_status")["active_tool"]
        assert after == "ObjectTool", f"UI tool changed to {after!r} under us"
        u.c.request("delete_element", id=r["id"])
        return "ObjectTool selected in the UI, tinted placement, still serving"

    u.check("tinted placement leaves the bridge alive", survives_tool_driving)

    def colour_with_modulate_refused():
        before = u.c.request("get_status")
        try:
            u.c.request("place_object", asset=asset, color="#2e6db4", modulate="#808080")
        except BridgeCommandError as exc:
            assert "modulate" in str(exc) and "saving" in str(exc), str(exc)
        else:
            raise AssertionError("tinted placement accepted nonpersistent modulate")
        after = u.c.request("get_status")
        assert after["counts"] == before["counts"], "refusal placed a colored object"
        assert after["undo_depth"] == before["undo_depth"], "refusal changed history"
        return "color plus modulate refused before colored placement"

    u.check("colored placement refuses nonpersistent modulate", colour_with_modulate_refused)

    # regression: a malformed colour used to fall through to black rather than
    # being refused, silently baking the wrong colour into an unchangeable prop.
    u.rejects(
        "place_object rejects a malformed colour",
        "place_object",
        asset=asset,
        x=u.cx,
        y=u.cy,
        color="nothex",
    )

    # Colour cannot be changed after placement — not by the bridge, and not in
    # Dungeondraft's own UI. Accepting it would be worse than refusing.
    made = u.c.request("place_object", asset=asset, x=u.cx, y=u.cy + 512, color="#2e6db4")["id"]
    u.rejects(
        "modify_object refuses to recolour a placed object",
        "modify_object",
        id=made,
        color="#ff0000",
    )

    # regression: place_object had this guard; four other commands did not, and
    # every one of them accepted color="nothex", substituted a default and
    # reported success. Wall and object colour are baked at placement, so the
    # caller was left with a permanently wrong element. Parameterised so a new
    # colour-taking command is one line away from being covered.
    for cmd, extra in (
        ("add_light", {}),
        ("add_text", {"text": "uat"}),
        ("draw_wall", {"points": [[u.cx, u.cy], [u.cx + 300, u.cy]]}),
        ("set_ambient_light", {}),
    ):
        u.rejects(
            f"{cmd} rejects a malformed colour",
            cmd,
            **{"color": "nothex", **({"x": u.cx, "y": u.cy} if "points" not in extra else {})},
            **extra,
        )
    u.rejects(
        "dig_cave rejects a malformed ground_color",
        "dig_cave",
        x=u.cx + 900,
        y=u.cy + 900,
        radius=200.0,
        ground_color="nothex",
    )

    # The array form must still be ACCEPTED — set_ambient_light used to refuse
    # it, because it validated with _is_hex_color instead of the shared guard.
    def array_colour_accepted():
        r = u.c.request("set_ambient_light", color=[1.0, 0.9, 0.7])
        assert r.get("ambient_light"), f"array colour not applied: {r}"
        u.c.request("set_ambient_light", color="#ffffff")
        return f"[1.0, 0.9, 0.7] accepted -> {r['ambient_light']}"

    u.check("a colour given as [r,g,b] is accepted", array_colour_accepted)

    # regression: place_object with a colour returned the id of ObjectTool's
    # NEXT Preview — a plausible integer resolving to nothing. Every create now
    # verifies its id resolves before returning it, centrally, so this covers
    # commands added later too.
    def every_create_returns_a_resolvable_id():
        made = []
        cases = [
            ("place_object", dict(asset=asset, x=u.cx, y=u.cy, color="#2e6db4")),
            ("place_object", dict(asset=asset, x=u.cx + 128, y=u.cy)),
            ("add_light", dict(x=u.cx, y=u.cy + 128, color="#ffcc88")),
            ("add_text", dict(x=u.cx, y=u.cy + 256, text="uat", color="#101010")),
            ("draw_wall", dict(points=[[u.cx, u.cy + 384], [u.cx + 300, u.cy + 384]])),
        ]
        for cmd, kw in cases:
            r = u.c.request(cmd, **kw)
            e = u.c.request("get_element", id=r["id"])
            assert e["id"] == r["id"], f"{cmd} id {r['id']} resolved to {e}"
            made.append(r["id"])
        for i in made:
            u.c.request("delete_element", id=i)
        return f"{len(made)} creates, every id resolved through get_element"

    u.check("every create returns an id that resolves", every_create_returns_a_resolvable_id)

    def still_original():
        e = u.c.request("get_element", id=made)
        assert e.get("color") == "#2e6db4", f"colour changed to {e.get('color')!r}"
        u.c.request("delete_element", id=made)
        return "refusal left the baked colour untouched"

    u.check("a refused recolour changes nothing", still_original)


@group("hooks")
def hooks(u: Uat) -> None:
    def signals_connected():
        s = u.c.request("get_status")
        got = set(s.get("signals") or [])
        want = {"OnSaveBegin", "OnSaveEnd", "OnAssignNode"}
        assert want <= got, f"not connected: {sorted(want - got)}"
        return f"connected: {sorted(got)}"

    u.check("the 1.2 signals are connected", signals_connected)

    def save_state_shape():
        s = u.c.request("get_status")["saving"]
        for k in ("in_flight", "path", "is_backup", "last_saved", "saves_seen", "tracked"):
            assert k in s, f"saving.{k} missing"
        assert s["tracked"] is True, "save tracking reports itself as unavailable"
        assert s["in_flight"] is False, f"a save is in flight already: {s}"
        return f"tracked, {s['saves_seen']} save(s) seen so far"

    u.check("get_status reports save state", save_state_shape)

    def assign_log_grows():
        before = u.c.request("get_recent_nodes", since=0, limit=1)["next_since"]
        obj = u.asset("Objects", "barrel") or u.asset("Objects")
        r = u.c.request("place_object", asset=obj, x=u.cx + 1024, y=u.cy + 1024)
        after = u.c.request("get_recent_nodes", since=before, limit=50)
        assert after["next_since"] > before, "OnAssignNode never fired"
        ids = [n.get("id") for n in after["nodes"]]
        assert r["id"] in ids, f"placed id {r['id']} not in the assign log {ids}"
        u.c.request("delete_element", id=r["id"])
        return f"seq {before} -> {after['next_since']}, placed id present"

    u.check("OnAssignNode records new node ids", assign_log_grows)

    def prefab_reports_ids():
        sets = u.c.request("list_prefabs")
        names = sets.get("prefabs") or []
        if not names:
            raise AssertionError("no prefabs in the current set to place")
        r = u.c.request("place_prefab", name=names[0])
        assert r.get("placed") is True, f"prefab not placed: {r}"
        ids = r.get("ids")
        assert ids, f"place_prefab reported no ids: {r}"
        # The ids must be real: this is the whole point of the hook.
        e = u.c.request("get_element", id=ids[0])
        assert e["id"] == ids[0], f"id {ids[0]} does not resolve"
        for i in ids:
            try:
                u.c.request("delete_element", id=i)
            except Exception:
                pass
        return f"{names[0]!r} reported {len(ids)} addressable id(s)"

    u.check("place_prefab reports the ids it created", prefab_reports_ids, needs_dirty=True)

    # `layer` is a VALUE (-500..900 by 100), not the layer menu's index. The
    # first version of set_tool_layer passed it straight to SetLayer, which
    # takes the index — so "layer 0" silently put the tool on -500, and an
    # index past the end of the menu left ActiveLayer null with nothing said.
    def layer_roundtrip():
        info = u.c.request("get_tool_layer", tool="ObjectTool")
        was = info["layer"]
        assert info["step"] == 100 and info["min"] == -500 and info["max"] == 900, (
            f"the layer menu is not laid out as this build expects: {info}"
        )
        target = was + info["step"]
        r = u.c.request("set_tool_layer", tool="ObjectTool", layer=target)
        assert r["applied"] is True, f"layer {target} not applied: {r}"
        now = u.c.request("get_tool_layer", tool="ObjectTool")["layer"]
        assert now == target, f"tool holds {now}, asked for {target}"
        assert r["layer"] == now, f"set_tool_layer said {r['layer']}, tool holds {now}"
        u.c.request("set_tool_layer", tool="ObjectTool", layer=was)
        back = u.c.request("get_tool_layer", tool="ObjectTool")["layer"]
        assert back == was, f"layer not restored: {back} vs {was}"
        return f"layer {was} -> {target} -> restored"

    u.check("tool layer round-trips and reports honestly", layer_roundtrip)

    def layer_extremes():
        was = u.c.request("get_tool_layer", tool="ObjectTool")["layer"]
        for edge in (-500, 900):
            r = u.c.request("set_tool_layer", tool="ObjectTool", layer=edge)
            assert r["applied"] is True and r["layer"] == edge, f"layer {edge}: {r}"
        u.c.request("set_tool_layer", tool="ObjectTool", layer=was)
        return "both ends of the menu (-500, 900) apply and read back"

    u.check("the extreme layers apply", layer_extremes)

    u.rejects("get_tool_layer rejects an unknown tool", "get_tool_layer", tool="NoSuchTool")
    u.rejects(
        "set_tool_layer rejects an unknown tool", "set_tool_layer", tool="NoSuchTool", layer=100
    )
    # regression: an off-grid or out-of-range layer used to reach SetLayer as an
    # index and leave ActiveLayer null — an unusable tool, reported as success.
    u.rejects(
        "set_tool_layer rejects an off-grid layer", "set_tool_layer", tool="ObjectTool", layer=150
    )
    u.rejects(
        "set_tool_layer rejects a layer past the menu",
        "set_tool_layer",
        tool="ObjectTool",
        layer=5000,
    )
    u.rejects("select_tool rejects an unknown tool", "select_tool", tool="NoSuchTool")

    def select_tool_roundtrip():
        was = u.c.request("get_status")["active_tool"]
        r = u.c.request("select_tool", tool="SelectTool")
        assert r["applied"] is True, f"did not select: {r}"
        assert u.c.request("get_status")["active_tool"] == "SelectTool", "status disagrees"
        # Leave the UI on something harmless rather than whatever we borrowed.
        u.c.request("select_tool", tool="ObjectTool")
        return f"was {was!r}, selected SelectTool, restored ObjectTool"

    u.check("select_tool changes the UI's active tool", select_tool_roundtrip)


@group("mixed_group")
def mixed_group(u: Uat) -> None:
    if not u.dirty:
        return

    def rigid_group():
        x, y = u.cx, u.cy
        ids = []
        try:
            wall = u.c.request("draw_wall", points=[[x - 1024, y + 1024], [x, y + 1024]], type=1)[
                "id"
            ]
            ids.append(wall)
            portal = u.c.request(
                "add_portal", asset=u.asset("Portals"), x=x - 512, y=y + 1024, snap_max=1
            )["id"]
            ids.append(portal)
            ids.append(
                u.c.request(
                    "draw_path",
                    asset=u.asset("Paths"),
                    points=[[x + 256, y + 1024], [x + 768, y + 1024]],
                )["id"]
            )
            ids.append(
                u.c.request(
                    "add_roof",
                    asset=u.asset("Roofs"),
                    points=[[x + 1024, y + 1024], [x + 1536, y + 1024]],
                    width=128,
                )["id"]
            )
            ids.append(u.c.request("place_object", asset=u.asset("Objects"), x=x - 1024, y=y)["id"])
            ids.append(u.c.request("add_light", x=x, y=y)["id"])
            ids.append(u.c.request("add_text", x=x + 512, y=y, text="group uat")["id"])
            ids.append(
                u.c.request("add_portal", asset=u.asset("Portals"), x=x + 1024, y=y, mount="free")[
                    "id"
                ]
            )
            ids.append(
                u.c.request(
                    "place_pattern",
                    category="Simple Tiles",
                    asset=u.asset("Simple Tiles"),
                    rect=[x - 512, y - 768, 256, 384],
                )["id"]
            )
            before = {i: u.c.request("get_element", id=i) for i in ids}
            depth = u.c.request("get_status")["undo_depth"]
            result = u.c.request(
                "move_elements",
                ids=[portal] + ids + [wall],
                dx=256,
                dy=-128,
                rotation=90,
                pivot_x=x,
                pivot_y=y,
            )
            assert set(result["moved"]) == set(ids) and len(result["moved"]) == len(ids), result
            assert not result["unsupported"] and not result["missing"], result
            assert u.c.request("get_status")["undo_depth"] == min(
                depth + 1, u.c.request("get_status")["max_undo"]
            )
            after = {i: u.c.request("get_element", id=i) for i in ids}
            for i in ids:
                a, c = before[i], after[i]
                for old, new in zip(
                    a.get("points", [a["position"]]), c.get("points", [c["position"]]), strict=True
                ):
                    expected = [x + 256 - (old[1] - y), y - 128 + (old[0] - x)]
                    assert all(abs(v - e) < 0.02 for v, e in zip(new, expected, strict=True)), (
                        i,
                        new,
                        expected,
                    )
            assert after[portal]["wall_id"] == wall
            assert before[ids[7]]["kind"] == "portal", before[ids[7]]
            assert u.c.request("undo")["kind"] == "transform_many"
            assert {i: u.c.request("get_element", id=i) for i in ids} == before
            assert u.c.request("redo")["kind"] == "transform_many"
            assert {i: u.c.request("get_element", id=i) for i in ids} == after
            u.c.request("undo")
            state = u.c.request("get_element", id=portal)
            refused = u.c.request("move_elements", ids=[portal, 987654321], dx=100, dy=100)
            assert refused["moved"] == [] and refused["missing"] == [987654321], refused
            assert refused["unsupported"][0]["id"] == portal, refused
            assert u.c.request("get_element", id=portal) == state
            # A wall-only request must still report and move its attached door.
            auto = u.c.request("move_elements", ids=[wall], dx=128, dy=0)
            assert set(auto["moved"]) == {wall, portal}, auto
            u.c.request("undo")
            assert u.c.request("get_element", id=portal) == state
            polygon = before[ids[-1]]["points"]
            centre = [(min(p[a] for p in polygon) + max(p[a] for p in polygon)) / 2 for a in (0, 1)]
            pattern_turn = u.c.request("move_elements", ids=[ids[-1]], dx=0, dy=0, rotation=90)
            assert pattern_turn["pivot"] == centre, pattern_turn
            u.c.request("undo")
            assert u.c.request("get_element", id=ids[-1]) == before[ids[-1]]
            return "9 kinds; deduplicated rigid move, grouped undo, attached doors"
        finally:
            for i in reversed(ids):
                u.c.request("delete_element", id=i)

    u.check("mixed groups preserve geometry and portal ownership", rigid_group)

    def prefab_frame():
        library = u.c.request("list_prefabs")
        name = library["prefabs"][0]
        placed = u.c.request("place_prefab", name=name, x=u.cx, y=u.cy, rotation=90)
        ids = placed["ids"]
        try:
            assert placed["placed"] and ids, placed
            assert not placed["placement"]["skipped"], placed
            points = []
            for i in ids:
                element = u.c.request("get_element", id=i)
                points.extend(element.get("points", [element["position"]]))
            centre = [(min(p[a] for p in points) + max(p[a] for p in points)) / 2 for a in (0, 1)]
            assert abs(centre[0] - u.cx) < 0.1 and abs(centre[1] - u.cy) < 0.1, centre
            assert u.c.request("undo")["kind"] == "group"
            assert u.c.request("redo")["kind"] == "group"
            assert all(u.c.request("get_element", id=i) for i in ids)
            return "native prefab centred/rotated with complete readback and grouped creation undo"
        finally:
            for i in reversed(ids):
                u.c.request("delete_element", id=i)

    u.check("prefab placement shares the rigid group transform", prefab_frame)


@group("cave_entrance")
def cave_entrance(u: Uat) -> None:
    def read_cave():
        state = u.c.request("get_cave")
        assert state["floor_cells"] >= 0 and state["entrance_cells"] >= 0
        assert len(state["bitmap_size"]) == 2
        return f"{state['bitmap_size']}, {state['entrance_cells']} entrance cells"

    u.check("cave inspection reads both bitmaps", read_cave)
    if not u.dirty:
        return
    x, y = u.cx, u.cy

    def roundtrip():
        u.c.request("dig_cave", points=[[x - 512, y], [x, y]], radius=256)
        u.c.request("set_cave_entrance", x=x + 256, y=y, radius=192, open=False)
        before = u.c.request("get_cave")
        opened = u.c.request("set_cave_entrance", x=x + 256, y=y, radius=192)
        assert opened["changed_cells"] > 0, opened
        after = u.c.request("get_cave")
        assert after["floor_cells"] == before["floor_cells"]
        assert after["entrance_cells"] == before["entrance_cells"] + opened["changed_cells"]
        assert u.c.request("undo")["kind"] == "cave"
        assert u.c.request("get_cave") == before
        assert u.c.request("redo")["kind"] == "cave"
        assert u.c.request("get_cave") == after
        depth = u.c.request("get_status")["undo_depth"]
        assert u.c.request("set_cave_entrance", x=x + 256, y=y, radius=192)["changed_cells"] == 0
        assert u.c.request("get_status")["undo_depth"] == depth
        u.c.request("clear_caves")
        u.c.request("undo")
        assert u.c.request("get_cave") == after
        return "opening preserves floor; undo/redo and clear undo restore both rasters"

    u.check("cave entrances and clearing are reversible", roundtrip)

    def wrong_level():
        start = u.c.request("list_levels")["current_level_id"]
        made = u.c.request("add_level", label="uat-cave-history")["id"]
        try:
            u.c.request("set_level", id=start)
            before = u.c.request("get_cave")
            u.c.request("set_cave_entrance", x=x + 256, y=y, radius=192, open=False)
            u.c.request("set_level", id=made)
            depth = u.c.request("get_status")["undo_depth"]
            try:
                u.c.request("undo")
            except BridgeCommandError as exc:
                assert "original level" in str(exc)
            else:
                raise AssertionError("wrong-level undo accepted")
            assert u.c.request("get_status")["undo_depth"] == depth
            assert u.c.request("get_cave")["entrance_cells"] == 0
            u.c.request("set_level", id=start)
            assert u.c.request("undo")["kind"] == "cave"
            assert u.c.request("get_cave") == before
        finally:
            u.c.request("set_level", id=start)
            u.c.request("delete_level", id=made)
        return "refused on another level; original pending undo still succeeds"

    u.check("cave undo refuses another level without consuming history", wrong_level)

    def resized():
        dims = u.c.request("get_status")["map_size_woxels"]
        width, height = [int(v / 256) for v in dims]
        before = u.c.request("get_cave")
        u.c.request("set_cave_entrance", x=x + 256, y=y, radius=192, open=False)
        try:
            u.c.request("set_map_size", width=width + 1, height=height + 1)
            depth = u.c.request("get_status")["undo_depth"]
            try:
                u.c.request("undo")
            except BridgeCommandError as exc:
                assert "resize" in str(exc)
            else:
                raise AssertionError("undo after resize accepted")
            assert u.c.request("get_status")["undo_depth"] == depth
        finally:
            u.c.request("set_map_size", width=width, height=height)
        assert u.c.request("undo")["kind"] == "cave"
        assert u.c.request("get_cave") == before
        return "resize refusal keeps history; restoring dimensions permits undo"

    u.check("cave undo refuses changed map dimensions", resized)

    def invalid():
        before = u.c.request("get_cave")
        depth = u.c.request("get_status")["undo_depth"]
        for params in [
            {"x": -1, "y": y},
            {"x": x, "y": y, "radius": 2049},
            {"x": x, "y": y, "open": "false"},
            {"x": [], "y": y},
        ]:
            try:
                u.c.request("set_cave_entrance", **params)
            except BridgeCommandError:
                pass
            else:
                raise AssertionError(f"invalid request accepted: {params}")
        assert u.c.request("get_cave") == before
        assert u.c.request("get_status")["undo_depth"] == depth
        return "invalid raw requests change neither cave bitmaps nor history"

    u.check("cave entrance validation is atomic", invalid)


@group("map_style")
def map_style(u: Uat) -> None:
    def read_style():
        state = u.c.request("get_map_style")
        assert state["scope"] == "map", state
        assert state["building_wear"] in state["options"]["building_wear"], state
        assert state["grid_style"] in state["options"]["grid_style"], state
        return f"wear={state['building_wear']}, grid={state['grid_style']}"

    u.check("map style reports actual world textures", read_style)
    if not u.dirty:
        return

    def choices():
        original = u.c.request("get_map_style")
        for wear in original["options"]["building_wear"]:
            got = u.c.request("set_map_style", building_wear=wear)
            assert got["building_wear"] == wear, got
            assert got["grid_style"] == original["grid_style"], got
            assert got == u.c.request("get_map_style"), got
        for grid in original["options"]["grid_style"]:
            got = u.c.request("set_map_style", grid_style=grid)
            assert got["grid_style"] == grid, got
            assert got == u.c.request("get_map_style"), got
        u.c.request(
            "set_map_style",
            building_wear=original["building_wear"],
            grid_style=original["grid_style"],
        )
        return "5 wear and 4 grid choices read back; omitted field preserved"

    u.check("map style applies every supported choice", choices)

    def history():
        original = u.c.request("get_map_style")
        wear = "grime" if original["building_wear"] != "grime" else "none"
        grid = "thick_line" if original["grid_style"] != "thick_line" else "dotted"
        depth = u.c.request("get_status")["undo_depth"]
        changed = u.c.request("set_map_style", building_wear=wear, grid_style=grid)
        assert u.c.request("get_status")["undo_depth"] == min(
            depth + 1, u.c.request("get_status")["max_undo"]
        )
        assert u.c.request("undo")["kind"] == "map_style"
        assert u.c.request("get_map_style") == original
        assert u.c.request("redo")["kind"] == "map_style"
        assert u.c.request("get_map_style") == changed
        u.c.request("undo")
        return "both settings undone/redone together with actual texture readback"

    u.check("map style is one reversible edit", history)

    def across_levels():
        start = u.c.request("list_levels")["current_level_id"]
        original = u.c.request("get_map_style")
        made = u.c.request("add_level", label="uat-map-style")["id"]
        try:
            u.c.request("set_level", id=start)
            wear = "dust" if original["building_wear"] != "dust" else "none"
            changed = u.c.request("set_map_style", building_wear=wear)
            u.c.request("set_level", id=made)
            assert u.c.request("get_map_style") == changed
            assert u.c.request("undo")["kind"] == "map_style"
            assert u.c.request("get_map_style") == original
            assert u.c.request("redo")["kind"] == "map_style"
            assert u.c.request("get_map_style") == changed
            u.c.request("undo")
        finally:
            u.c.request("set_level", id=start)
            u.c.request("delete_level", id=made)
        return "map-wide textures and undo survive switching levels"

    u.check("map style undo works across levels", across_levels)

    def invalid_is_atomic():
        original = u.c.request("get_map_style")
        depth = u.c.request("get_status")["undo_depth"]
        try:
            u.c.request("set_map_style", building_wear="grime", grid_style="invalid")
        except BridgeCommandError:
            pass
        else:
            raise AssertionError("invalid grid style was accepted")
        assert u.c.request("get_map_style") == original
        assert u.c.request("get_status")["undo_depth"] == depth
        return "invalid second field changes neither textures nor history"

    u.check("map style validates all fields before editing", invalid_is_atomic)


@group("wall_merge")
def wall_merge(u: Uat) -> None:
    if not u.dirty:
        return
    wall_asset = u.asset("Walls")
    portal_asset = u.asset("Portals")
    if not wall_asset or not portal_asset:
        return

    def preserves_portal():
        x, y = u.cx - 1000, u.cy
        ids = [
            u.c.request("draw_wall", asset=wall_asset, type=1, points=points)["id"]
            for points in (
                [[x, y], [x + 512, y]],
                [[x + 512, y], [x + 1024, y]],
            )
        ]
        portal = u.c.request(
            "add_portal",
            asset=portal_asset,
            x=x + 768,
            y=y,
            radius=64,
            fallback_free=False,
        )
        assert portal.get("wall_id") == ids[1], portal
        before = [u.c.request("get_element", id=ident) for ident in ids]
        u.c.request("select_elements", ids=ids)
        try:
            u.c.request("tool_action", tool="SelectTool", control="MERGE_WALLS")
        except BridgeCommandError as exc:
            assert "portal" in str(exc).lower(), str(exc)
        else:
            raise AssertionError(
                "merge accepted portal-bearing walls; native merge deletes the door"
            )
        assert [u.c.request("get_element", id=ident) for ident in ids] == before
        assert u.c.request("get_element", id=portal["id"])["wall_id"] == ids[1]
        u.c.request("clear_selection")
        u.c.request("delete_element", id=portal["id"])
        for ident in ids:
            u.c.request("delete_element", id=ident)
        return "merge refused; both wall geometries and the mounted door survived"

    u.check("wall merge refuses to delete mounted portals", preserves_portal)

    def typed_roundtrip():
        checked = 0
        x, y = u.cx - 1024, u.cy - 768
        # Append/prepend and both source directions, straight and corner,
        # automatic and manual. Doors on both inputs must survive.
        for typ in (0, 1):
            for second in (
                [[x + 512, y], [x + 1024, y]],
                [[x + 1024, y], [x + 512, y]],
                [[x - 512, y], [x, y]],
                [[x, y], [x - 512, y]],
                [[x + 512, y], [x + 512, y + 512]],
            ):
                walls = [
                    u.c.request("draw_wall", asset=wall_asset, type=typ, points=pts)["id"]
                    for pts in ([[x, y], [x + 512, y]], second)
                ]
                portals = []
                for pts in ([[x, y], [x + 512, y]], second):
                    portals.append(
                        u.c.request(
                            "add_portal",
                            asset=portal_asset,
                            x=(pts[0][0] + pts[1][0]) / 2,
                            y=(pts[0][1] + pts[1][1]) / 2,
                            radius=48,
                            closed=True,
                            flip=True,
                            fallback_free=False,
                        )["id"]
                    )
                all_ids = walls + portals
                before = [u.c.request("get_element", id=i) for i in all_ids]
                depth = u.c.request("get_status")["undo_depth"]
                result = u.c.request("merge_walls", ids=walls)
                assert result["id"] == walls[0] and result["removed_ids"] == walls[1:]
                assert sorted(result["portal_ids"]) == sorted(portals)
                assert u.c.request("get_status")["undo_depth"] == min(
                    u.c.request("get_status")["max_undo"], depth + 1
                )
                merged = [u.c.request("get_element", id=i) for i in [walls[0]] + portals]
                assert len(merged[0]["points"]) == 3
                listed = {
                    p["id"]: p
                    for p in u.c.request("list_elements", kind="portals", limit=1000)["elements"]
                }
                assert set(portals) <= set(listed), (portals, listed)
                assert all(listed[p]["wall_id"] == walls[0] for p in portals)
                for i, portal in enumerate(merged[1:]):
                    assert portal["wall_id"] == walls[0]
                    for key in ("id", "position", "asset", "radius", "closed"):
                        assert portal[key] == before[2 + i][key], (key, portal, before[2 + i])
                for _ in range(2):
                    assert u.c.request("undo")["kind"] == "wall_merge"
                    assert [u.c.request("get_element", id=i) for i in all_ids] == before
                    assert u.c.request("redo")["kind"] == "wall_merge"
                    listed = {
                        p["id"]
                        for p in u.c.request("list_elements", kind="portals", limit=1000)[
                            "elements"
                        ]
                    }
                    assert set(portals) <= listed, (portals, listed)
                    assert [
                        u.c.request("get_element", id=i) for i in [walls[0]] + portals
                    ] == merged
                u.c.request("undo")
                for i in reversed(all_ids):
                    u.c.request("delete_element", id=i)
                checked += 1
        return f"{checked} orientations/types preserved both doors through repeated undo/redo"

    u.check("typed wall merge preserves IDs and reversible geometry", typed_roundtrip)

    def refused_pairs():
        x, y = u.cx - 1024, u.cy - 768
        cases = [
            ({"points": [[x, y], [x + 512, y]]}, {"points": [[x + 256, y], [x + 256, y + 512]]}),
            ({"points": [[x, y], [x + 512, y]]}, {"points": [[x + 512, y], [x + 256, y]]}),
            ({"points": [[x, y], [x + 512, y]]}, {"points": [[x + 768, y], [x + 1024, y]]}),
            (
                {"points": [[x, y], [x + 512, y]]},
                {"points": [[x + 512, y], [x + 1024, y]], "color": "#123456"},
            ),
            (
                {"points": [[x, y], [x + 512, y]], "loop": True},
                {"points": [[x + 512, y], [x + 1024, y]]},
            ),
            (
                {"points": [[x, y], [x + 512, y]]},
                {"points": [[x + 512, y], [x + 1024, y]], "type": 1},
            ),
            (
                {"points": [[x, y], [x + 512, y], [x + 512, y + 512]]},
                {"points": [[x + 512, y + 512], [x + 256, y - 256]]},
            ),
        ]
        for left, right in cases:
            ids = [u.c.request("draw_wall", asset=wall_asset, **kw)["id"] for kw in (left, right)]
            before = [u.c.request("get_element", id=i) for i in ids]
            depth = u.c.request("get_status")["undo_depth"]
            try:
                u.c.request("merge_walls", ids=ids)
            except BridgeCommandError:
                pass
            else:
                raise AssertionError(f"unsupported merge accepted: {left}, {right}")
            assert [u.c.request("get_element", id=i) for i in ids] == before
            assert u.c.request("get_status")["undo_depth"] == depth
            for i in ids:
                u.c.request("delete_element", id=i)
        return (
            "T-junction, overlap, gap, style/type mismatch, loop and crossing rejected atomically"
        )

    u.check("typed wall merge rejects unsupported pairs without editing", refused_pairs)

    def history_ownership():
        x, y = u.cx - 1024, u.cy - 768
        walls = [
            u.c.request("draw_wall", asset=wall_asset, points=pts)["id"]
            for pts in ([[x, y], [x + 512, y]], [[x + 512, y], [x + 1536, y]])
        ]
        portals = [
            u.c.request(
                "add_portal", asset=portal_asset, x=x + offset, y=y, radius=40, fallback_free=False
            )["id"]
            for offset in (700, 1000, 1300)
        ]
        before = [u.c.request("get_element", id=i) for i in walls + portals]
        u.c.request("merge_walls", ids=walls)
        for _ in range(39):
            u.c.request("add_text", text="uat-history", x=u.cx, y=u.cy)
        for _ in range(39):
            assert u.c.request("undo")["kind"] == "create"
        assert u.c.request("undo")["kind"] == "wall_merge"
        assert [u.c.request("get_element", id=i) for i in walls + portals] == before
        u.c.request("redo")
        listed = {
            p["id"] for p in u.c.request("list_elements", kind="portals", limit=1000)["elements"]
        }
        assert set(portals) <= listed
        u.c.request("undo")
        for i in reversed(walls + portals):
            u.c.request("delete_element", id=i)
        return "three transferred portals and absorbed wall survive creation-history eviction"

    u.check("wall merge retains nodes until its own history expires", history_ownership)

    def level_guard():
        original = u.c.request("get_status")["level_id"]
        other = u.c.request("add_level", label="uat-wall-history")["id"]
        u.c.request("set_level", id=original)
        x, y = u.cx - 1024, u.cy - 768
        walls = [
            u.c.request("draw_wall", asset=wall_asset, points=pts)["id"]
            for pts in ([[x, y], [x + 512, y]], [[x + 512, y], [x + 1024, y]])
        ]
        u.c.request("merge_walls", ids=walls)
        u.c.request("set_level", id=other)
        depth = u.c.request("get_status")["undo_depth"]
        try:
            u.c.request("undo")
        except BridgeCommandError as exc:
            assert "original level" in str(exc)
        else:
            raise AssertionError("wall merge undo accepted a different level")
        assert u.c.request("get_status")["undo_depth"] == depth
        u.c.request("set_level", id=original)
        assert u.c.request("undo")["kind"] == "wall_merge"
        assert u.c.request("redo")["kind"] == "wall_merge"
        u.c.request("undo")
        for i in walls:
            u.c.request("delete_element", id=i)
        u.c.request("delete_level", id=other)
        return "wrong-level undo preserves pending history; portal-free merge also round-trips"

    u.check("wall merge history requires its original level", level_guard)

    def duplicate_portal_anchor():
        x, y = u.cx - 1400, u.cy - 1000
        first = u.c.request("draw_wall", asset=wall_asset, points=[[x, y], [x + 512, y]])["id"]
        p1 = u.c.request("add_portal", asset=portal_asset, x=x + 512, y=y, fallback_free=False)[
            "id"
        ]
        second = u.c.request(
            "draw_wall", asset=wall_asset, points=[[x + 1024, y + 512], [x + 1536, y + 512]]
        )["id"]
        p2 = u.c.request(
            "add_portal", asset=portal_asset, x=x + 1024, y=y + 512, fallback_free=False
        )["id"]
        u.c.request("move_elements", ids=[second], dx=-512, dy=-512)
        ids = [first, second, p1, p2]
        before = [u.c.request("get_element", id=i) for i in ids]
        depth = u.c.request("get_status")["undo_depth"]
        try:
            u.c.request("merge_walls", ids=[first, second])
        except BridgeCommandError as exc:
            assert "same merged anchor" in str(exc), str(exc)
        else:
            raise AssertionError("colliding portal anchors were accepted")
        assert [u.c.request("get_element", id=i) for i in ids] == before
        assert u.c.request("get_status")["undo_depth"] == depth
        for i in reversed(ids):
            u.c.request("delete_element", id=i)
        return "two doors at the shared endpoint rejected before editing"

    u.check("wall merge rejects colliding portal anchors atomically", duplicate_portal_anchor)


# ------------------------------------------------------------------ history
# Behaviour, not source: these replace tests that grepped the mod for
# MAX_SNAPSHOT_OPS, a `_trim_snapshot_ops()` call and SAFE_DURING_SAVE
# membership. A constant can exist and a call can appear while the stack still
# grows or a read still discards redo; only running the commands shows either.
@group("batch")
def batch(u: Uat) -> None:
    """place_objects and delete_elements: one call, one undo step, all or nothing."""

    def objects_at(y):
        asset = u.asset("Objects")
        return [{"asset": asset, "x": u.cx - 1024 + i * 192, "y": y} for i in range(4)]

    def on_map(ident) -> bool:
        try:
            return u.c.request("get_element", id=ident).get("id") == ident
        except BridgeCommandError:
            return False

    def batch_placement_is_one_undo_step():
        before = u.c.request("get_status")
        result = u.c.request("place_objects", objects=objects_at(u.cy - 3584))
        made = [entry["id"] for entry in result["objects"]]
        after = u.c.request("get_status")
        assert result["placed"] == 4 and len(made) == 4, result
        assert after["counts"]["objects"] == before["counts"]["objects"] + 4, after["counts"]
        assert after["undo_depth"] == before["undo_depth"] + 1, (
            f"4 objects took {after['undo_depth'] - before['undo_depth']} undo steps"
        )
        assert all(on_map(ident) for ident in made), made
        original = {ident: u.c.request("get_element", id=ident) for ident in made}

        undone = u.c.request("undo")
        time.sleep(0.3)
        assert undone["undone"] is True, undone
        assert not any(on_map(ident) for ident in made), "undo left some of the batch on the map"
        assert u.c.request("get_status")["counts"]["objects"] == before["counts"]["objects"]

        u.c.request("redo")
        time.sleep(0.3)
        assert all(on_map(ident) for ident in made), "redo did not put the whole batch back"
        for ident in made:
            restored = u.c.request("get_element", id=ident)
            assert restored == original[ident], f"redo changed object {ident}: {restored}"
        u.c.request("delete_elements", ids=made)
        return f"4 placed in 1 call and 1 undo step, ids {made}"

    u.check(
        "batch: place_objects is one undo step", batch_placement_is_one_undo_step, needs_dirty=True
    )

    def batch_deletion_is_one_undo_step():
        made = [
            entry["id"]
            for entry in u.c.request("place_objects", objects=objects_at(u.cy - 3840))["objects"]
        ]
        before = u.c.request("get_status")
        removed = u.c.request("delete_elements", ids=made)
        time.sleep(0.3)
        after = u.c.request("get_status")
        assert removed["deleted"] == 4, removed
        assert not any(on_map(ident) for ident in made), "an id survived delete_elements"
        assert after["counts"]["objects"] == before["counts"]["objects"] - 4, after["counts"]
        assert after["undo_depth"] == before["undo_depth"] + 1, (
            f"4 deletes took {after['undo_depth'] - before['undo_depth']} undo steps"
        )

        u.c.request("undo")
        time.sleep(0.3)
        assert all(on_map(ident) for ident in made), "undo did not restore the whole batch"
        assert u.c.request("get_status")["counts"]["objects"] == before["counts"]["objects"]
        u.c.request("delete_elements", ids=made)
        return "4 deleted in 1 call and 1 undo step, all restored by undo"

    u.check(
        "batch: delete_elements is one undo step", batch_deletion_is_one_undo_step, needs_dirty=True
    )

    def a_bad_entry_places_nothing():
        before = u.c.request("get_status")["counts"]["objects"]
        entries = objects_at(u.cy - 4096)
        entries[2] = dict(entries[2], asset="res://textures/objects/does_not_exist.png")
        try:
            u.c.request("place_objects", objects=entries)
        except BridgeCommandError as refused:
            message = str(refused)
        else:
            raise AssertionError("a nonexistent asset was accepted")
        time.sleep(0.3)
        after = u.c.request("get_status")["counts"]["objects"]
        assert after == before, f"a refused batch left {after - before} objects behind"
        assert "objects[2]" in message, message
        return "a bad entry named its index and placed nothing"

    u.check("batch: one bad entry places nothing", a_bad_entry_places_nothing, needs_dirty=True)

    def an_unknown_id_deletes_nothing():
        made = u.c.request("place_objects", objects=objects_at(u.cy - 4352))["objects"]
        ids = [entry["id"] for entry in made]
        before = u.c.request("get_status")["counts"]["objects"]
        try:
            u.c.request("delete_elements", ids=[*ids, 999999])
        except BridgeCommandError as refused:
            message = str(refused)
        else:
            raise AssertionError("an unknown id was accepted")
        time.sleep(0.3)
        assert u.c.request("get_status")["counts"]["objects"] == before, (
            "a refused delete_elements removed something anyway"
        )
        assert all(on_map(ident) for ident in ids), ids
        u.c.request("delete_elements", ids=ids)
        assert "999999" in message, message
        return "an unknown id refused the batch and deleted nothing"

    u.check(
        "batch: one unknown id deletes nothing", an_unknown_id_deletes_nothing, needs_dirty=True
    )

    def coloured_batch_leaves_the_tool_usable():
        """A coloured placement drives ObjectTool, and the tool holds a Preview
        inside the same node tree the undo detaches from. If the batch's undo
        takes the Preview with it, the NEXT placement dies a frame later."""
        carpets = u.c.request(
            "list_assets",
            category="Objects",
            search="carpet",
            limit=COLORABLE_ASSET_SCAN_LIMIT,
            vanilla_only=True,
        )
        colourable = vanilla_colourable_assets(carpets["assets"], carpets["colorable"])
        if not colourable:
            return "skipped: this map offers no colourable Objects asset"
        tinted = [
            {
                "asset": colourable[0],
                "x": u.cx - 512 + i * 256,
                "y": u.cy - 4608,
                "color": "#3366ff",
            }
            for i in range(2)
        ]
        made = [entry["id"] for entry in u.c.request("place_objects", objects=tinted)["objects"]]
        u.c.request("undo")
        time.sleep(0.5)
        after = u.c.request("place_object", asset=u.asset("Objects"), x=u.cx, y=u.cy - 4864)
        time.sleep(0.5)
        assert on_map(after["id"]), "the placement after a coloured batch undo did not survive"
        assert u.c.request("ping")["pong"] is True, "the bridge stopped answering"
        u.c.request("delete_element", id=after["id"])
        return f"2 tinted placed and undone ({made}); the next placement and the bridge survived"

    u.check(
        "batch: a coloured batch undo leaves ObjectTool usable",
        coloured_batch_leaves_the_tool_usable,
        needs_dirty=True,
    )

    def file_sized_batch_is_one_undo_step():
        """The group undo recorded only the first 500 nodes a command created, so
        undoing 600 left 100 behind with the op reporting success.
        """
        asset = u.asset("Objects")
        items = [
            {"asset": asset, "x": 256 + (i % 30) * 256, "y": 256 + (i // 30) * 200}
            for i in range(600)
        ]
        before = u.c.request("get_status")
        result = u.c.request("place_objects", objects=items, compact=True)
        after = u.c.request("get_status")
        assert result["placed"] == 600 and "objects" not in result, sorted(result)
        placed = sum(last - first + 1 for first, last in result["id_ranges"])
        assert placed == 600, result["id_ranges"]
        assert after["undo_depth"] == before["undo_depth"] + 1, "600 objects took several steps"
        u.c.request("undo")
        time.sleep(0.5)
        left = u.c.request("get_status")["counts"]["objects"] - before["counts"]["objects"]
        assert left == 0, f"one undo left {left} of 600 objects on the map"
        return f"600 placed in one compact call ({len(result['id_ranges'])} id range) and undone"

    u.check(
        "batch: a 600-object file batch is one undo step",
        file_sized_batch_is_one_undo_step,
        needs_dirty=True,
    )


@group("patch")
def patch(u: Uat) -> None:
    """Runtime behavior and validation."""
    info = u.c.request("get_status").get("unofficial_patch") or {}
    loaded = bool(info.get("loaded"))
    label = f"patch {info.get('version')}" if loaded else "no patch"

    def refused(cmd: str, fragment: str, **params) -> str:
        try:
            u.c.request(cmd, **params)
        except BridgeCommandError as exc:
            assert fragment in str(exc), f"unexplained refusal: {exc}"
            return str(exc)
        raise AssertionError(f"{cmd} {params} was accepted")

    def reports_itself():
        ping = u.c.request("ping").get("unofficial_patch")
        assert ping == info, f"ping {ping} and get_status {info} disagree"
        assert "dialog_open" in u.c.request("get_status"), "get_status has no dialog_open"
        if loaded:
            assert info.get("version"), f"no version: {info}"
        return f"{label}: {info}"

    u.check("patch: ping and get_status report it", reports_itself)

    def layers_follow_the_patch():
        asset = u.asset("Objects", "barrel") or u.asset("Objects")
        refused("place_object", "must be", asset=asset, x=u.cx, y=u.cy, layer=150)
        extra = u.c.request("get_tool_layer", tool="ObjectTool").get("extra_layers")
        if not loaded:
            refused("place_object", "must be", asset=asset, x=u.cx, y=u.cy, layer=1100)
            assert extra is None, f"extra layers without the patch: {extra}"
            return "150 and 1100 refused; -500..900 only"
        assert extra == [1100], f"extra_layers {extra}"
        placed = u.c.request("place_object", asset=asset, x=u.cx, y=u.cy, layer=1100)
        try:
            got = u.c.request("get_element", id=placed["id"])["layer"]
            assert got == 1100, f"placed on 1100, read back {got}"
        finally:
            u.c.request("delete_element", id=placed["id"])
        before = u.c.request("get_tool_layer", tool="ObjectTool")["layer"]
        try:
            r = u.c.request("set_tool_layer", tool="ObjectTool", layer=1100)
            assert r["applied"] and r["layer"] == 1100, r
        finally:
            u.c.request("set_tool_layer", tool="ObjectTool", layer=before)
        return "1100 places, reads back and selects in ObjectTool; 150 refused"

    u.check("patch: layers follow the patch", layers_follow_the_patch, needs_dirty=True)

    def map_size_follows_the_patch():
        s = u.c.request("get_status")
        w0, h0 = (int(v / 256) for v in s["map_size_woxels"])
        if not loaded:
            refused("set_map_size", "8 to 128", width=129, height=h0)
            return "129 tiles refused (8..128)"
        refused("set_map_size", "1 to 200", width=201, height=h0)
        r = u.c.request("set_map_size", width=150, height=h0 + 10)
        try:
            assert r["steps"] == 1, f"the patch's resize takes any size in one step: {r}"
            splat = u.c.request("get_terrain", samples=2)["splat_size"]
            assert splat == [600, (h0 + 10) * 4], f"terrain not resized: {splat}"
        finally:
            back = u.c.request("set_map_size", width=w0, height=h0)
        assert back["width_tiles"] == w0 and back["height_tiles"] == h0, back
        return f"{w0}x{h0} -> 150x{h0 + 10} in one step, terrain resized, restored; 201 refused"

    u.check("patch: map size follows the patch", map_size_follows_the_patch, needs_dirty=True)


@group("snap")
def snap(u: Uat) -> None:
    """The mod snaps the cursor, not the bridge, so the server snaps coordinates
    itself with a port of the mod's math. This asks the mod for ITS answer on
    the same points and compares, on whatever grid the user has set up. Run it
    once per grid worth trusting: a square preset, a hex preset each way, and
    one with an offset.
    """
    from battlemap_mcp import snapping

    state = u.c.request("get_snap_settings")
    if not state.get("mod_loaded"):
        u.skipped.append(("snap group", "the Custom Snap Mod is not loaded"))
        return
    from battlemap_mcp import server as _server

    # The server's own resolution: isometric counts only where the mod snaps
    # it as horizontal hex (v1.2.5), never in v1.1.2.
    grid = _server._mod_grid(state)
    label = f"{state.get('preset')} ({grid.geometry if grid else 'unreadable'})"

    def port_matches_the_mod():
        assert grid is not None, f"settings unreadable: {state}"
        # A spread of positions, plus points either side of every half step,
        # where rounding rules decide the answer.
        step = grid.interval[0]
        points = [[37.0 + i * 211.7, 91.0 + i * 157.3] for i in range(40)]
        points += [[step * k / 2 + d, step * k / 2 - d] for k in range(1, 20) for d in (-0.5, 0.5)]
        mod = u.c.request("get_snap_settings", points=points)["mod_snapped"]
        if not grid.supported:
            assert all(m is None for m in mod), f"the mod snapped {grid.geometry}: {mod[:3]}"
            return f"{label}: the mod does not snap it, and the port applies nothing"
        worst = 0.0
        for point, theirs in zip(points, mod, strict=True):
            ours = snapping.snap(grid, *point)
            gap = max(abs(ours[0] - theirs[0]), abs(ours[1] - theirs[1]))
            assert gap < 0.01, f"{point}: port {ours}, mod {theirs}"
            worst = max(worst, gap)
        like = f" as {grid.snaps_like}" if grid.snaps_like != grid.geometry else ""
        return f"{label}{like}: {len(points)} points agree, worst gap {worst:.4f} woxels"

    u.check(f"snap: port matches the mod on {label}", port_matches_the_mod)

    def placement_lands_where_the_cursor_would():
        if not (state["settings"].get("custom_snap_enabled") and state.get("vanilla_snapping")):
            return "skipped: snapping is not active, so 'auto' rightly moves nothing"
        if grid is None or not grid.supported:
            return f"skipped: {label} is not snapped"
        asset = u.asset("Objects")
        x, y = u.cx + 37.3, u.cy + 91.9
        theirs = u.c.request("get_snap_settings", points=[[x, y]])["mod_snapped"][0]
        from battlemap_mcp import server

        placed = server.place_object(asset, x=x, y=y, snap="auto")
        try:
            got = u.c.request("get_element", id=placed["id"])["position"]
            assert max(abs(got[0] - theirs[0]), abs(got[1] - theirs[1])) < 0.5, (got, theirs)
        finally:
            u.c.request("delete_element", id=placed["id"])
        return f"({x}, {y}) placed at {got}; the mod's cursor would pick {theirs}"

    u.check(
        "snap: snap='auto' places where the user's cursor would",
        placement_lands_where_the_cursor_would,
        needs_dirty=True,
    )

    def every_snapping_tool_lands_on_the_grid():
        if not (state["settings"].get("custom_snap_enabled") and state.get("vanilla_snapping")):
            return "skipped: snapping is not active, so 'auto' rightly moves nothing"
        if grid is None or not grid.supported:
            return f"skipped: {label} is not snapped"
        from battlemap_mcp import server

        def on_grid(point):
            again = snapping.snap(grid, point[0], point[1])
            return max(abs(again[0] - point[0]), abs(again[1] - point[1])) < 0.5

        made: list[int] = []
        try:
            room = server.build_room(
                rect=[u.cx - 1203, u.cy - 707, 1290, 1016], floor="none", snap="auto"
            )
            made.append(room["wall_id"])
            corners = u.c.request("get_element", id=room["wall_id"])["points"]
            assert all(on_grid(p) for p in corners), f"room corners off the grid: {corners}"
            wall = server.draw_wall(
                [[u.cx + 333, u.cy + 17], [u.cx + 911, u.cy + 403]], snap="auto"
            )
            made.append(wall["id"])
            ends = u.c.request("get_element", id=wall["id"])["points"]
            assert all(on_grid(p) for p in ends), f"wall off the grid: {ends}"
            thing = server.place_object(u.asset("Objects"), x=u.cx + 91, y=u.cy + 57)
            made.append(thing["id"])
            server.move_element(thing["id"], x=u.cx + 133, y=u.cy + 171, snap="auto")
            moved = u.c.request("get_element", id=thing["id"])["position"]
            assert on_grid(moved), f"move_element off the grid: {moved}"
            server.move_elements([thing["id"]], dx=137, dy=-61, snap="auto")
            shifted = u.c.request("get_element", id=thing["id"])["position"]
            assert on_grid(shifted), f"move_elements left the grid: {shifted}"
            twin = server.duplicate_object(thing["id"], dx=160, dy=30, snap="auto")
            made.append(twin["id"])
            copy = u.c.request("get_element", id=twin["id"])["position"]
            assert on_grid(copy), f"duplicate off the grid: {copy}"
            light = server.add_light(x=u.cx - 71, y=u.cy + 97, snap="auto")
            made.append(light["id"])
        finally:
            if made:
                u.c.request("delete_elements", ids=made)
        return f"{label}: room, wall, move, group move, duplicate and light all on the grid"

    u.check(
        "snap: every snapping tool lands on the grid",
        every_snapping_tool_lands_on_the_grid,
        needs_dirty=True,
    )


@group("settings")
def settings(u: Uat) -> None:
    """Each is set through the file the panel writes, as a click would, and
    checked by its effect. Any real settings file and environment overrides
    are put back afterwards. Pause, the panel's Undo button and the panel
    showing saved values at startup need a real click or a restart, so they
    are checked by hand; this covers what can be driven without one.
    """
    import json
    import os

    from battlemap_mcp import server, updates, user_settings

    path = user_settings.path()
    saved = path.read_bytes() if path.exists() else None
    env_names = (updates.OPT_OUT, server.CAPTURE_RETENTION_ENV)
    env_saved = {name: os.environ.pop(name, None) for name in env_names}
    notice_saved = updates._result
    tick = [0]

    def write(data: dict | None) -> None:
        if data is None:
            path.unlink(missing_ok=True)
            return
        path.write_text(json.dumps(data), encoding="utf-8")
        # Two writes inside one mtime tick would read as unchanged.
        tick[0] += 1
        stamp = time.time() + tick[0]
        os.utime(path, (stamp, stamp))

    def shipped_defaults():
        write(None)
        report = server.get_status()["settings"]
        assert updates.enabled() is True, "update check off by default"
        assert report["update_check"] == {"value": True, "source": "default"}, report
        assert report["capture_retention"] == {"value": 20, "source": "default"}, report
        assert report["snap_default"] == {"value": "none", "source": "default"}, report
        assert u.c.request("ping")["paused"] is False
        return "update check on, keep 20 captures, place exactly, not paused"

    def retention_prunes_to_the_panel_value():
        write({"capture_retention": 3})
        for _ in range(5):
            server.screenshot()
        kept = len(server._generated_capture_files())
        assert kept == 3, f"panel said 3, {kept} captures kept"
        write({"capture_retention": 5})
        for _ in range(6):
            server.screenshot()
        kept = len(server._generated_capture_files())
        assert kept == 5, f"panel said 5, {kept} captures kept"
        return "3, then 5: the assistant's captures were pruned to each"

    def placements_follow_the_panel_default():
        asset = u.asset("Objects")
        write({"snap_default": "auto"})
        placed = server.place_object(asset, x=u.cx + 37.3, y=u.cy + 91.9)
        try:
            assert placed.get("snap", {}).get("mode") == "auto", placed.get("snap")
        finally:
            u.c.request("delete_element", id=placed["id"])
        write({"snap_default": "none"})
        exact = server.place_object(asset, x=u.cx + 37.3, y=u.cy + 91.9)
        try:
            assert "snap" not in exact, exact.get("snap")
            got = u.c.request("get_element", id=exact["id"])["position"]
            assert abs(got[0] - (u.cx + 37.3)) < 0.5, got
        finally:
            u.c.request("delete_element", id=exact["id"])
        outcome = placed["snap"].get("reason", "applied")
        return f"'Snap to my grid' made snap='auto' ({outcome}); 'exactly' placed as asked"

    def update_notice_follows_the_panel():
        updates._result = {"installed": "1.0.0", "latest": "9.9.9", "url": "u", "message": "m"}
        write({"update_check": True})
        assert "update_available" in server.get_status(), "notice missing with the check on"
        write({"update_check": False})
        assert updates.enabled() is False
        assert "update_available" not in server.get_status(), "notice shown with the check off"
        assert updates.check_now() is None, "a disabled check ran"
        return "notice shown with the check on, hidden (and no check run) with it off"

    def environment_overrides_the_panel():
        write({"update_check": False, "capture_retention": 3})
        os.environ[updates.OPT_OUT] = "1"
        os.environ[server.CAPTURE_RETENTION_ENV] = "9"
        try:
            report = server.get_status()["settings"]
            assert report["update_check"] == {"value": True, "source": "environment"}, report
            assert report["capture_retention"] == {"value": 9, "source": "environment"}, report
        finally:
            for name in env_names:
                os.environ.pop(name, None)
        report = server.get_status()["settings"]
        assert report["capture_retention"] == {"value": 3, "source": "panel"}, report
        return "set environment variables won; unset, the panel applied again"

    def pause_belongs_to_the_user():
        assert u.c.request("get_status")["paused"] is False
        for command, extra in (
            ("tool_action", {"control": "mcp_pause"}),
            ("set_tool_option", {"control": "mcp_pause", "pressed": True}),
        ):
            try:
                u.c.request(command, tool="mcp_bridge", **extra)
            except BridgeCommandError as exc:
                assert "only the user" in str(exc), exc
            else:
                raise AssertionError(f"{command} reached the bridge's own panel")
        assert u.c.request("get_status")["paused"] is False, "a command changed Pause"
        return "not paused, and tool_action/set_tool_option cannot reach the panel"

    try:
        u.check("settings: nothing chosen means the shipped defaults", shipped_defaults)
        u.check(
            "settings: capture retention prunes to the panel's number",
            retention_prunes_to_the_panel_value,
        )
        u.check(
            "settings: placements follow the panel's snap default",
            placements_follow_the_panel_default,
            needs_dirty=True,
        )
        u.check("settings: the update notice follows the panel", update_notice_follows_the_panel)
        u.check("settings: an explicit environment variable wins", environment_overrides_the_panel)
        u.check("settings: Pause belongs to the user", pause_belongs_to_the_user)
    finally:
        if saved is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(saved)
        for name, value in env_saved.items():
            if value is not None:
                os.environ[name] = value
        updates._result = notice_saved


@group("checkpoint")
def checkpoint(u: Uat) -> None:
    """Runtime behavior and validation."""
    from battlemap_mcp.bridge_client import BridgeClient

    def counts():
        return {
            kind: u.c.request("list_elements", kind=kind, limit=1)["total"]
            for kind in ("objects", "walls", "lights")
        }

    def rollback(label):
        """Repeat until done, as the MCP tool does: a pass stops at an object
        an earlier step is still putting back, which happens next frame."""
        kinds: list[str] = []
        for _ in range(200):
            result = u.c.request("rollback_checkpoint", label=label)
            kinds += result["kinds"]
            if not result["continue"]:
                break
            time.sleep(0.05)
        result["kinds"], result["rolled_back"] = kinds, len(kinds)
        return result

    def resolves(ident) -> bool:
        try:
            return u.c.request("get_element", id=ident).get("id") == ident
        except BridgeCommandError:
            return False

    def a_request_rolls_back_whole():
        asset = u.asset("Objects")
        before = counts()
        u.c.request("checkpoint", label="uat-request")
        wall = u.c.request(
            "draw_wall", points=[[u.cx - 900, u.cy + 1700], [u.cx + 900, u.cy + 1700]]
        )["id"]
        light = u.c.request("add_light", x=u.cx, y=u.cy + 1500)["id"]
        batch = u.c.request(
            "place_objects",
            objects=[
                {"asset": asset, "x": u.cx - 300 + i * 300, "y": u.cy + 1400} for i in range(3)
            ],
        )
        made = [wall, light, *batch["ids"]]
        assert counts() == {
            "objects": before["objects"] + 3,
            "walls": before["walls"] + 1,
            "lights": before["lights"] + 1,
        }, counts()
        result = rollback("uat-request")
        time.sleep(0.3)
        assert result["rolled_back"] == 3, result
        assert counts() == before, f"after rollback {counts()} vs before {before}"
        assert not any(resolves(ident) for ident in made), "an element survived the rollback"
        return f"wall, light and 3 objects in 3 calls; one rollback reversed {result['kinds']}"

    u.check(
        "checkpoint: a whole request rolls back in one call",
        a_request_rolls_back_whole,
        needs_dirty=True,
    )

    def another_sessions_edit_blocks_it():
        asset = u.asset("Objects")
        other = BridgeClient()
        assert other.session != u.c.session
        u.c.request("checkpoint", label="uat-foreign")
        theirs = other.request("place_object", asset=asset, x=u.cx + 600, y=u.cy - 900)["id"]
        mine = u.c.request("place_object", asset=asset, x=u.cx + 800, y=u.cy - 900)["id"]
        before = counts()
        try:
            u.c.request("rollback_checkpoint", label="uat-foreign")
        except BridgeCommandError as exc:
            assert "another session" in str(exc), exc
        else:
            raise AssertionError("rolled back over another session's edit")
        assert counts() == before, "a refused rollback changed the map"
        assert resolves(theirs) and resolves(mine)
        u.c.request("delete_elements", ids=[theirs, mine])
        return "refused over another session's placement, and nothing changed"

    def placed_then_deleted_rolls_back():
        """Undoing a delete restores its node on the NEXT frame; a one-frame
        rollback then failed on that node's placement half way through."""
        asset = u.asset("Objects")
        before = counts()
        u.c.request("checkpoint", label="uat-churn")
        made = [
            u.c.request("place_object", asset=asset, x=u.cx - 600 + i * 200, y=u.cy + 900)["id"]
            for i in range(5)
        ]
        for ident in made:
            u.c.request("delete_element", id=ident)
        result = rollback("uat-churn")
        time.sleep(0.3)
        assert result["rolled_back"] == 10 and "stopped" not in result, result
        assert counts() == before, f"after rollback {counts()} vs before {before}"
        assert not any(resolves(ident) for ident in made), "a placement survived"
        return f"5 placed and deleted, then one rollback reversed all {result['rolled_back']} steps"

    u.check(
        "checkpoint: placing then deleting the same objects rolls back",
        placed_then_deleted_rolls_back,
        needs_dirty=True,
    )

    u.check(
        "checkpoint: another session's edit blocks the rollback",
        another_sessions_edit_blocks_it,
        needs_dirty=True,
    )

    def history_limit_is_reported():
        asset = u.asset("Objects")
        cap = u.c.request("get_status")["max_undo"]
        u.c.request("checkpoint", label="uat-evict")
        made, warnings = [], []
        for i in range(cap + 1):
            placed = u.c.request(
                "place_object", asset=asset, x=u.cx - 1200 + (i % 10) * 200, y=u.cy - 1600
            )
            made.append(placed["id"])
            if placed.get("checkpoint_warning"):
                warnings.append(placed["checkpoint_warning"])
        try:
            assert any("more edit" in w for w in warnings), f"no early warning: {warnings[:2]}"
            assert any("can no longer" in w for w in warnings), "no warning once lost"
            try:
                u.c.request("rollback_checkpoint", label="uat-evict")
            except BridgeCommandError as exc:
                assert "no longer reaches" in str(exc), exc
            else:
                raise AssertionError("rolled back past the history limit")
        finally:
            for start in range(0, len(made), 100):
                u.c.request("delete_elements", ids=made[start : start + 100])
        return f"{len(warnings)} warnings over {cap + 1} edits, then the rollback refused"

    u.check(
        "checkpoint: the history limit is warned about, then refused",
        history_limit_is_reported,
        needs_dirty=True,
    )

    def unreversible_edits_are_named():
        asset = u.asset("Objects")
        pool = [u.cx + 1500, u.cy + 1500, 300, 300]
        u.c.request("checkpoint", label="uat-water")
        u.c.request("add_water", rect=pool)
        u.c.request("place_object", asset=asset, x=u.cx + 1200, y=u.cy + 1200)
        try:
            result = rollback("uat-water")
        finally:
            u.c.request("add_water", rect=pool, invert=True)
        assert result["rolled_back"] == 1, result
        assert "add_water" in result["not_reversible"], result
        return f"rolled back {result['kinds']}; not reversible: {result['not_reversible']}"

    u.check(
        "checkpoint: edits outside history are named, not claimed",
        unreversible_edits_are_named,
        needs_dirty=True,
    )


@group("history")
def history(u: Uat) -> None:
    def undo_stack_is_capped():
        status = u.c.request("get_status")
        cap = status["max_undo"]
        asset = u.asset("Objects")
        ids = [
            u.c.request("place_object", asset=asset, x=u.cx + (i % 8) * 128, y=u.cy - 2048)["id"]
            for i in range(cap + 5)
        ]
        depth = u.c.request("get_status")["undo_depth"]
        for ident in ids:
            u.c.request("delete_element", id=ident)
        assert depth == cap, f"{cap + 5} creates left undo_depth {depth}, cap {cap}"
        return f"{cap + 5} creates -> undo_depth {depth}"

    u.check("the undo stack stops at max_undo", undo_stack_is_capped, needs_dirty=True)

    def snapshots_are_capped():
        """Terrain snapshots are bounded by memory, oldest dropped first.

        At 128x128 tiles a terrain edit holds four 512x512 splat images, ~4 MB,
        so a few dozen edits pass the budget; at the UAT map's 35x20 it would
        take hundreds.
        """
        start = u.c.request("get_status")
        w, h = int(start["map_size_woxels"][0] // 256), int(start["map_size_woxels"][1] // 256)
        budget = start["snapshot_budget_bytes"]
        u.c.request("set_map_size", width=128, height=128)
        try:
            marker = u.c.request("place_object", asset=u.asset("Objects"), x=u.cx, y=u.cy - 2560)
            rect = [u.cx - 1024, u.cy - 1024, 512, 512]
            u.c.request("fill_region", rect=rect, slot=1, rate=1.0)
            per_edit = u.c.request("get_status")["snapshot_bytes"]
            assert per_edit > 0, "a terrain edit held no snapshot"
            edits = budget // per_edit + 3
            for i in range(edits - 1):
                u.c.request("fill_region", rect=rect, slot=1 + (i + 1) % 2, rate=1.0)
            status = u.c.request("get_status")
            held, used = status["snapshot_ops"], status["snapshot_bytes"]
            assert used <= budget, f"{used} bytes held, budget {budget}"
            assert held < edits, f"{edits} edits of {per_edit} bytes all kept"
            kinds = [u.c.request("undo")["kind"] for _ in range(held)]
            assert all(kind == "terrain" for kind in kinds), kinds
            # The oldest terrain edits were released, so the next undo reaches
            # the object placed before them rather than a snapshot that is gone.
            reached = u.c.request("undo")
            assert reached["kind"] == "create", f"expected the marker create, got {reached}"
            assert not any(
                e["id"] == marker["id"]
                for e in u.c.request("list_elements", kind="objects", limit=1000)["elements"]
            ), "undoing the create left the marker on the map"
        finally:
            u.c.request("set_map_size", width=w, height=h)
        return (
            f"{edits} edits of {per_edit // 1024} KB -> {held} kept in "
            f"{used // (1024 * 1024)} of {budget // (1024 * 1024)} MB; next undo reached the create"
        )

    u.check(
        "terrain snapshots stay within their memory budget", snapshots_are_capped, needs_dirty=True
    )

    def reads_keep_the_redo_branch():
        placed = u.c.request("place_object", asset=u.asset("Objects"), x=u.cx + 512, y=u.cy - 2560)
        u.c.request("undo")
        before = u.c.request("get_status")
        assert before["redo_depth"] >= 1, before
        reads = [
            ("get_status", {}),
            ("list_elements", {"kind": "objects"}),
            ("get_composition_snapshot", {}),
            ("list_levels", {}),
            ("get_terrain", {"samples": 2}),
            ("get_camera", {}),
            ("get_map_style", {}),
            ("get_tool_layer", {"tool": "ObjectTool"}),
            ("list_assets", {"category": "Objects", "limit": 1}),
            ("get_operation", {}),
        ]
        snapshot = None
        for cmd, params in reads:
            result = u.c.request(cmd, **params)
            if cmd == "get_composition_snapshot":
                snapshot = result
        after = u.c.request("get_status")
        for key in ("undo_depth", "redo_depth", "counts"):
            assert after[key] == before[key], f"{key}: {before[key]} -> {after[key]}"
        assert snapshot and snapshot["grid"]["occupied_cells"] is not None, snapshot
        for kind, facts in snapshot["by_kind"].items():
            assert "count" in facts and "occupied_cells" in facts, (kind, facts)
        redone = u.c.request("redo")
        assert redone["kind"] == "create", redone
        u.c.request("delete_element", id=placed["id"])
        return f"{len(reads)} reads left undo/redo depth and counts unchanged; redo still worked"

    u.check("read-only commands keep the redo branch", reads_keep_the_redo_branch, needs_dirty=True)

    def an_edit_discards_redo():
        first = u.c.request("place_object", asset=u.asset("Objects"), x=u.cx - 512, y=u.cy - 2560)
        u.c.request("undo")
        assert u.c.request("get_status")["redo_depth"] >= 1
        second = u.c.request("place_object", asset=u.asset("Objects"), x=u.cx, y=u.cy - 3072)
        status = u.c.request("get_status")
        u.c.request("delete_element", id=second["id"])
        assert status["redo_depth"] == 0, (
            f"an edit left a stale redo branch: {status['redo_depth']}"
        )
        assert u.c.request("redo")["redone"] is False
        return f"redo branch for {first['id']} dropped by a new edit"

    u.check("a new edit discards the redo branch", an_edit_discards_redo, needs_dirty=True)


@group("asset_search")
def asset_search(u: Uat) -> None:
    """Searching a LARGE library: the case that used to fail outright."""

    def ranked_search_survives_a_pack_library():
        total = u.c.request("list_assets", category="Objects", limit=1)["total"]
        ranked = u.c.request(
            "list_assets", category="Objects", terms=["round", "table"], limit=2000
        )
        assert ranked["assets"], "a terms filter returned nothing on a full catalogue"
        for path in ranked["assets"][:20]:
            lowered = str(path).lower()
            assert "round" in lowered and "table" in lowered, path
        return f"{ranked['matched']} candidates filtered in the bridge out of {total} assets"

    u.check("assets: a ranked search filters in the bridge", ranked_search_survives_a_pack_library)

    def colourability_is_reported_as_indices():
        listing = u.c.request("list_assets", category="Objects", search="carpet", limit=40)
        assert listing["colorable_scanned"], "the scan was skipped; this proves nothing"
        for index in listing["colorable"]:
            assert isinstance(index, int), f"colorable must be indices, got {index!r}"
            assert 0 <= index < len(listing["assets"]), index
        names = vanilla_colourable_assets(listing["assets"], listing["colorable"])
        return (
            f"{len(listing['colorable'])} of {len(listing['assets'])} colourable, e.g. {names[:1]}"
        )

    u.check("assets: colourability is reported as indices", colourability_is_reported_as_indices)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UAT against a live Dungeondraft map")
    parser.add_argument(
        "--map",
        default="",
        help="filename of the THROWAWAY map --dirty may mutate (or set "
        "BATTLEMAP_MCP_DISPOSABLE_MAP)",
    )
    parser.add_argument("--dirty", action="store_true", help="run map-mutating cases")
    parser.add_argument("--group", choices=sorted(GROUPS), help="run one named case group")
    parser.add_argument(
        "--log",
        type=pathlib.Path,
        help="Dungeondraft stdout log (or set BATTLEMAP_MCP_LOG_FILE)",
    )
    args = parser.parse_args(argv)
    if args.log is not None:
        uat_harness.LOG = args.log

    u = Uat(dirty=args.dirty)
    if args.dirty:
        try:
            confirmed = require_disposable_map(u.c, args.map, "uat --dirty")
        except NotDisposable as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(f"mutating map: {confirmed}")
    mode = "DIRTY (mutating)" if args.dirty else "safe subset"
    print(f"UAT against a live Dungeondraft — {mode}\n")
    for name, fns in GROUPS.items():
        if args.group and name != args.group:
            continue
        print(f"[{name}]")
        for fn in fns:
            fn(u)
        print()
    return u.report()


if __name__ == "__main__":
    raise SystemExit(main())
