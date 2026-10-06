"""Build versioned, allowlisted release artifacts in an isolated environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import threading
import venv
import zipfile
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
MOD_FILES = (
    "mcp_bridge.ddmod",
    "scripts/tools/mcp_bridge.gd",
    "LICENSE",
    "icons/mcp_bridge.png",
)
# Text payload, held to LF. The panel icon is binary: a PNG header itself
# contains a CR byte (\x89PNG\r\n), so it is exempt from require_lf.
MOD_TEXT_FILES = tuple(name for name in MOD_FILES if not name.endswith(".png"))
# Desktop shells drop these into any directory a user browses, at any depth.
OS_METADATA = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", ".AppleDouble"})
# Artifacts the running editor writes back into a payload directory, by path
# relative to that directory. Both these and OS_METADATA are gitignored and are
# never archived, because build_mod writes MOD_FILES explicitly. validate_tree
# used to reject them anyway as unexpected payload, so a macOS checkout whose
# mod/ folder had been opened in Finder, or any checkout Dungeondraft had
# generated its mod icon into, could not package a release at all. The
# allowlist still rejects everything else, which is what guards against a
# stray log or key sitting in the payload directory.
# The panel icon used to be generated INTO this folder at runtime and was
# tolerated here; since #176 it is a real, shipped file drawn by
# tools/make_icon.py, and the bridge only reads it.
MOD_ARTIFACTS: frozenset[str] = frozenset()
MOD_ROOT = "battlemap-mcp-bridge"
SERVER_FILES = (
    "__init__.py",
    "__main__.py",
    "arrangement.py",
    "asset_packs.py",
    "asset_search.py",
    "bridge_client.py",
    "cli.py",
    "client_config.py",
    "errors.py",
    "floorplan.py",
    "handshake.py",
    "pack_contents.py",
    "installer.py",
    "lifecycle.py",
    "placement.py",
    "preflight.py",
    "scene.py",
    "server.py",
    "snapping.py",
    "state_paths.py",
    "timing.py",
    "updates.py",
    "user_settings.py",
    "validation.py",
)
SKILL_FILES = (
    "skill-index.json",
    "_shared/build-loop.md",
    "_shared/review-rubric.md",
    "_shared/style-bible.md",
    *(
        f"battlemap-{name}/SKILL.md"
        for name in (
            "art-direction",
            "composition-audit",
            "environments",
            "interiors",
            "lighting-hierarchy",
            "material-language",
            "visual-review",
        )
    ),
)
VERSION_RE = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"


def python_runtime_license():
    for directory in (Path(sys.base_prefix), Path(sysconfig.get_path("stdlib"))):
        for name in ("LICENSE.txt", "LICENSE"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    raise ValueError("Python runtime license not found")


def versions(root):
    result = {
        "server/pyproject.toml": tomllib.loads(
            (root / "server/pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"],
        "server/battlemap_mcp/__init__.py": re.search(
            r'__version__ = "([^"]+)"',
            (root / "server/battlemap_mcp/__init__.py").read_text(encoding="utf-8"),
        ).group(1),
    }
    for name in (
        f"mod/{MOD_ROOT}/mcp_bridge.ddmod",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
    ):
        path = root / name
        if not path.exists() and name != ".claude-plugin/marketplace.json":
            raise ValueError(f"Missing required version manifest: {name}")
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if "version" in data:
                result[name] = data["version"]
            for plugin in data.get("plugins", []):
                if "version" in plugin:
                    result[name + ":" + plugin["name"]] = plugin["version"]
    return result


def check_versions(root, tag=None):
    found = versions(root)
    if len(set(found.values())) != 1:
        raise ValueError(f"Release version mismatch: {found}")
    version = next(iter(found.values()))
    plugin = json.loads(
        (root / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
    )
    bundle = plugin.get("mcpServers")
    if bundle is not None and bundle != mcpb_url(version):
        raise ValueError(
            f"plugin.json mcpServers is {bundle!r}, not this release's bundle "
            f"{mcpb_url(version)!r}"
        )
    if not re.fullmatch(VERSION_RE, version):
        raise ValueError(f"Invalid version: {version}")
    if tag is not None and tag != "v" + version:
        raise ValueError(f"Release tag {tag!r} does not match v{version}")
    return version


def set_version(root, version):
    if not re.fullmatch(VERSION_RE, version):
        raise ValueError("Invalid version")
    for name in versions(root):
        if ":" in name:
            continue
        path = root / name
        original = path.read_text(encoding="utf-8")
        if path.suffix == ".toml":
            updated = re.sub(
                r'(?m)^version = "[^"]+"', f'version = "{version}"', original, count=1
            )
        elif path.suffix == ".py":
            updated = re.sub(
                r'__version__ = "[^"]+"', f'__version__ = "{version}"', original
            )
        else:
            updated = re.sub(
                r'("version"\s*:\s*")[^"]+',
                lambda m: m.group(1) + version,
                original,
            )
        if name == ".claude-plugin/plugin.json":
            updated = re.sub(
                r'("mcpServers"\s*:\s*")[^"]+',
                lambda m: m.group(1) + mcpb_url(version),
                updated,
            )
        path.write_text(updated, encoding="utf-8", newline="\n")
    market = root / ".claude-plugin/marketplace.json"
    if market.exists():
        data = json.loads(market.read_text(encoding="utf-8"))
        for plugin in data.get("plugins", []):
            if "version" in plugin:
                plugin["version"] = version
        market.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    check_versions(root)


def validate_tree(base, allowed=None, artifacts=frozenset()):
    if base.is_symlink():
        raise ValueError(f"Symlink payload: {base}")
    for path in base.rglob("*"):
        if path.name in OS_METADATA:
            continue
        if path.relative_to(base).as_posix() in artifacts:
            continue
        if path.is_symlink():
            raise ValueError(f"Symlink payload: {path}")
        if (
            path.is_file()
            and allowed is not None
            and path.relative_to(base).as_posix() not in allowed
        ):
            raise ValueError(f"Unexpected payload file: {path.relative_to(base)}")


def require_lf(base, names):
    """Refuse CR bytes, so every host bundles the same payload bytes.

    The companion is frozen on each platform's own checkout while the mod ZIP
    comes from the Linux job. v1.0.0's Windows runner converted to CRLF, and
    `smoke` compared that payload with the same converted checkout, so nothing
    noticed until the installed mod failed the checker. .gitattributes keeps
    these LF; this is what fails the build if it stops doing so.
    """
    for name in names:
        if b"\r" in (base / name).read_bytes():
            raise ValueError(
                f"CRLF line endings in release payload {name}; "
                "check out with the repository's .gitattributes"
            )


def build_mod(root, out, version):
    base = root / "mod" / MOD_ROOT
    validate_tree(base, MOD_FILES, MOD_ARTIFACTS)
    require_lf(base, MOD_TEXT_FILES)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"battlemap-mcp-mod-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in MOD_FILES:
            zipped.write(base / name, f"{MOD_ROOT}/{name}")
    return archive


# The MCP SDK a frozen companion ships, exactly. pyproject allows any 2.x, and
# a release used to take whatever was newest on the day it was built: 1.1.0
# shipped mcp 2.2.0, and a build on 2026-10-05 picked up 2.3.0 unannounced.
# A new SDK can change what a client sees on connect (see handshake.py for
# the cold-start failure the 2026-07-28 protocol era brought), so raise this
# deliberately, and only after a cold-start test in a real client.
MCP_SDK_PINS = ("mcp==2.2.0", "mcp-types==2.2.0")


def dependency_pins(system=None, machine=None):
    """Extra pins for the companion's runtime dependencies on this build host.

    cryptography (via mcp -> pyjwt[crypto]) stopped publishing Intel macOS
    wheels at 49.0.0. Building it from source there links the wrong OpenSSL and
    the frozen companion cannot import it, so Intel Macs stay on 48.x.
    """
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    pins = list(MCP_SDK_PINS)
    if system == "Darwin" and machine in ("x86_64", "amd64"):
        pins.append("cryptography>=48,<49")
    return pins


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


# Windows antivirus false positives.
#
# PyInstaller's prebuilt Windows bootloader is the same file in every
# PyInstaller app, malware included, so heuristic engines score it on sight:
# v1.0.1's companion drew 2/70 on VirusTotal (SecureAge "Malicious", Skyhigh
# "BehavesLike.Win64.Dropper"). Windows builds therefore compile their own
# bootloader and refuse to package the stock one, and the executable carries
# a version resource naming what it is. This is the prebuilt run.exe shipped by
# both the pinned pyinstaller wheel and its sdist.
STOCK_WINDOWS_BOOTLOADER = (
    "c384e3d8007a0117ec61c8ff5c0e9032e398de1a25c3103978e9f02b43ab7145"
)


def compile_windows_bootloader(root, python):
    """Reinstall the pinned PyInstaller from source with a freshly built bootloader.

    Needs a C compiler; GitHub's Windows runners have MSVC.
    """
    requirements = (root / "packaging/build-requirements.txt").read_text()
    (pin,) = (
        line.strip()
        for line in requirements.splitlines()
        if line.strip().lower().startswith("pyinstaller==")
    )
    run(
        python,
        "-m",
        "pip",
        "install",
        "--force-reinstall",
        "--no-deps",
        "--no-binary",
        "pyinstaller",
        pin,
        env={**os.environ, "PYINSTALLER_COMPILE_BOOTLOADER": "1"},
    )
    package = subprocess.run(
        [
            str(python),
            "-c",
            "import os, PyInstaller; print(os.path.dirname(PyInstaller.__file__))",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bootloader = Path(package) / "bootloader/Windows-64bit-intel/run.exe"
    digest = hashlib.sha256(bootloader.read_bytes()).hexdigest()
    if digest == STOCK_WINDOWS_BOOTLOADER:
        raise ValueError("PyInstaller kept its prebuilt Windows bootloader")
    print(f"compiled Windows bootloader: {digest}")
    return digest


def windows_pyinstaller_args(root, work, launcher):
    """What makes the Windows executable identify itself instead of looking
    like every other PyInstaller build: a version resource, the Knownframe
    icon in place of PyInstaller's default (which unsigned malware shares),
    and no UPX packing, another antivirus heuristic."""
    icon = root / "packaging/icon.ico"
    if not icon.is_file():
        raise ValueError(f"Windows icon missing: {icon}")
    version_file = work / "version_info.txt"
    version_file.write_text(windows_version_info(launcher))
    return ["--version-file", version_file, "--icon", icon, "--noupx"]


def windows_version_info(launcher):
    """PyInstaller --version-file text: an unlabelled executable scores worse.

    It names the launcher generation, never the release: the launcher is
    reused across releases, so nothing in it may change per release.
    """
    generation = launcher["generation"]
    numbers = (generation, 0, 0, 0)
    label = f"launcher {generation} (PyInstaller {launcher['pyinstaller']})"
    strings = {
        "CompanyName": "Knownframe",
        "FileDescription": "battlemap-mcp: MCP server for Dungeondraft",
        "FileVersion": label,
        "Comments": (
            "Connects AI assistants to a running Dungeondraft. Runs "
            "battlemap-mcp.pkg from its own folder. "
            "https://github.com/thekannen/battlemap-mcp"
        ),
        "InternalName": "battlemap-mcp",
        "LegalCopyright": "Copyright (c) 2026 Brandon Florian, thekannen. MIT License.",
        "OriginalFilename": "battlemap-mcp.exe",
        "ProductName": "battlemap-mcp",
        "ProductVersion": label,
    }
    table = ", ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    return (
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3F,"
        " flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        f"  kids=[StringFileInfo([StringTable('040904B0', [{table}])]),"
        " VarFileInfo([VarStruct('Translation', [1033, 1200])])],\n"
        ")\n"
    )


# The pinned Windows launcher.
#
# A PyInstaller exe is the bootloader with the whole Python payload appended,
# so every release had a new hash, and the antivirus reputation the last one
# had earned, Microsoft's clearance included, started again from zero. In
# 1.1.0, Microsoft's ML verdict flipped between builds that differed only in
# the PE timestamp. Windows builds therefore keep the payload OUT of the exe
# (append_pkg=False: battlemap-mcp.pkg beside it) and ship the same
# launcher bytes every release, recorded in packaging/windows-launcher.json.
# A launcher only changes on a PyInstaller upgrade, which bumps its
# generation; the bootloader and the .pkg format must come from the same
# PyInstaller, which load_launcher_pin enforces.
LAUNCHER_PIN = "packaging/windows-launcher.json"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def load_launcher_pin(root):
    """Read and check the pinned launcher record. sha256/url are null until
    the first launcher of a generation is published."""
    pin = json.loads((root / LAUNCHER_PIN).read_text(encoding="utf-8"))
    if not isinstance(pin.get("generation"), int) or pin["generation"] < 1:
        raise ValueError(f"{LAUNCHER_PIN}: generation must be a positive integer")
    stamp = pin.get("build_timestamp")
    if not isinstance(stamp, int) or stamp <= 0:
        raise ValueError(f"{LAUNCHER_PIN}: build_timestamp must be an integer")
    requirements = (root / "packaging/build-requirements.txt").read_text()
    (pyinstaller,) = (
        line.strip().split("==", 1)[1]
        for line in requirements.splitlines()
        if line.strip().lower().startswith("pyinstaller==")
    )
    if pin.get("pyinstaller") != pyinstaller:
        raise ValueError(
            f"{LAUNCHER_PIN} is for PyInstaller {pin.get('pyinstaller')}, but the "
            f"build pins {pyinstaller}. A launcher only runs the .pkg format of its "
            "own PyInstaller: bump the generation, clear sha256 and url, and "
            "publish a new launcher."
        )
    digest, url = pin.get("sha256"), pin.get("url")
    if (digest is None) != (url is None):
        raise ValueError(f"{LAUNCHER_PIN}: set sha256 and url together")
    if digest is not None and not SHA256_HEX.fullmatch(digest):
        raise ValueError(f"{LAUNCHER_PIN}: sha256 must be 64 lowercase hex digits")
    if url is not None and not url.startswith("https://github.com/"):
        raise ValueError(f"{LAUNCHER_PIN}: url must be a GitHub release download")
    return pin


def windows_spec(spec):
    """Rewrite a generated spec so the payload ships beside the exe."""
    text = spec.read_text(encoding="utf-8")
    anchor = "    exclude_binaries=True,\n"
    if text.count(anchor) != 1:
        raise ValueError("generated spec has no single EXE(exclude_binaries=True)")
    spec.write_text(
        text.replace(anchor, anchor + "    append_pkg=False,\n"), encoding="utf-8"
    )


def pinned_launcher_bytes(pin, launcher_file=None):
    """The pinned launcher, from a local copy or its release URL, by hash."""
    if launcher_file is not None:
        data = Path(launcher_file).read_bytes()
    else:
        import urllib.request

        with urllib.request.urlopen(pin["url"], timeout=60) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != pin["sha256"]:
        raise ValueError(
            f"pinned launcher hash mismatch: got {digest}, {LAUNCHER_PIN} says "
            f"{pin['sha256']}"
        )
    return data


def pin_windows_launcher(
    bundle, pin, launcher_file=None, require=False, candidate_dir=None
):
    """Swap the freshly built launcher for the pinned one.

    The fresh one is kept in candidate_dir when given: it is what a new
    generation is published from. Returns a short description of what
    shipped.
    """
    executable = bundle / "battlemap-mcp.exe"
    package = bundle / "battlemap-mcp.pkg"
    if not package.is_file():
        raise ValueError("Windows build has no battlemap-mcp.pkg beside the exe")
    built = executable.read_bytes()
    built_digest = hashlib.sha256(built).hexdigest()
    print(f"built Windows launcher: {built_digest} ({len(built)} bytes)")
    if candidate_dir is not None:
        candidate_dir = Path(candidate_dir)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "battlemap-mcp.exe").write_bytes(built)
        (candidate_dir / "SHA256").write_text(
            f"{built_digest}  battlemap-mcp.exe\n", encoding="utf-8"
        )
    if pin["sha256"] is None:
        if require:
            raise ValueError(
                f"{LAUNCHER_PIN} pins no launcher, and this build requires one. "
                "Publish a launcher first; see docs/releases.md."
            )
        print("WARNING: no pinned launcher; shipping the freshly built one")
        return f"unpinned {built_digest}"
    executable.write_bytes(pinned_launcher_bytes(pin, launcher_file))
    same = "identical to" if built_digest == pin["sha256"] else "replacing"
    print(f"pinned Windows launcher {pin['sha256']} ({same} the fresh build)")
    return f"pinned {pin['sha256']}"


# macOS notarization.
#
# Unsigned builds are killed by Gatekeeper the moment they run, and on the
# Terminal path with no message at all -- just SIGKILL and exit 137. That was
# the outcome of the first clean macOS install run, so signing is the fix that
# makes a Mac install work at all.
#
# Credentials never appear here, in the repository, or on a command line. The
# maintainer creates a notarytool keychain profile once:
#
#   xcrun notarytool store-credentials <profile> \
#       --apple-id <id> --team-id <team> --password <app-specific-password>
#
# and this passes only the profile NAME. Signing identity likewise comes from
# the keychain by name.
MACHO_MAGIC = (
    b"\xcf\xfa\xed\xfe",  # 64-bit little-endian
    b"\xce\xfa\xed\xfe",  # 32-bit little-endian
    b"\xca\xfe\xba\xbe",  # universal
)


def is_macho(path):
    """Return whether the file starts with a Mach-O magic number."""
    try:
        with open(path, "rb") as handle:
            return handle.read(4) in MACHO_MAGIC
    except OSError:
        return False


def sign_bundle(bundle, identity):
    """Sign every Mach-O in the bundle, nested first, then the executable.

    Hardened runtime and a secure timestamp are both required for
    notarization; without either, submission is accepted and the result comes
    back Invalid.
    """
    executable = bundle / "battlemap-mcp"
    if not executable.is_file():
        raise ValueError(f"Companion executable missing: {executable}")
    nested = sorted(
        (
            p
            for p in bundle.rglob("*")
            if p.is_file() and not p.is_symlink() and p != executable and is_macho(p)
        ),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for target in [*nested, executable]:
        run(
            "codesign",
            "--force",
            "--timestamp",
            "--options",
            "runtime",
            "--sign",
            identity,
            target,
        )
    # Verify before spending a notarization round trip on a bad signature.
    run("codesign", "--verify", "--strict", "--verbose=2", executable)
    return len(nested) + 1


def notarize_bundle(bundle, out, profile):
    """Submit the signed bundle and wait for Apple's verdict.

    Returns the path of the zip submitted. The ticket is published against the
    signature hashes, so the shipped .tar.gz is covered by it; Gatekeeper looks
    the ticket up online. A loose folder cannot be stapled, so a first run on a
    machine with no network can still be refused -- shipping a .dmg or .pkg is
    what would make it work offline.
    """
    submission = out / f"{bundle.name}-notarize.zip"
    if submission.exists():
        submission.unlink()
    # ditto, not zip: it preserves the symlinks and metadata the signature
    # covers, and a plain zip invalidates them.
    run("ditto", "-c", "-k", "--keepParent", bundle, submission)
    run(
        "xcrun",
        "notarytool",
        "submit",
        submission,
        "--keychain-profile",
        profile,
        "--wait",
    )
    return submission


def validate_companion_links(bundle):
    """Retain native library symlinks only when their targets stay in the bundle."""
    for path in bundle.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(bundle.resolve()):
            raise ValueError(f"Companion symlink escapes archive: {path.name}")


def smoke(executable, via=None):
    """Check a frozen companion's payload, version, CLI and MCP startup.

    via: start it through this command instead, e.g. ["/bin/sh", launch.sh]
    for an MCP bundle; the payload is still checked beside `executable`.
    """
    executable = executable.resolve()
    command = [str(part) for part in via] if via else [str(executable)]
    if executable.suffix.lower() == ".exe" and not via:
        check_windows_launcher(executable)
    payloads = list(executable.parent.rglob("bridge_payload/battlemap-mcp-bridge"))
    if len(payloads) != 1:
        raise ValueError("Frozen bridge payload missing or duplicated")
    payload = payloads[0]
    for name in MOD_FILES:
        if (payload / name).read_bytes() != (
            ROOT / "mod" / MOD_ROOT / name
        ).read_bytes():
            raise ValueError(f"Frozen bridge payload mismatch: {name}")
    for name in SKILL_FILES:
        if (payload.parent.parent / "skills_payload" / name).read_bytes() != (
            ROOT / "skills" / name
        ).read_bytes():
            raise ValueError(f"Frozen skills payload mismatch: {name}")
    with tempfile.TemporaryDirectory(prefix="dd-mcp-smoke-") as scratch:
        env = os.environ.copy()
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(key, None)
        for key in (
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "XDG_CONFIG_HOME",
            "XDG_STATE_HOME",
            "CODEX_HOME",
        ):
            env[key] = scratch
        version = subprocess.check_output(
            [*command, "--version"], cwd=scratch, env=env, text=True, timeout=30
        )
        if version.strip() != f"battlemap-mcp {check_versions(ROOT)}":
            raise ValueError(f"Unexpected frozen version: {version}")
        invalid = subprocess.run(
            [*command, "invalid-release-smoke-command"],
            cwd=scratch,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if invalid.returncode == 0:
            raise ValueError("Frozen CLI incorrectly accepted an invalid command")
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "release-smoke", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
                text=True,
                encoding="utf-8",
                cwd=scratch,
                env=env,
            )
            responses = queue.Queue()

            def read_responses():
                for line in process.stdout:
                    responses.put(line)
                responses.put(None)

            reader = threading.Thread(target=read_responses, daemon=True)
            reader.start()
            try:
                for message in messages:
                    process.stdin.write(json.dumps(message) + "\n")
                    process.stdin.flush()
                    if "id" not in message:
                        continue
                    line = responses.get(timeout=45)
                    if line is None:
                        errors.seek(0)
                        raise ValueError(f"MCP exited before response: {errors.read()}")
                    response = json.loads(line)
                    if response.get("id") != message["id"] or "result" not in response:
                        raise ValueError(f"Invalid MCP response: {response}")
                    if message["method"] == "tools/list" and not response["result"].get(
                        "tools"
                    ):
                        raise ValueError("MCP companion reported no tools")
                process.stdin.close()
                if process.wait(timeout=20) != 0:
                    raise ValueError("MCP companion exited unsuccessfully")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=20)
                process.stdout.close()
                reader.join(timeout=5)


def check_windows_launcher(executable):
    """A Windows bundle is the launcher plus its .pkg, and when a launcher is
    pinned the shipped exe must be exactly it. Smoke runs again on the
    extracted archive, so this also gates what users download."""
    if not executable.with_suffix(".pkg").is_file():
        raise ValueError(
            f"{executable.with_suffix('.pkg').name} missing beside the exe"
        )
    pin = load_launcher_pin(ROOT)
    if pin["sha256"] is not None:
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        if digest != pin["sha256"]:
            raise ValueError(
                f"shipped launcher {digest} is not the pinned {pin['sha256']}"
            )


def write_shortcuts(bundle, system):
    """Create clickable entry points without changing PATH or installing runtimes."""
    actions = {
        "Connect Codex": "setup --client codex --yes",
        "Connect Claude Code": "setup --client claude-code --yes",
        "Connect OpenCode": "setup --client opencode --yes",
        "Check connection": "doctor --live --brief",
    }
    for name, arguments in actions.items():
        if system == "Windows":
            content = (
                "@echo off\nsetlocal DisableDelayedExpansion\n"
                f'"%~dp0battlemap-mcp.exe" {arguments}\n'
                'set "dd_result=%errorlevel%"\n'
                "echo.\npause\nexit /b %dd_result%\n"
            )
            (bundle / f"{name}.cmd").write_text(
                content, encoding="utf-8", newline="\r\n"
            )
        else:
            content = (
                "#!/bin/sh\n"
                'bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1\n'
                f'"$bundle_dir/battlemap-mcp" {arguments}\n'
                'dd_result=$?\nprintf "\\nPress Enter to close..."\nread -r answer\n'
                'exit "$dd_result"\n'
            )
            path = bundle / f"{name}.command"
            path.write_text(content, encoding="utf-8")
            path.chmod(0o755)


def build(
    root,
    out,
    companion=False,
    tag=None,
    sign_identity=None,
    notary_profile=None,
    launcher_file=None,
    require_pinned_launcher=False,
    launcher_candidate=None,
):
    if sign_identity or notary_profile:
        # Check this first: discovering it after a multi-minute build is the
        # kind of thing that trains people to skip signing.
        if platform.system() != "Darwin":
            raise ValueError(
                "signing and notarization are macOS-only; Windows builds are deliberately unsigned"
            )
        if not (sign_identity and notary_profile):
            raise ValueError(
                "pass both --sign-identity and --notary-profile: notarizing an "
                "unsigned bundle always comes back Invalid"
            )
    version = check_versions(root, tag)
    windows = companion and os.name == "nt"
    # Read the pin before a multi-minute build, so a stale one fails first.
    launcher = load_launcher_pin(root) if windows else None
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    artifacts = [build_mod(root, out, version)]
    validate_tree(root / "skills", SKILL_FILES)
    require_lf(root / "skills", SKILL_FILES)
    with tempfile.TemporaryDirectory(prefix="dd-mcp-build-") as temporary:
        work = Path(temporary)
        # Stage explicit source inputs, never freeze the developer environment.
        stage = work / "source"
        package = stage / "server/battlemap_mcp"
        package.mkdir(parents=True)
        unexpected = {
            p.name for p in (root / "server/battlemap_mcp").glob("*.py")
        } - set(SERVER_FILES)
        if unexpected:
            raise ValueError(f"Unexpected server source files: {sorted(unexpected)}")
        for name in SERVER_FILES:
            path = root / "server/battlemap_mcp" / name
            if path.is_symlink():
                raise ValueError(f"Symlink source: {path}")
            shutil.copy2(path, package / path.name)
        for name in ("pyproject.toml", "hatch_build.py"):
            shutil.copy2(root / "server" / name, stage / "server" / name)
        ignore_metadata = shutil.ignore_patterns(*OS_METADATA)
        shutil.copytree(root / "mod", stage / "mod", ignore=ignore_metadata)
        shutil.copytree(root / "skills", stage / "skills", ignore=ignore_metadata)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        run(
            python,
            "-m",
            "pip",
            "install",
            "-r",
            root / "packaging/build-requirements.txt",
        )
        if windows:
            compile_windows_bootloader(root, python)
        run(
            python,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--outdir",
            out,
            stage / "server",
        )
        wheel = out / f"battlemap_mcp-{version.replace('-', '_')}-py3-none-any.whl"
        if not wheel.exists():
            raise ValueError(f"Expected wheel missing: {wheel.name}")
        with zipfile.ZipFile(wheel) as zipped:
            prefix = f"battlemap_mcp/bridge_payload/{MOD_ROOT}/"
            payload_names = {
                name.removeprefix(prefix)
                for name in zipped.namelist()
                if name.startswith(prefix)
            }
            if payload_names != set(MOD_FILES):
                raise ValueError("Wheel bridge payload has unexpected or missing files")
            for name in MOD_FILES:
                if (
                    zipped.read(prefix + name)
                    != (root / "mod" / MOD_ROOT / name).read_bytes()
                ):
                    raise ValueError(f"Wheel bridge payload mismatch: {name}")
        artifacts.append(wheel)
        if companion:
            # A missing cryptography wheel must fail here, not compile a
            # library the frozen companion cannot load.
            run(
                python,
                "-m",
                "pip",
                "install",
                "--only-binary=cryptography",
                wheel,
                *dependency_pins(),
            )
            # Python 3.11 venvs include setuptools. PyInstaller then bundles its
            # pkg_resources runtime hook, which fails to import in the frozen
            # companion; nothing at runtime needs setuptools.
            run(python, "-m", "pip", "uninstall", "--yes", "setuptools")
            entry = work / "launcher.py"
            entry.write_text(
                "from battlemap_mcp.cli import main\n"
                "if __name__ == '__main__':\n    raise SystemExit(main())\n"
            )
            windows_args = (
                windows_pyinstaller_args(root, work, launcher) if windows else []
            )
            run(
                python,
                "-m",
                "PyInstaller.utils.cliutils.makespec",
                "--onedir",
                "--name",
                "battlemap-mcp",
                "--collect-all",
                "battlemap_mcp",
                "--collect-data",
                "mcp",
                "--copy-metadata",
                "battlemap-mcp",
                "--specpath",
                work,
                *windows_args,
                entry,
                cwd=work,
            )
            spec = work / "battlemap-mcp.spec"
            environment_vars = os.environ.copy()
            if windows:
                windows_spec(spec)
                # A fixed PE timestamp, so CI rebuilds a byte-identical
                # launcher while its toolchain is unchanged.
                environment_vars["SOURCE_DATE_EPOCH"] = str(launcher["build_timestamp"])
            run(
                python,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                work / "dist",
                "--workpath",
                work / "build",
                spec,
                cwd=work,
                env=environment_vars,
            )
            bundle = work / "dist/battlemap-mcp"
            for provenance in bundle.rglob("direct_url.json"):
                # pip records the temporary wheel path; it is not runtime metadata.
                provenance.unlink()
            if windows:
                pin_windows_launcher(
                    bundle,
                    launcher,
                    launcher_file,
                    require_pinned_launcher,
                    launcher_candidate,
                )
            shutil.copy2(root / "LICENSE", bundle / "LICENSE")
            python_license = python_runtime_license()
            shutil.copy2(python_license, bundle / "PYTHON-LICENSE.txt")
            shutil.copy2(root / "packaging/INSTALL.txt", bundle / "INSTALL.txt")
            write_shortcuts(bundle, platform.system())
            # Preserve distribution-provided legal notices and record resolved versions.
            collector = root / "packaging/collect_notices.py"
            run(python, collector, bundle)
            inventory = {
                p.relative_to(bundle).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in bundle.rglob("*")
                if p.is_file() and not p.is_symlink()
            }
            (bundle / "INVENTORY.json").write_text(
                json.dumps(inventory, indent=2) + "\n"
            )
            smoke(
                bundle / ("battlemap-mcp.exe" if os.name == "nt" else "battlemap-mcp")
            )
            validate_companion_links(bundle)
            if sign_identity and notary_profile:
                signed = sign_bundle(bundle, sign_identity)
                print(f"signed {signed} Mach-O file(s) with {sign_identity!r}")
                submission = notarize_bundle(bundle, out, notary_profile)
                submission.unlink(missing_ok=True)
                print("notarization accepted")
            system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[
                platform.system()
            ]
            machine = platform.machine().lower()
            arch = {
                "amd64": "x64",
                "x86_64": "x64",
                "arm64": "arm64",
                "aarch64": "arm64",
            }.get(machine)
            if arch is None:
                raise ValueError(f"Unsupported architecture: {machine}")
            stem = out / f"battlemap-mcp-companion-{version}-{system}-{arch}"
            if os.name == "nt":
                artifacts.append(
                    Path(
                        shutil.make_archive(
                            str(stem), "zip", bundle.parent, bundle.name
                        )
                    )
                )
            else:
                archive = Path(str(stem) + ".tar.gz")
                with tarfile.open(archive, "w:gz", dereference=False) as tar:
                    tar.add(bundle, arcname=bundle.name)
                artifacts.append(archive)
    (out / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in artifacts
        ),
        encoding="utf-8",
    )
    return artifacts


# MCP bundle (.mcpb): one file that is both a Claude Desktop extension and the
# MCP server of the Claude Code plugin (#23). It carries every platform's
# companion, because a plugin names ONE bundle URL and Desktop's
# platform_overrides are keyed by OS, not architecture.
#
# Measured in the 2026-09-25 spike: Claude Code's extraction turns symlinks
# into small text files holding the target, which left PyInstaller's
# bootloader unable to load Python; replacing them with real files broke the
# macOS code signature ("code signature invalid"); re-signing that layout with
# the Developer ID worked. So: no symlinks, macOS trees signed AFTER the copy.
MCPB_PLATFORMS = ("windows-x64", "macos-arm64", "macos-x64", "linux-x64")
MCPB_LAUNCHER = """#!/bin/sh
# Start this computer's companion. exec replaces the shell, so the AI client
# stays the companion's parent and its exit watchdog still sees it.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
case "$(uname -s)" in
Darwin)
    # hw.optional.arm64 is 1 on Apple silicon even under Rosetta.
    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = 1 ] && [ -d "$here/macos-arm64" ]; then
        platform=macos-arm64
    else
        platform=macos-x64
    fi ;;
