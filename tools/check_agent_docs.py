"""Fail when the agent guides drift apart.

`AGENTS.md` and `CLAUDE.md` are the same maintainer guide under two names,
because Codex loads the first and Claude Code loads the second. Keeping them
in sync by discipline did not work: `CLAUDE.md` went on describing `modulate`
as a usable post-placement tint for days after `server.py` began refusing it,
and every other copy of that fact in the repository had already been fixed. The
stale copy is the one that gets auto-loaded into a model's context, so drift is
not a tidiness problem — it briefs an agent with something the server rejects.

`AGENTS.md` is canonical. Edit it, then copy it over `CLAUDE.md`:

    cp AGENTS.md CLAUDE.md
"""

from __future__ import annotations

import sys
from pathlib import Path

CANONICAL = "AGENTS.md"
MIRROR = "CLAUDE.md"


def check(root: Path) -> list[str]:
    """Return diagnostics for the agent guides under the given repository root."""
    errors: list[str] = []
    canonical, mirror = root / CANONICAL, root / MIRROR

    for path in (canonical, mirror):
        if not path.is_file():
            errors.append(f"{path.name}: missing; both agent guides must exist")
    if errors:
        return errors

    # Bytes, not text: a stray BOM or a line-ending flip still means one agent
    # reads something the other does not.
    left, right = canonical.read_bytes(), mirror.read_bytes()
    if left == right:
        return errors

    left_lines = left.decode("utf-8", "replace").splitlines()
    right_lines = right.decode("utf-8", "replace").splitlines()
    errors.append(
        f"{MIRROR} has drifted from {CANONICAL} "
        f"({len(left_lines)} vs {len(right_lines)} lines). "
        f"{CANONICAL} is canonical: make the change there, then `cp {CANONICAL} {MIRROR}`."
    )
    for number, (a, b) in enumerate(zip(left_lines, right_lines), start=1):
        if a != b:
            errors.append(f"  first difference at line {number}:")
            errors.append(f"    {CANONICAL}: {a[:100]}")
            errors.append(f"    {MIRROR}: {b[:100]}")
            break
    else:
        shorter, longer = sorted((len(left_lines), len(right_lines)))
        errors.append(
            f"  identical through line {shorter}; one file has {longer - shorter} extra line(s)"
        )
    return errors


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
