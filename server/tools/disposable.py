"""Refuse map mutations unless the caller explicitly names the disposable map.

Pass --map NAME or set BATTLEMAP_MCP_DISPOSABLE_MAP; a filename mismatch
stops the run before its first edit."""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "BATTLEMAP_MCP_DISPOSABLE_MAP"


class NotDisposable(RuntimeError):
    """The open map is not the throwaway the caller named."""


SUFFIX = ".dungeondraft_map"


def _name_of(value: str) -> str:
    return Path(str(value).strip()).name


def _key(value: str) -> str:
    """Compare by bare name: the docs say `--map NAME`, and the open map's
    filename carries the extension, so one of the two always has it."""
    name = _name_of(value)
    return name[: -len(SUFFIX)] if name.endswith(SUFFIX) else name


def require_disposable_map(bridge, expected: str | None, what: str = "this suite") -> str:
    """Return the open map's filename, or raise if it is not the named one.

    `expected` is a name, filename or path; only the final component is
    compared and the `.dungeondraft_map` suffix is optional on either side, so
    `--map uat-scratch`, the filename, and a full path all work.
    """
    wanted = expected or os.environ.get(ENV_VAR, "")
    if not wanted.strip():
        raise NotDisposable(
            f"{what} MUTATES the open map: it places, deletes and repaints, and "
            "cannot put back what it changes. Name the throwaway map you intend "
            f"it to run against with --map NAME (or set {ENV_VAR}). "
            "Never point it at work you want to keep."
        )

    status = bridge.request("get_status")
    if not status.get("map_open"):
        raise NotDisposable("no map is open, so there is nothing to check")
    open_path = str(status.get("map_file") or "")
    open_name = _name_of(open_path)
    if not open_name:
        raise NotDisposable(
            "the open map has never been saved, so it cannot be confirmed as "
            f"{_name_of(wanted)}. Save it under a throwaway name first."
        )
    if _key(open_name) != _key(wanted):
        raise NotDisposable(
            f"refusing to run {what}: the open map is {open_name}, not the "
            f"{_name_of(wanted)} you named. Open the throwaway map, or correct --map."
        )
    return open_path