Linux)
    case "$(uname -m)" in
    x86_64 | amd64) platform=linux-x64 ;;
    *) echo "battlemap-mcp: no companion for Linux on $(uname -m)" >&2; exit 1 ;;
    esac ;;
*) echo "battlemap-mcp: no companion for $(uname -s)" >&2; exit 1 ;;
esac
companion="$here/$platform/battlemap-mcp"
if [ ! -f "$companion" ]; then
    echo "battlemap-mcp: this bundle has no $platform companion" >&2
    exit 1
fi
# Some extractors drop the execute bit; the file is ours to fix.
[ -x "$companion" ] || chmod u+x "$companion" 2>/dev/null
exec "$companion" "$@"
"""


def mcpb_name(version):
    return f"battlemap-mcp-{version}.mcpb"


def mcpb_url(version):
    """Where a published release keeps its bundle; plugin.json points here."""
    return (
        "https://github.com/thekannen/battlemap-mcp/releases/download/"
        f"v{version}/{mcpb_name(version)}"
    )


def mcpb_manifest(version, platforms):
    os_of = {"windows": "win32", "macos": "darwin", "linux": "linux"}
    oses = sorted({os_of[name.split("-")[0]] for name in platforms})
    config = {
        "command": "/bin/sh",
        "args": ["${__dirname}/server/launch.sh"],
        "env": {},
    }
    if "windows-x64" in platforms:
        config["platform_overrides"] = {
            "win32": {
                "command": "${__dirname}/server/windows-x64/battlemap-mcp.exe",
                "args": [],
            }
        }
    return {
        "manifest_version": "0.3",
        "name": "battlemap",
        "display_name": "battlemap-mcp",
        "version": version,
        "description": (
            "Build battle maps in a running Dungeondraft: walls, floors, terrain, "
            "lighting and objects, with screenshots so the assistant sees its work."
        ),
        "long_description": (
            "Needs Dungeondraft 1.2.0.1 with the bridge mod installed and a map "
            "open. Ask the assistant to install the bridge: the companion carries "
            "it and shows what it will change before it does."
        ),
        "author": {
            "name": "thekannen",
            "url": "https://github.com/thekannen/battlemap-mcp",
        },
        "homepage": "https://github.com/thekannen/battlemap-mcp",
        "repository": {
            "type": "git",
            "url": "https://github.com/thekannen/battlemap-mcp",
        },
        "license": "MIT",
        "icon": "icon.png",
        "keywords": ["battlemap", "battle map", "ttrpg", "map"],
        "server": {
            "type": "binary",
            "entry_point": "server/launch.sh",
            "mcp_config": config,
        },
        "tools_generated": True,
        "compatibility": {"platforms": oses},
    }


def _replace_symlinks(tree, drop_frameworks=False):
    """Copy each symlink's target in place of the link, deepest first.

    drop_frameworks (macOS): a framework copied without its symlinks has real
    files at its root and in Versions/, and codesign then refuses it as
    "bundle format is ambiguous" (measured 2026-10-05). PyInstaller's bootloader
    loads _internal/Python, a link INTO Python.framework, so that link gets the
    real library and the framework directory is removed. Verified: all 91
    Mach-O files re-signed, and the companion answered MCP initialize.
    """
    links = sorted(
        (p for p in tree.rglob("*") if p.is_symlink()),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    frameworks = [
        p for p in tree.rglob("*.framework") if p.is_dir() and not p.is_symlink()
    ]
    for link in links:
        inside = any(link.is_relative_to(fw) for fw in frameworks)
        if drop_frameworks and inside:
            continue
        target = link.resolve()
        if not target.is_relative_to(tree.resolve()):
            raise ValueError(f"symlink escapes the companion: {link}")
        link.unlink()
        if target.is_dir():
            shutil.copytree(target, link, symlinks=False)
        else:
            shutil.copy2(target, link)
    if drop_frameworks:
        for framework in frameworks:
            shutil.rmtree(framework)
    leftover = [p for p in tree.rglob("*") if p.is_symlink()]
    if leftover:
        raise ValueError(f"symlinks remain after copying: {leftover[:3]}")


def _extract_companion(archive, destination):
    staging = destination.parent / (destination.name + "-staging")
    staging.mkdir()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(staging, filter="data")
    (root,) = [p for p in staging.iterdir() if p.is_dir()]
    root.rename(destination)
    staging.rmdir()


def build_mcpb(
    companions,
    out,
    version,
    platforms=MCPB_PLATFORMS,
    sign_identity=None,
    notary_profile=None,
    allow_unnotarized=False,
):
    """Assemble one .mcpb from the release's companion archives."""
    macos = [p for p in platforms if p.startswith("macos")]
    if macos:
        if platform.system() != "Darwin":
            raise ValueError("a bundle with macOS companions must be built on a Mac")
        if not sign_identity:
            raise ValueError(
                "the macOS companions must be re-signed once their symlinks are "
                "copied; pass --sign-identity"
            )
        if not notary_profile and not allow_unnotarized:
            raise ValueError(
                "pass --notary-profile, or --allow-unnotarized for a local test "
                "bundle that must never be published"
            )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / mcpb_name(version)
    if target.exists():
        raise ValueError(f"{target.name} already exists")
    with tempfile.TemporaryDirectory(prefix="dd-mcp-mcpb-") as temporary:
        work = Path(temporary)
        stage = work / "bundle"
        server_dir = stage / "server"
        server_dir.mkdir(parents=True)
        for name in platforms:
            if name not in MCPB_PLATFORMS:
                raise ValueError(f"unknown platform {name}")
            ext = "zip" if name.startswith("windows") else "tar.gz"
            archive = companions / f"battlemap-mcp-companion-{version}-{name}.{ext}"
            if not archive.is_file():
                raise ValueError(f"companion archive missing: {archive.name}")
            tree = server_dir / name
            _extract_companion(archive, tree)
            _replace_symlinks(tree, drop_frameworks=name.startswith("macos"))
            if name.startswith("macos"):
                signed = sign_bundle(tree, sign_identity)
                print(f"{name}: re-signed {signed} Mach-O file(s)")
                if notary_profile:
                    submission = notarize_bundle(tree, work, notary_profile)
                    submission.unlink(missing_ok=True)
                    print(f"{name}: notarization accepted")
        launcher = server_dir / "launch.sh"
        launcher.write_text(MCPB_LAUNCHER, encoding="utf-8", newline="\n")
        launcher.chmod(0o755)
        shutil.copy2(root_icon(), stage / "icon.png")
        (stage / "manifest.json").write_text(
            json.dumps(mcpb_manifest(version, platforms), indent=2) + "\n",
            encoding="utf-8",
        )
        partial = work / target.name
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(stage.rglob("*")):
                if path.is_dir():
                    continue
                info = zipfile.ZipInfo.from_file(
                    path, path.relative_to(stage).as_posix()
                )
                # Keep the Unix mode, execute bits included: the extractors
                # that honour it then need no chmod.
                info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as source, bundle.open(info, "w") as sink:
                    shutil.copyfileobj(source, sink, 1024 * 1024)
        shutil.move(str(partial), target)
    smoke_mcpb(target)
    return target


