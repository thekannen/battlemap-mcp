"""Serve the map-making skills to clients that cannot load them as skills.

The Claude desktop extension (.mcpb) carries only this server, so a desktop
session had the tools without the procedures. The skills already ship inside
the package (`skills_payload`), so the server hands them out itself.

Only files named by the skill index, and the shared references, can be read:
a request is matched against that allowlist, never joined onto a path.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import ValidationError
from .installer import skills_payload_root

INDEX = "skill-index.json"
SHARED = "_shared"


def _root():
    return skills_payload_root()


def _index() -> list[dict[str, Any]]:
    return json.loads(_root().joinpath(INDEX).read_text(encoding="utf-8"))["skills"]


def _description(text: str) -> str:
    """The `description:` line of a SKILL.md's front matter."""
    match = re.match(r"---\n(.*?)\n---", text.replace("\r\n", "\n"), re.DOTALL)
    if match:
        for line in match.group(1).splitlines():
            if line.startswith("description:"):
                return line[len("description:") :].strip()
    return ""


def files() -> dict[str, Any]:
    """Every readable file, keyed by its path relative to the skills folder."""
    root = _root()
    found: dict[str, Any] = {}
    for entry in _index():
        name = entry["name"]
        found[f"{name}/SKILL.md"] = root.joinpath(name, "SKILL.md")
    shared = root.joinpath(SHARED)
    if shared.is_dir():
        for item in shared.iterdir():
            if item.name.endswith(".md") and item.is_file():
                found[f"{SHARED}/{item.name}"] = item
    return found


def _key(requested: str, base: str = "") -> str:
    """Normalise a link as a skill writes it (`../_shared/x.md`) to a key."""
    path = requested.strip().replace("\\", "/")
    parts: list[str] = [p for p in base.split("/")[:-1] if p] if base else []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _links(key: str, text: str, known: dict[str, Any]) -> list[str]:
    """The files this one links to, as keys get_skill(file=...) accepts."""
    out: list[str] = []
    for target in re.findall(r"\]\(([^)#\s]+\.md)\)", text):
        linked = _key(target, key)
        if linked in known and linked != key and linked not in out:
            out.append(linked)
    return out


def listing() -> dict[str, Any]:
    entries = []
    for entry in _index():
        text = _root().joinpath(entry["name"], "SKILL.md").read_text(encoding="utf-8")
        entries.append(
            {
                "name": entry["name"],
                "use_when": _description(text),
                "also_read": entry.get("requires", []),
            }
        )
    return {
        "skills": entries,
        "note": (
            "Read the skill that fits the request with get_skill(name) before "
            "building, then the files it links to with get_skill(file=...)."
        ),
    }


def read(name: str = "", file: str = "") -> str:
    """One skill or shared file as markdown, with what it links to appended."""
    known = files()
    if file:
        key = _key(file)
    else:
        key = f"{name.strip()}/SKILL.md"
    if key not in known:
        names = ", ".join(entry["name"] for entry in _index())
        shared = ", ".join(k for k in known if k.startswith(f"{SHARED}/"))
        raise ValidationError(
            f"no skill file {file or name!r}. Skills: {names}. Shared files: {shared}."
        )
    text = known[key].read_text(encoding="utf-8").replace("\r\n", "\n")
    links = _links(key, text, known)
    footer = f"\n\n---\n[{key}]"
    if links:
        footer += " Linked files, read with get_skill(file=...): " + ", ".join(links)
    return text.rstrip("\n") + footer + "\n"
