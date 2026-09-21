#!/usr/bin/env python3
"""Run all offline checks, returning nonzero when any check fails.

Use python tools/gate.py --quick to skip slower checks while iterating.
Live acceptance checks run separately against an explicitly named disposable map."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

SERVER = pathlib.Path(__file__).resolve().parents[1]
REPO = SERVER.parent
# The interpreter running this script, unless a server/.venv exists next to it.
# Everything else goes through `PYTHON -m <tool>`: hardcoding a venv's bin/
# directory assumes one particular layout, and the README creates the
# virtualenv at the REPOSITORY root, while Windows uses Scripts/ rather than
# bin/ — either of which made this die with FileNotFoundError before a single
# check ran.
_LOCAL = SERVER / ".venv" / "bin" / "python"
PYTHON = str(_LOCAL) if _LOCAL.exists() else sys.executable

# (label, argv, cwd, slow). Ordered cheapest-first so a typo fails in a second
# rather than after the test suite.
CHECKS: list[tuple[str, list[str], pathlib.Path, bool]] = [
    ("ruff format", [PYTHON, "-m", "ruff", "format", "--check", "."], SERVER, False),
    ("ruff lint", [PYTHON, "-m", "ruff", "check", "."], SERVER, False),
    ("gdscript", [PYTHON, "tools/check_gdscript.py"], SERVER, False),
    ("command contract", [PYTHON, "tools/check_command_contract.py"], SERVER, False),
    ("tool lifecycle", [PYTHON, "tools/check_tool_lifecycle.py"], SERVER, False),
    ("engine guards", [PYTHON, "tools/check_engine_guards.py"], SERVER, False),
    ("skills", [PYTHON, str(REPO / "tools" / "check_skills.py")], SERVER, False),
    ("agent docs", [PYTHON, str(REPO / "tools" / "check_agent_docs.py")], SERVER, False),
    ("types", [PYTHON, "-m", "mypy", "battlemap_mcp"], SERVER, True),
    ("tests", [PYTHON, "-m", "pytest", "-q"], SERVER, True),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip the slow checks")
    args = parser.parse_args()

    failures: list[tuple[str, str]] = []
    for label, argv, cwd, slow in CHECKS:
        if slow and args.quick:
            print(f"  skip  {label}")
            continue
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ok    {label}")
            continue
        print(f"  FAIL  {label}")
        failures.append((label, ((result.stdout or "") + (result.stderr or "")).strip()))

    if not failures:
        print("\nall checks passed")
        return 0

    # Print the reasons AFTER the summary: the whole point is that a failure
    # must be the last thing on screen, not something scrolled past.
    for label, output in failures:
        print(f"\n===== {label} =====")
        print("\n".join(output.splitlines()[-25:]))
    print(f"\n{len(failures)} check(s) FAILED: {', '.join(label for label, _ in failures)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
