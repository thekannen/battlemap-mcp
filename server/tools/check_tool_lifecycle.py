#!/usr/bin/env python3
"""Check that bridge tool operations enable and release tools safely.

Validate lifecycle helper usage and reject direct disabling of UI-owned tools."""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
MOD = ROOT / "mod/battlemap-mcp-bridge/scripts/tools/mcp_bridge.gd"

# handler -> why its lifecycle deviates from Enable/…/Disable
DELIBERATE = {
    "_select_elements": (
        "selection must survive for a following tool_action; _detach_node "
        "deselects before removing so it can never outlive its elements"
    ),
    "_prefab_controls": "helper; its callers enable the tool",
    "_wall_color": "read-only property access, verified working without Enable",
    "_add_text": "verified working without Enable",
    "_clear_selection": "only calls DeselectAll",
    "_describe": "read-only GetSelectableType",
    "_prop_detach_error": "read-only GetSelectableType, same classification as _describe",
    "_movable_group": "read-only GetSelectableType, same classification as _describe",
    "_cave_mesh": "helper; enables for its caller, which disables",
    "_set_wizard_design": (
        "presses the wizard's radio and calls OnDesignChange, which sets a "
        "field rather than touching Preview/mesh/selection state; exercised "
        "many times live, verified by generating both designs"
    ),
    "_generator_options": (
        "reads the wizard panel's own controls; only holds a Generator "
        "reference to refuse the picker path. The pickers that DO need the "
        "tool enabled are applied by _generate_dungeon, inside its Enable"
    ),
    "_dig_cave": "_cave_mesh enables CaveBrush for it; its error path disables",
    "_place_pattern": (
        "sets properties on PatternShapeTool and adds shapes through the level, "
        "never touching tool state that needs enabling; passes live on every run"
    ),
    "_detach_node": (
        "only calls DeselectAll, to stop a selection outliving its elements; never enables the tool"
    ),
}


def main() -> int:
    src = MOD.read_text(encoding="utf-8")
    rows = []
    for block in re.split(r"\n(?=func )", src):
        m = re.match(r"func (_\w+)", block)
        if not m:
            continue
        name = m.group(1)
        tools = sorted(set(re.findall(r'Tools\["(\w+)"\]', block)))
        if not tools or name.startswith("_debug_"):
            continue
        # Match the CALL, not the substring. "Enable" also matches
        # EnableTransformBox, which is how _select_elements passed this check
        # while never enabling SelectTool at all — and calling
        # EnableTransformBox on a cold tool crashes Dungeondraft.
        # _enable_tool/_release_tool ARE the Enable/Disable pair: they wrap the
        # engine calls so the "is the UI still holding this tool?" rule lives in
        # one place. Count them as such.
        has_enable = re.search(r"\.Enable\(\)", block) is not None or "_enable_tool(" in block
        has_disable = (
            re.search(r"\.Disable\(\)", block) is not None
            or "_release_tool(" in block
            or "_release_tool_named(" in block
        )
        if has_enable and has_disable:
            continue
        if name in DELIBERATE:
            continue
        rows.append((name, tools, has_enable, has_disable))

    # A bare Disable() outside _release_tool is the crash, not a style point.
    raw = []
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(r"\.Disable\(\)", line) and "func _release_tool" not in line:
            raw.append((i, line.strip()))
    # _release_tool's own body is the one place allowed to call it.
    body = src.split("func _release_tool(editor_tool, was_active : bool) -> void:", 1)
    allowed = set()
    if len(body) == 2:
        offset = body[0].count("\n") + 1
        for j, line in enumerate(body[1].splitlines()[:8], offset):
            if ".Disable()" in line:
                allowed.add(j)
    raw = [r for r in raw if r[0] not in allowed]
    for lineno, text in raw:
        print(f"{MOD.name}:{lineno}: bare Disable() — use _release_tool: {text}")
    if raw:
        print(
            f"\n{len(raw)} bare Disable() call(s). Disabling the tool the UI has "
            f"selected crashes Dungeondraft every frame; route it through "
            f"_release_tool so the ActiveToolName check cannot be skipped."
        )
        return 1

    for name, tools, en, _dis in rows:
        state = "no Enable()" if not en else "no Disable() — leaves the tool active"
        print(f"{MOD.name}: {name} drives {','.join(tools)} — {state}")
    if rows:
        print(
            f"\n{len(rows)} handler(s) to review. Either fix the lifecycle, or add "
            f"an entry to DELIBERATE explaining why it is correct."
        )
        return 1
    print("tool lifecycles: every handler either pairs Enable/Disable or is a reviewed exception")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
