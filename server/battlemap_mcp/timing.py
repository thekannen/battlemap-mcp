"""Opt-in, local, content-free timing for end-user performance measurement.

Set BATTLEMAP_MCP_TIMING_FILE to a path and every MCP tool call appends one
JSON line: the tool name, wall time, how much of it was spent in bridge
requests, and the size of what went back to the model. Nothing else — no
arguments, results, asset paths, map contents or authentication material — so
a timing file can be shared without leaking the map it measured.

Unset, every function here is a cheap no-op. A failure to write is swallowed:
measurement must never turn a working tool call into an error.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

ENV_VAR = "BATTLEMAP_MCP_TIMING_FILE"

_local = threading.local()
_write_lock = threading.Lock()


def _path() -> str | None:
    return os.environ.get(ENV_VAR) or None


@contextmanager
def tool_call(name: str) -> Iterator[dict[str, Any]]:
    """Measure one tool call. Yields the row so the caller can add result sizes.

    Synchronous tools run one call per worker thread, so bridge requests made
    inside the call are attributed to it through a thread-local.
    """
    if _path() is None:
        yield {}
        return
    row: dict[str, Any] = {
        "event": "tool",
        "tool": name,
        "started": round(time.time(), 3),
        "bridge_requests": 0,
        "bridge_ms": 0.0,
        "bridge_response_bytes": 0,
    }
    previous = getattr(_local, "row", None)
    _local.row = row
    start = time.perf_counter()
    try:
        yield row
    except BaseException as exc:
        row["error"] = type(exc).__name__
        raise
    finally:
        _local.row = previous
        row["total_ms"] = round((time.perf_counter() - start) * 1000, 1)
        row["bridge_ms"] = round(row["bridge_ms"], 1)
        _write(row)


def bridge_request(seconds: float, response_bytes: int) -> None:
    """Attribute one bridge round trip to the tool call in progress, if any."""
    row = getattr(_local, "row", None)
    if row is None or _path() is None:
        return
    row["bridge_requests"] += 1
    row["bridge_ms"] += seconds * 1000
    row["bridge_response_bytes"] += response_bytes


def _write(row: dict[str, Any]) -> None:
    path = _path()
    if path is None:
        return
    line = json.dumps(row, separators=(",", ":")) + "\n"
    try:
        with _write_lock, open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
