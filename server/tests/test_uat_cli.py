"""CLI-level regressions for the live UAT entry point."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_uat_help_is_available_without_a_live_dungeondraft_session():
    """Discovering UAT options must not accidentally execute the acceptance suite."""
    script = Path(__file__).resolve().parents[1] / "tools" / "uat.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0
    assert "--dirty" in completed.stdout
    assert "--log" in completed.stdout
