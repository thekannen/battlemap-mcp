"""Include the canonical Dungeondraft bridge in source and wheel builds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PAYLOAD_DESTINATION = "battlemap_mcp/bridge_payload/battlemap-mcp-bridge"
SKILLS_DESTINATION = "battlemap_mcp/skills_payload"


class CustomBuildHook(BuildHookInterface):
    """Bundle the bridge while leaving the repository copy authoritative."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Include the checkout's bridge until an sdist has made it in-tree."""
        if version == "editable":
            return

        root = Path(self.root)
        packaged_payload = root / PAYLOAD_DESTINATION
        if packaged_payload.is_dir():
            return

        canonical_payload = root.parent / "mod" / "battlemap-mcp-bridge"
        if not canonical_payload.is_dir():
            raise RuntimeError("Canonical Dungeondraft bridge payload is missing")

        build_data.setdefault("force_include", {})[str(canonical_payload)] = PAYLOAD_DESTINATION

        canonical_skills = root.parent / "skills"
        if not canonical_skills.is_dir():
            raise RuntimeError("Canonical Codex skills payload is missing")
        build_data["force_include"][str(canonical_skills)] = SKILLS_DESTINATION
