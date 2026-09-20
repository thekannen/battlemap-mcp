"""Read-only destination access checks; never create probes or alter permissions."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


def directory_write_access(destination: Path) -> str:
    """Check the nearest existing directory using the current effective identity.

    Windows opens a directory handle requesting write rights, without writing any
    content. This invokes native access checks instead of os.access's read-only-bit
    approximation. Unknown errors remain explicitly unknown. This is a preflight,
    not a promise: child ACLs, filesystem space and races can still prevent a copy.
    """
    try:
        candidate = destination.absolute()
        while not candidate.exists():
            parent = candidate.parent
            if parent == candidate:
                return "unknown"
            candidate = parent
        if not candidate.is_dir():
            return "denied"
        if os.name == "nt":
            return _windows_directory_access(candidate)
        if os.access not in os.supports_effective_ids:
            return "unknown"
        return (
            "allowed" if os.access(candidate, os.W_OK | os.X_OK, effective_ids=True) else "denied"
        )
    except OSError:
        return "unknown"


def _windows_directory_access(path: Path) -> str:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # OPEN_EXISTING + BACKUP_SEMANTICS opens a directory, creating nothing.
    handle = create(str(path), 0x40000000, 7, None, 3, 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        return "denied" if ctypes.get_last_error() == 5 else "unknown"
    close(handle)
    return "allowed"
