"""Every client session starts its own companion over stdio, and an idle one
exits by itself when its stdin closes. A companion in the middle of a tool
call does not notice until the call returns: measured on macOS, one waiting
on an export outlived its force-killed client by the rest of that call (12 s
of a 15 s wait; export waits allow up to 600). On Windows a child is never
cleaned up with its parent at all. So the companion watches its parent and
leaves the moment it is gone. Nothing is lost by leaving mid-call: the bridge
runs each command whole inside Dungeondraft, and the only thing dropped is a
reply that nobody is left to read.

Set BATTLEMAP_MCP_PARENT_WATCHDOG=0 to turn it off for a launcher that
starts the companion and then exits while keeping its pipes open.
"""

from __future__ import annotations

import os
import sys
import threading
import time

OPT_OUT = "BATTLEMAP_MCP_PARENT_WATCHDOG"
POLL_SECONDS = 2.0


def enabled() -> bool:
    return os.environ.get(OPT_OUT, "1").strip().lower() not in {"0", "false", "no", "off"}


def _exit() -> None:
    # os._exit, not sys.exit: this runs on a watchdog thread, and the server's
    # own threads may be blocked inside a tool call that would never return.
    os._exit(0)


def _watch_posix(parent: int, poll: float) -> None:
    # An orphan is re-parented (to init or launchd), so the parent id changes.
    while os.getppid() == parent:
        time.sleep(poll)
    _exit()


def _image_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def launcher_images(executable: str, argv0: str, base: str) -> set[str]:
    """Images of the Windows launchers that may stand between a client and this interpreter.

    A venv's python.exe is `executable`. A console script such as
    battlemap-mcp.exe is `argv0`, except that pip's launcher script strips
    the .exe from argv[0]: measured, the watchdog missed it until the .exe
    form was added.
    """
    paths = {executable, argv0}
    if argv0 and not os.path.splitext(argv0)[1]:
        paths.add(argv0 + ".exe")
    return {_image_key(path) for path in paths if path} - {_image_key(base)}


# Defined per platform at module level, which is how type checkers narrow
# sys.platform: ctypes.WinDLL exists only on Windows.
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _ProcessEntry(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        )

    def _kernel32():
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        entry = ctypes.POINTER(_ProcessEntry)
        kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, entry)
        kernel32.Process32NextW.argtypes = (wintypes.HANDLE, entry)
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        return kernel32

    def _parent_of(kernel32, pid: int) -> int | None:
        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snapshot in (None, wintypes.HANDLE(-1).value):
            return None
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(_ProcessEntry)
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32ProcessID == pid:
                    return int(entry.th32ParentProcessID)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return None
        finally:
            kernel32.CloseHandle(snapshot)

    def _image_of(kernel32, pid: int) -> str | None:
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            return buffer.value
        finally:
            kernel32.CloseHandle(handle)

    def _client_of(kernel32, parent: int) -> int:
        """Look past this companion's own launchers to the process that started it.

        A venv's python.exe and a console-script .exe are launchers: each starts
        the real interpreter as its child and waits for it, so it outlives a
        killed client. Measured on Windows 11: a `python -m` companion's parent
        was .venv\\Scripts\\python.exe, and it stayed alive after its client
        was killed. A frozen companion has no launcher and its parent is the
        client itself.
        """
        launchers = launcher_images(
            sys.executable, sys.argv[0], getattr(sys, "_base_executable", sys.executable)
        )
        for _ in range(4):
            image = _image_of(kernel32, parent)
            if image is None or _image_key(image) not in launchers:
                break
            grandparent = _parent_of(kernel32, parent)
            if not grandparent:
                break
            parent = grandparent
        return parent

    def _watch_windows(parent: int, poll: float) -> None:
        kernel32 = _kernel32()
        parent = _client_of(kernel32, parent)
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, parent)
        if not handle:
            # The parent is already gone, or may not be opened. Without a handle
            # there is nothing to wait on; do not guess, stdin EOF still applies.
            return
        wait_object_0 = 0
        infinite = 0xFFFFFFFF
        if kernel32.WaitForSingleObject(handle, infinite) == wait_object_0:
            _exit()

else:

    def _watch_windows(parent: int, poll: float) -> None:
        raise OSError("the Windows parent watchdog runs only on Windows")


def start(poll: float = POLL_SECONDS) -> threading.Thread | None:
    """Watch the parent process on a daemon thread; None when turned off."""
    if not enabled():
        return None
    parent = os.getppid()
    target = _watch_windows if sys.platform.startswith("win") else _watch_posix
    thread = threading.Thread(
        target=target, args=(parent, poll), name="parent-watchdog", daemon=True
    )
    thread.start()
    return thread
