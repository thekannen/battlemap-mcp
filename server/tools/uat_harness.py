"""Shared harness for live acceptance checks against a running Dungeondraft.

Check returned values, command logs, and visible map changes together.
Review asynchronous engine messages before attributing them to a command."""

from __future__ import annotations

import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from battlemap_mcp.bridge_client import BridgeClient  # noqa: E402

LOG = pathlib.Path(os.environ.get("BATTLEMAP_MCP_LOG_FILE", "/tmp/dd.log"))
# Keep UAT listings at the bridge's colour-mask scanning cap. The UAT requests
# vanilla_only, so custom packs cannot consume this result page.
COLORABLE_ASSET_SCAN_LIMIT = 200
BAD = (
    "ERROR",
    "SCRIPT ERROR",
    "Unhandled Exception",
    "FATAL",
    "out of bounds",
    "Invalid call",
    "Native Crash",
    "segv",
    'Condition "',
)
# Dungeondraft's own faults, seen firing asynchronously during unrelated commands.
IGNORE_LOG = (
    "ObjectLibraryPanel",
    "Colorable contains missing image",
    "Failed to find tags file",
    "GLD_TEXTURE_INDEX_2D",
    "metadata.has(p_name)",
    # Dungeondraft's own map teardown, seen only during open_map. Prop._ExitTree
    # reads World.get_Level(), which indexes Levels[CurrentLevelId] — and by the
    # time the props leave the tree that list is already empty, so every live
    # prop throws ArgumentOutOfRangeException on the way out. One fault per prop.
    #
    # Not ours: props created through ObjectTool (Dungeondraft's own placement
    # path) throw at exactly the same rate as props the bridge creates directly,
    # 3 for 3 in both cases, and a map with no props throws nothing.
    #
    # Matched as a PAIR so it cannot hide the bridge's own tree surgery.
    # _detach_node/_attach_node also trigger _ExitTree, but with a live map and
    # a populated Levels list — so they never produce the get_Level frame.
    ("Prop._ExitTree", "World.get_Level"),
    "Name: 'Action'",
)


def vanilla_assets(assets: list[str]) -> list[str]:
    """Return assets shipped by Dungeondraft, excluding optional custom packs."""
    return [asset for asset in assets if asset.startswith("res://textures/")]


def vanilla_colourable_assets(assets: list[str], colorable: list) -> list[str]:
    """Return colourable vanilla assets, preserving the catalogue's result order.

    `colorable` is the bridge's list of INDICES into `assets`. Paths are still
    accepted, because an older bridge reported them that way and a mixed pair is
    what a partial upgrade looks like.
    """
    named = set()
    for entry in colorable:
        if isinstance(entry, int) and not isinstance(entry, bool):
            if 0 <= entry < len(assets):
                named.add(assets[entry])
        else:
            named.add(str(entry))
    return [asset for asset in vanilla_assets(assets) if asset in named]


def _existing_map_path(value: object) -> pathlib.Path | None:
    """Return a real map path, never Dungeondraft's unsaved-map sentinel."""
    if not isinstance(value, str) or value in {"", "Null"}:
        return None
    path = pathlib.Path(value)
    return path if path.is_file() else None


def pixel_difference(first: object, second: object) -> tuple[int, int, int, int] | None:
    """Bounding box of every pixel whose colour OR alpha differs, else None.

    Pillow's `getbbox()` on an RGBA image looks at the alpha band alone by
    default, and the difference of two opaque images has zero alpha
    everywhere — so an all-red and an all-green render compared "identical".
    That default is what an export-equality UAT case was first written on.
    """
    from PIL import Image, ImageChops

    def rgba(image: object) -> Image.Image:
        if isinstance(image, Image.Image):
            return image.convert("RGBA")
        with Image.open(image) as opened:  # type: ignore[arg-type]
            return opened.convert("RGBA")

    a, b = rgba(first), rgba(second)
    if a.size != b.size:
        return (0, 0, max(a.width, b.width), max(a.height, b.height))
    return ImageChops.difference(a, b).getbbox(alpha_only=False)


