"""Validate portable Dungeondraft map-aesthetics skill contracts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED = {
    "battlemap-art-direction": {
        "ping",
        "get_status",
        "list_assets",
        "save_map",
        "screenshot",
    },
    "battlemap-environments": {
        "list_assets",
        "paint_terrain",
        "get_terrain",
        "screenshot",
        "export_map",
    },
    "battlemap-interiors": {
        "list_assets",
        "place_object",
        "save_map",
        "screenshot",
    },
    "battlemap-material-language": {
        "list_assets",
        "get_composition_snapshot",
        "export_map",
        "screenshot",
    },
    "battlemap-lighting-hierarchy": {
        "set_ambient_light",
        "add_light",
        "get_composition_snapshot",
        "export_map",
        "screenshot",
    },
    "battlemap-visual-review": {"screenshot", "export_map", "at most three"},
}
FORBIDDEN = {"guess an asset path", "build blind", "universal object count"}
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)


def check(root: Path) -> list[str]:
    """Return sorted errors for an isolated repository skill tree."""
    root = root.resolve()
    index_path = root / "skills" / "skill-index.json"
    if not index_path.is_file():
        return ["skills/skill-index.json: missing skill index"]

    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"skills/skill-index.json: invalid JSON: {exc.msg}"]

    if index.get("schema") != 1 or not isinstance(index.get("skills"), list):
        return ["skills/skill-index.json: expected schema 1 with a skills list"]

    errors: list[str] = []
    for entry in index["skills"]:
        errors.extend(_check_entry(root, entry))
    return sorted(errors)


def _check_entry(root: Path, entry: Any) -> list[str]:
    """Check one skill-index entry and its Markdown document."""
    if not isinstance(entry, dict):
        return ["skills/skill-index.json: skill entry must be an object"]

    name = entry.get("name")
    relative_path = entry.get("path")
    if not isinstance(name, str) or not isinstance(relative_path, str):
        return ["skills/skill-index.json: skill entry needs name and path"]

    path = (root / relative_path).resolve()
    if not _inside(root, path):
        return [f"{relative_path}: indexed skill path escapes repository root"]
    if not path.is_file():
        return [f"{relative_path}: indexed skill path does not exist"]

    text = path.read_text(encoding="utf-8")
    errors = _check_frontmatter(relative_path, text, name)
    lower_text = text.lower()
    for token in sorted(REQUIRED.get(name, set())):
        if token not in lower_text:
            errors.append(f"{relative_path}: missing required token: {token}")
    for phrase in sorted(FORBIDDEN):
        if phrase in lower_text:
            errors.append(f"{relative_path}: forbidden phrase: {phrase}")
    errors.extend(_check_links(root, path, relative_path, text))
    return errors


def _check_frontmatter(relative_path: str, text: str, expected_name: str) -> list[str]:
    """Validate a minimal, discoverable skill frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return [f"{relative_path}: missing frontmatter opening delimiter"]
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return [f"{relative_path}: missing frontmatter closing delimiter"]

    match = NAME.search("\n".join(lines[1:closing]))
    if match is None:
        return [f"{relative_path}: missing frontmatter name"]
    if match.group(1) != expected_name:
        return [f"{relative_path}: frontmatter name does not match index"]
    return []


def _check_links(root: Path, path: Path, relative_path: str, text: str) -> list[str]:
    """Ensure local Markdown links remain inside the repository and exist."""
    errors: list[str] = []
    for target in LINK.findall(text):
        if target.startswith(("#", "http://", "https://")):
            continue
        destination = (path.parent / target).resolve()
        if not _inside(root, destination):
            errors.append(
                f"{relative_path}: relative reference escapes repository root: {target}"
            )
        elif not destination.exists():
            errors.append(
                f"{relative_path}: relative reference does not exist: {target}"
            )
    return errors


def _inside(root: Path, path: Path) -> bool:
    """Return whether path is contained by root after resolving traversals."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Print deterministic lint diagnostics for the requested repository root."""
    arguments = sys.argv[1:] if argv is None else argv
    root = Path(arguments[0]) if arguments else Path(__file__).resolve().parents[1]
    errors = check(root)
    if errors:
        print("\n".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
