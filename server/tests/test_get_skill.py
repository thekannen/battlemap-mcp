"""get_skill serves the map-making skills to clients that cannot load them.

The desktop extension (.mcpb) carries only this server, so these tests keep
what it serves identical to `skills/`, keep every link inside a skill
reachable, and keep the reader inside its allowlist.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from mcp.client import Client

from battlemap_mcp import server, skills
from battlemap_mcp.errors import ValidationError

SKILLS = Path(__file__).resolve().parents[2] / "skills"


def _canonical() -> dict[str, str]:
    """Every file get_skill should serve, read straight from skills/."""
    index = json.loads((SKILLS / "skill-index.json").read_text(encoding="utf-8"))
    found = {
        f"{entry['name']}/SKILL.md": (SKILLS / entry["name"] / "SKILL.md").read_text("utf-8")
        for entry in index["skills"]
    }
    for path in (SKILLS / "_shared").glob("*.md"):
        found[f"_shared/{path.name}"] = path.read_text("utf-8")
    return found


def _body(served: str) -> str:
    """The served markdown without the footer get_skill appends."""
    return served.rsplit("\n\n---\n[", 1)[0]


def test_every_skill_file_is_served_unchanged():
    canonical = _canonical()
    assert set(skills.files()) == set(canonical)
    for key, text in canonical.items():
        served = server.get_skill(file=key)
        assert _body(served) == text.replace("\r\n", "\n").rstrip("\n"), key


def test_a_skill_reads_by_name_the_same_as_by_file():
    for entry in server.get_skill()["skills"]:
        name = entry["name"]
        assert server.get_skill(name=name) == server.get_skill(file=f"{name}/SKILL.md")


def test_the_listing_names_every_skill_with_when_to_use_it():
    index = json.loads((SKILLS / "skill-index.json").read_text(encoding="utf-8"))
    listed = server.get_skill()["skills"]
    assert [e["name"] for e in listed] == [e["name"] for e in index["skills"]]
    assert all(e["use_when"].startswith("Use when") for e in listed), listed


def test_every_markdown_link_in_a_skill_is_reachable():
    """Skills link to each other and to _shared by relative path."""
    known = set(skills.files())
    broken = []
    for key, text in _canonical().items():
        for target in re.findall(r"\]\(([^)#\s]+\.md)\)", text):
            resolved = skills._key(target, key)
            if resolved not in known:
                broken.append(f"{key} -> {target}")
    assert not broken, broken


def test_a_served_skill_names_the_files_it_links_to():
    served = server.get_skill(name="battlemap-vtt-rebuild")
    footer = served.rsplit("\n\n---\n[", 1)[1]
    assert "_shared/build-loop.md" in footer
    assert "battlemap-visual-review/SKILL.md" in footer
    # Links are written relative to the skill; the footer gives the key back.
    assert "../" not in footer


@pytest.mark.parametrize(
    "file",
    [
        "../../server/battlemap_mcp/server.py",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "skill-index.json",
        "battlemap-interiors/../../README.md",
        "nope.md",
    ],
)
def test_nothing_outside_the_skills_can_be_read(file):
    with pytest.raises(ValidationError):
        server.get_skill(file=file)


def test_an_unknown_name_lists_what_exists():
    with pytest.raises(ValidationError, match="battlemap-interiors"):
        server.get_skill(name="interiors")


def test_a_skill_reaches_the_model_as_plain_markdown():
    """JSON-escaped markdown (one line of \\n) is hard to follow; send text."""

    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool("get_skill", {"name": "battlemap-interiors"})

    result = asyncio.run(run())
    text = result.content[0].text
    assert text.startswith("---\nname: battlemap-interiors")
    assert "\\n" not in text.split("\n", 1)[0]
