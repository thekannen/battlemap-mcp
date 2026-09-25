#!/usr/bin/env python3
"""Check color validation, tool restoration after level changes, and saveable nodes.

Run python tools/check_engine_guards.py before testing bridge changes live."""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
MOD = ROOT / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"

# Reads a colour from the request but is validated somewhere else.
COLOUR_DELIBERATE = {
    "_wall_color": "helper; _draw_wall validates before calling it",
    "_place_object_tinted": "reached only through _place_object, which validates",
}

# Frees or rebuilds the current level's node tree.
LEVEL_TEARDOWN = re.compile(r"Global\.World\.(DeleteLevel|CreateLevel|SetLevel)\(")
# Creates a node on the map. Excluded: levels, and the bridge's own settings panel.
CREATES_MAP_NODE = re.compile(r"\.(Create(?!Level\b|ModTool\b|Label\b)\w+)\(")
SAVEABLE_DELIBERATE: dict[str, str] = {
    # The bridge's own panel in Dungeondraft's Settings tools. CreateButton,
    # CreateCheckButton, CreateSeparator and the rest build UI controls in the
    # tool panel, never a node on the map, so there is nothing to save.
    "_register_tool": "ToolPanel Create* calls build panel UI, not map nodes",
}

REARM_DELIBERATE = {
    "_open_map": "ForceOpenMap rebuilds the editor; verified the tool survives",
}


def functions(src: str):
    """(name, body) for every func in the file."""
    for block in re.split(r"\n(?=func )", src):
        m = re.match(r"func (_\w+)", block)
        if m:
            yield m.group(1), block


def main() -> int:
    src = MOD.read_text(encoding="utf-8")
    problems: list[str] = []

    for name, body in functions(src):
        if name.startswith("_debug_"):
            continue  # throwaway probes, excluded like the lifecycle check does

        # --- 1. colour validation
        keys = set(re.findall(r'_color\(\s*req\[\s*"(\w+)"', body))
        keys |= set(re.findall(r'_color\(\s*req\.get\(\s*"(\w+)"', body))
        if keys and name not in COLOUR_DELIBERATE:
            guarded = set(re.findall(r'_color_requested\(\s*req\s*,\s*"(\w+)"', body))
            for call in re.findall(r"_bad_color\(\s*req\s*,\s*\[([^\]]*)\]", body):
                guarded |= set(re.findall(r'"(\w+)"', call))
            if "_modulate_requested(req)" in body:
                guarded.add("modulate")
            for key in sorted(keys - guarded):
                problems.append(
                    f"{MOD.name}: {name} reads req['{key}'] as a colour without "
                    f"validating it — _color() will silently substitute a default"
                )

        # --- 2. re-arm after a level teardown
        if LEVEL_TEARDOWN.search(body) and name not in REARM_DELIBERATE:
            if "_rearm_active_tool()" not in body:
                op = LEVEL_TEARDOWN.search(body).group(1)
                problems.append(
                    f"{MOD.name}: {name} calls {op} without _rearm_active_tool() — "
                    f"the UI's tool keeps ticking against the freed level's Preview"
                )

        # --- 3. every node the bridge creates is marked saveable
        creates = CREATES_MAP_NODE.findall(body)
        if creates and name not in SAVEABLE_DELIBERATE:
            if 'set_meta("preview"' not in body and "_mark_saveable(" not in body:
                problems.append(
                    f"{MOD.name}: {name} calls {creates[0]} without marking the "
                    f"result saveable — each collection's Save() reads its "
                    f"`preview` metadata, and a node without it has broken "
                    f"saving three times (#19, #20, #39)"
                )

        if not name.startswith("_on_panel_") and name != "_panel_write_setting":
            if "_panel_write_setting(" in body:
                problems.append(
                    f"{MOD.name}: {name} writes the panel's settings file; only "
                    f"_on_panel_* handlers, which the user drives, may do that"
                )
            if re.search(r"^\s*_paused\s*=", body, re.MULTILINE):
                problems.append(
                    f"{MOD.name}: {name} changes Pause; only the panel's "
                    f"_on_panel_pause may, so an assistant cannot unpause itself"
                )

    for p in problems:
        print(p)
    if problems:
        print(
            f"\n{len(problems)} problem(s). Either add the guard, or add the "
            f"handler to COLOUR_DELIBERATE / REARM_DELIBERATE / "
            f"SAVEABLE_DELIBERATE with the reason."
        )
        return 1
    print(
        "engine guards: every request colour is validated before use, every "
        "level teardown re-arms the UI's tool, every created node is saveable, "
        "and only the user's panel changes Pause or the panel settings"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