def root_icon():
    icon = ROOT / "mod" / MOD_ROOT / "icons/mcp_bridge.png"
    if not icon.is_file():
        raise ValueError(f"bundle icon missing: {icon}")
    return icon


def smoke_mcpb(bundle_path):
    """Unpack a bundle the way a client does and start this computer's companion."""
    with tempfile.TemporaryDirectory(prefix="dd-mcp-mcpb-smoke-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(bundle_path) as bundle:
            bundle.extractall(root)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("version") != check_versions(ROOT):
            raise ValueError(
                f"bundle version {manifest.get('version')} is not this release"
            )
        if any(p.is_symlink() for p in root.rglob("*")):
            raise ValueError("bundle contains symlinks")
        system = platform.system()
        if system == "Windows":
            executable = root / "server/windows-x64/battlemap-mcp.exe"
            if executable.is_file():
                smoke(executable)
                return
        else:
            native = {
                ("Darwin", "arm64"): "macos-arm64",
                ("Darwin", "x86_64"): "macos-x64",
                ("Linux", "x86_64"): "linux-x64",
            }.get((system, platform.machine()))
            executable = root / "server" / str(native) / "battlemap-mcp"
            if native and executable.is_file():
                # zipfile drops the mode bits, as some clients' extractors do:
                # the launcher has to cope, so it is not helped here.
                smoke(executable, via=["/bin/sh", root / "server/launch.sh"])
                return
        print("bundle carries no companion for this computer; not started")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--tag")
    bump = commands.add_parser("set-version")
    bump.add_argument("version")
    package = commands.add_parser("build")
    package.add_argument("--out", type=Path, required=True)
    package.add_argument("--companion", action="store_true")
    package.add_argument(
        "--sign-identity",
        default=os.environ.get("DD_SIGN_IDENTITY"),
        help=(
            "Developer ID Application identity name or hash, from "
            "`security find-identity -v -p codesigning`. macOS only. "
            "Defaults to $DD_SIGN_IDENTITY."
        ),
    )
    package.add_argument(
        "--notary-profile",
        default=os.environ.get("DD_NOTARY_PROFILE"),
        help=(
            "notarytool keychain profile NAME created by "
            "`xcrun notarytool store-credentials`. No secret is read or "
            "passed here. Defaults to $DD_NOTARY_PROFILE."
        ),
    )
    package.add_argument("--tag")
    package.add_argument(
        "--launcher",
        type=Path,
        help=(
            "Windows: a local copy of the pinned launcher, used instead of "
            "downloading it. Its hash is still checked."
        ),
    )
    package.add_argument(
        "--require-pinned-launcher",
        action="store_true",
        help="Windows: fail unless packaging/windows-launcher.json pins a launcher.",
    )
    package.add_argument(
        "--launcher-candidate",
        type=Path,
        help="Windows: keep the freshly built launcher and its hash here.",
    )
    verify = commands.add_parser("smoke")
    verify.add_argument("executable", type=Path)
    bundle = commands.add_parser(
        "mcpb", help="assemble the MCP bundle from the release's companion archives"
    )
    bundle.add_argument("--companions", type=Path, required=True)
    bundle.add_argument("--out", type=Path, required=True)
    bundle.add_argument("--tag")
    bundle.add_argument("--platform", action="append", choices=MCPB_PLATFORMS)
    bundle.add_argument("--sign-identity", default=os.environ.get("DD_SIGN_IDENTITY"))
    bundle.add_argument("--notary-profile", default=os.environ.get("DD_NOTARY_PROFILE"))
    bundle.add_argument(
        "--allow-unnotarized",
        action="store_true",
        help="local test bundle only; never publish one",
    )
    args = parser.parse_args()
    if args.command == "check":
        print(check_versions(ROOT, args.tag))
    elif args.command == "set-version":
        set_version(ROOT, args.version)
    elif args.command == "smoke":
        smoke(args.executable)
    elif args.command == "mcpb":
        print(
            build_mcpb(
                args.companions,
                args.out,
                check_versions(ROOT, args.tag),
                tuple(args.platform or MCPB_PLATFORMS),
                args.sign_identity,
                args.notary_profile,
                args.allow_unnotarized,
            )
        )
    else:
        for artifact in build(
            ROOT,
            args.out,
            args.companion,
            args.tag,
            args.sign_identity,
            args.notary_profile,
            args.launcher,
            args.require_pinned_launcher,
            args.launcher_candidate,
        ):
            print(artifact)


if __name__ == "__main__":
    main()