def engine_errors(tail: str) -> list[str]:
    """Lines in `tail` that indicate a real engine fault.

    Matched per BLOCK, not per line. A .NET exception spans several lines and
    names its origin in the stack trace, not on the "Unhandled Exception:" line
    — so line-at-a-time matching reported Dungeondraft's own
    ObjectLibraryPanel._on_AllButton_pressed fault as ours, four times a run,
    despite it being listed above. Blocks are separated by blank lines, which is
    how Godot and Mono format them.
    """
    out: list[str] = []
    for block in tail.split("\n\n"):
        lines = block.splitlines()
        # An entry is a substring, or a tuple of substrings that must ALL be
        # present — some engine noise needs two markers to tell it apart from a
        # fault that matters.
        if any(
            all(part in block for part in ig) if isinstance(ig, tuple) else ig in block
            for ig in IGNORE_LOG
        ):
            continue
        for ln in lines:
            if any(b in ln for b in BAD) and "mcp-bridge" not in ln:
                out.append(ln.strip())
                break
    return out


class Uat:
    def __init__(self, dirty: bool = False):
        self.c = BridgeClient(timeout=20)
        self.dirty = dirty
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.skipped: list[tuple[str, str]] = []
        self.c.request("set_verbose", on=True)
        st = self.c.request("get_status")
        if not st["map_open"]:
            raise SystemExit("no map open — the UAT needs a map")
        self.cx, self.cy = st["map_center"]
        self.original_map_file = _existing_map_path(st.get("map_file"))
        self._colourable: tuple[str | None, str] | None = None
        # Map files the save cases write, removed at the end of the run. Tracked
        # by the exact path save_map returns rather than globbed off a name
        # pattern: a glob in the user's own map folder is one typo away from
        # deleting maps they made by hand.
        self.made_files: list[str] = []

    # -- asset discovery: never hardcode, so this runs on vanilla or with packs
    def asset(self, category: str, search: str = "") -> str | None:
        try:
            r = self.c.request("list_assets", category=category, search=search, limit=1)
        except Exception:
            return None
        return (r.get("assets") or [None])[0]

    # -- colourable asset discovery
    #
    # Colour is baked at placement, so testing it means placing objects. There
    # is no "is this colourable?" query, and hardcoding an asset path would tie
    # the suite to one asset library — so probe: place with a colour and see
    # whether the colour reads back. Vanilla Dungeondraft ships plenty of
    # colourable props, so this must not need an asset pack.
    #
    # Colourable props render RED when untinted (that is the unpainted mask),
    # which is why fabric-ish things are the productive place to look first.
    COLOURABLE_HINTS = ("carpet", "rug", "banner", "tapestry", "curtain", "flag", "cloth", "tent")

    def colourable_asset(self, colour: str = "#2e6db4") -> tuple[str | None, str]:
        """Find an asset that actually accepts a custom colour. Returns (asset, note)."""
        if self._colourable is not None:
            return self._colourable
        tried = 0
        candidates: list[str] = []
        for hint in self.COLOURABLE_HINTS:
            try:
                r = self.c.request("list_assets", category="Objects", search=hint, limit=3)
            except Exception:
                continue
            candidates.extend(r.get("assets") or [])
        try:
            bulk = self.c.request("list_assets", category="Objects", search="", limit=30)
            candidates.extend(bulk.get("assets") or [])
        except Exception:
            pass

        seen: set[str] = set()
        for asset in candidates:
            if asset in seen:
                continue
            seen.add(asset)
            if tried >= 25:
                break
            tried += 1
            try:
                r = self.c.request("place_object", asset=asset, x=self.cx, y=self.cy, color=colour)
            except Exception:
                continue
            got = None
            try:
                got = self.c.request("get_element", id=r["id"]).get("color")
            except Exception:
                # A tinted placement whose id does not resolve is a real defect,
                # but this helper's job is only to find a colourable asset —
                # the colour cases assert on it. Do not let it abort discovery.
                pass
            try:
                self.c.request("delete_element", id=r["id"])
            except Exception:
                pass
            if got and got.lower() == colour.lower():
                self._colourable = (asset, f"found after {tried} probe(s)")
                return self._colourable
        self._colourable = (None, f"no colourable asset in {tried} probed")
        return self._colourable

    # -- saves
    #
    # Dungeondraft saves asynchronously, and while a save is in flight the
    # bridge refuses to mutate the map — edits that land mid-save are dropped
    # from the file. So anything that saves must wait before carrying on, or it
    # spends the next second and a half being correctly refused.
    def wait_for_save(self, timeout: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.c.request("get_status")["saving"]["in_flight"]:
                return True
            time.sleep(0.2)
        return False

    def made_file(self, path: str) -> str:
        """Record a map file this run created, for cleanup in report()."""
        self.made_files.append(path)
        return path

    def cleanup_files(self) -> str:
        active_map = None
        try:
            active_map = _existing_map_path(self.c.request("get_status").get("map_file"))
        except Exception:
            # If the bridge cannot report its current map, retaining every
            # scratch file is safer than leaving Dungeondraft pointing at a
            # deleted one.
            return f"removed 0/{len(self.made_files)} file(s) this run created; " + (
                f"preserved {len(self.made_files)} active map file(s)"
            )

        if active_map is None:
            # A sentinel or stale map path cannot establish that every scratch
            # file is inactive. Keep them all until a later run can identify
            # the current map reliably.
            return f"removed 0/{len(self.made_files)} file(s) this run created; " + (
                f"preserved {len(self.made_files)} active map file(s)"
            )

        if any(active_map == pathlib.Path(path) for path in self.made_files):
            original = self.original_map_file
            if original is not None and original.is_file():
                if self._restore_original_map(original):
                    active_map = None

        removed = 0
        preserved = 0
        for path in self.made_files:
            if active_map is not None and pathlib.Path(path) == active_map:
                preserved += 1
                continue
            try:
                pathlib.Path(path).unlink()
                removed += 1
            except OSError:
                pass
        result = f"removed {removed}/{len(self.made_files)} file(s) this run created"
        if preserved:
            result += f"; preserved {preserved} active map file(s)"
        return result

    def _restore_original_map(self, original: pathlib.Path) -> bool:
        """Return true only after Dungeondraft has actually switched away from a scratch map."""
        try:
            self.c.request("open_map", path=str(original))
        except Exception:
            return False

        deadline = time.monotonic() + getattr(self, "cleanup_restore_timeout", 20.0)
        while True:
            try:
                active = _existing_map_path(self.c.request("get_status").get("map_file"))
            except Exception:
                active = None
            if active == original:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)

    def _log_size(self) -> int:
        try:
            return len(LOG.read_bytes())
        except OSError:
            return 0

    def check(self, name, fn, needs_dirty=False):
        """Run one case. `fn` returns a detail string, or raises to fail."""
        if needs_dirty and not self.dirty:
            self.skipped.append((name, "needs --dirty"))
            return
        pos = self._log_size()
        self.c.request("log_marker", text=name)
        try:
            detail = fn() or ""
        except AssertionError as exc:
            self.failed.append((name, f"assertion: {exc}"))
            print(f"  FAIL  {name}\n          {exc}")
            return
        except Exception as exc:
            self.failed.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"  FAIL  {name}\n          {type(exc).__name__}: {exc}")
            return
        time.sleep(0.3)  # let the engine flush
        tail = LOG.read_bytes()[pos:].decode("utf-8", "replace")
        errs = engine_errors(tail)
        if errs:
            self.failed.append((name, f"engine log: {errs[0].strip()[:120]}"))
            print(f"  DIRTY {name}\n          {detail}\n          LOG! {errs[0].strip()[:120]}")
            return
        self.passed.append(name)
        print(f"  PASS  {name}" + (f"  — {detail}" if detail else ""))

    def rejects(self, _name: str, _cmd: str, /, needs_dirty: bool = False, **params) -> None:
        """A case that PASSES when the bridge refuses the input."""

        def run():
            try:
                res = self.c.request(_cmd, **params)
            except Exception as exc:
                return f"rejected: {str(exc)[:80]}"
            raise AssertionError(f"accepted bad input, returned {res}")

        self.check(_name, run, needs_dirty)

    def report(self) -> int:
        if self.made_files:
            print(f"\ncleanup: {self.cleanup_files()}")
        print(
            f"\n{len(self.passed)} passed, {len(self.failed)} failed, {len(self.skipped)} skipped"
        )
        for n, why in self.skipped:
            print(f"  SKIP  {n} — {why}")
        for n, why in self.failed:
            print(f"  FAIL  {n} — {why}")
        return 1 if self.failed else 0
