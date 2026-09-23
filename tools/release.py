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
MOD_FILES = ("mcp_bridge.ddmod", "scripts/tools/mcp_bridge.gd", "LICENSE")
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
MOD_ARTIFACTS = frozenset({"icons/mcp_bridge.png"})
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
    "installer.py",
    "placement.py",
    "preflight.py",
    "scene.py",
    "server.py",
    "state_paths.py",
    "timing.py",
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
    require_lf(base, MOD_FILES)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"battlemap-mcp-mod-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in MOD_FILES:
            zipped.write(base / name, f"{MOD_ROOT}/{name}")
    return archive


def dependency_pins(system=None, machine=None):
    """Extra pins for the companion's runtime dependencies on this build host.

    cryptography (via mcp -> pyjwt[crypto]) stopped publishing Intel macOS
    wheels at 49.0.0. Building it from source there links the wrong OpenSSL and
    the frozen companion cannot import it, so Intel Macs stay on 48.x.
    """
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Darwin" and machine in ("x86_64", "amd64"):
        return ["cryptography>=48,<49"]
    return []


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


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


def smoke(executable):
    executable = executable.resolve()
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
            [str(executable), "--version"], cwd=scratch, env=env, text=True, timeout=30
        )
        if version.strip() != f"battlemap-mcp {check_versions(ROOT)}":
            raise ValueError(f"Unexpected frozen version: {version}")
        invalid = subprocess.run(
            [str(executable), "invalid-release-smoke-command"],
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
                [str(executable)],
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


def write_shortcuts(bundle, system):
    """Create clickable entry points without changing PATH or installing runtimes."""
    actions = {
        "Connect Codex": "setup --client codex --yes",
        "Connect Claude Code": "setup --client claude-code --yes",
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
    root, out, companion=False, tag=None, sign_identity=None, notary_profile=None
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
        ignore_metadata = shutil.ignore_patterns(*OS_METADATA, "mcp_bridge.png")
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
            run(
                python,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onedir",
                "--name",
                "battlemap-mcp",
                "--collect-all",
                "battlemap_mcp",
                "--collect-data",
                "mcp",
                "--copy-metadata",
                "battlemap-mcp",
                "--distpath",
                work / "dist",
                "--workpath",
                work / "build",
                "--specpath",
                work,
                entry,
                cwd=work,
            )
            bundle = work / "dist/battlemap-mcp"
            for provenance in bundle.rglob("direct_url.json"):
                # pip records the temporary wheel path; it is not runtime metadata.
                provenance.unlink()
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
    verify = commands.add_parser("smoke")
    verify.add_argument("executable", type=Path)
    args = parser.parse_args()
    if args.command == "check":
        print(check_versions(ROOT, args.tag))
    elif args.command == "set-version":
        set_version(ROOT, args.version)
    elif args.command == "smoke":
        smoke(args.executable)
    else:
        for artifact in build(
            ROOT,
            args.out,
            args.companion,
            args.tag,
            args.sign_identity,
            args.notary_profile,
        ):
            print(artifact)


if __name__ == "__main__":
    main()
