"""Bridge payload discovery for Dungeondraft installation support."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from importlib import resources
from pathlib import Path
from shutil import copytree, move, rmtree
from typing import Any

from .bridge_client import PROTOCOL_VERSION, BridgeClient
from .errors import BridgeError


class InstallConflictError(RuntimeError):
    """Raised when an existing bridge would be overwritten without consent."""


@dataclass(frozen=True)
class InstallPlan:
    """A write-free description of a requested bridge installation."""

    destination: Path
    actions: tuple[str, ...]
    requires_force: bool
    now: datetime
    records_path: Path


@dataclass(frozen=True)
class InstallResult:
    """The filesystem outcome of an applied installation plan."""

    changed: bool
    destination: Path
    backup_destination: Path | None


@dataclass(frozen=True)
class CodexSkillsInstallPlan:
    """A write-free description of an included Codex skill installation."""

    destination: Path
    source_directories: tuple[Path, ...]
    now: datetime


@dataclass(frozen=True)
class CodexSkillsInstallResult:
    """The filesystem outcome of installing the included Codex skills."""

    destination: Path
    installed: tuple[Path, ...]
    backups: tuple[Path, ...]
    # Existing skills left in place (no --force) that differ from this version.
    kept: tuple[Path, ...] = ()


@dataclass(frozen=True)
class DoctorReport:
    """A non-mutating health report for an installed bridge."""

    destination: Path
    status: str
    recommended_action: str


@dataclass(frozen=True)
class LogEvidence:
    """Historical evidence only; never correlated with a running process."""

    status: str
    path: Path | None = None
    mod_path: str | None = None
    protocol: int | None = None
    mod_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class LiveIdentity:
    """Result of an explicitly requested authenticated, read-only ping."""

    status: str
    detail: str
    bridge_root: str | None = None
    process_id: int | None = None
    bridge_sha256: str | None = None


def latest_log_evidence(data_dir: Path) -> LogEvidence:
    """Inspect at most the newest log's final 256 KiB without trusting old successes."""
    logs = data_dir / "logs"
    try:
        candidates = [
            (path.stat().st_mtime_ns, path)
            for path in logs.iterdir()
            if path.is_file() and path.suffix.lower() == ".log"
        ]
        if not candidates:
            return LogEvidence("no logs")
        _, newest = max(candidates, key=lambda item: (item[0], str(item[1])))
    except OSError:
        return LogEvidence("logs unavailable")
    try:
        with newest.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 256 * 1024))
            text = stream.read(256 * 1024).decode("utf-8", errors="replace")
    except OSError:
        return LogEvidence("unreadable", path=newest)
    mod_path = None
    protocol = None
    mod_paths: list[str] = []
    for line in text.splitlines():
        if line.strip() == "Mods refreshed.":
            mod_paths.clear()
            mod_path = None
            protocol = None
        found = re.search(r"Battlemap MCP Bridge mod found in (.+)", line)
        if found:
            if protocol is not None:
                mod_paths.clear()
            mod_path = found.group(1).strip()
            if mod_path not in mod_paths:
                mod_paths.append(mod_path)
            # A later mod load invalidates any earlier listening message.
            protocol = None
        listening = re.search(r"\[mcp-bridge\] listening on [^\r\n]+ \(protocol v(\d+)\)", line)
        if listening:
            value = listening.group(1)
            protocol = int(value) if len(value) <= 6 else None
    ambiguous = len(mod_paths) > 1
    return LogEvidence(
        "ambiguous discovery"
        if ambiguous
        else ("historical" if mod_path and protocol is not None else "missing evidence"),
        newest,
        None if ambiguous else mod_path,
        protocol,
        tuple(mod_paths),
    )


def live_bridge_identity() -> LiveIdentity:
    """Compare authenticated running source with this package, independent of logs."""
    script = Path(payload_root()) / "scripts" / "tools" / "mcp_bridge.gd"
    try:
        source = script.read_bytes().decode("utf-8").replace("\r", "")
    except (OSError, UnicodeError):
        return LiveIdentity("unverified", "Packaged bridge source could not be read.")
    expected = hashlib.sha256(source.encode("utf-8")).hexdigest()
    try:
        result = BridgeClient().request("ping")
    except (BridgeError, OSError, ValueError) as exc:
        return LiveIdentity("unavailable", f"Authenticated ping failed ({type(exc).__name__}).")
    if not isinstance(result, dict) or result.get("pong") is not True:
        return LiveIdentity("unverified", "Ping did not return the expected pong response.")
    root = result.get("bridge_root")
    pid = result.get("process_id")
    digest = result.get("bridge_sha256")
    identity = LiveIdentity(
        "unverified",
        "Running bridge did not report a valid source identity.",
        root if isinstance(root, str) and Path(root).is_absolute() else None,
        pid if type(pid) is int and pid > 0 else None,
        digest if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) else None,
    )
    if result.get("protocol") != PROTOCOL_VERSION:
        return replace(
            identity, status="mismatch", detail="Running protocol differs from this package."
        )
    if identity.bridge_sha256 is None:
        return identity
    if digest != expected:
        return replace(
            identity,
            status="mismatch",
            detail="Running source differs from this package; reinstall and restart Dungeondraft.",
        )
    return replace(
        identity,
        status="current",
        detail="Authenticated running source and protocol match this package.",
    )


def payload_root():
    """Return the bridge payload from a package or authoritative source tree."""
    packaged = resources.files("battlemap_mcp").joinpath("bridge_payload/battlemap-mcp-bridge")
    if packaged.is_dir():
        return packaged

    return Path(__file__).resolve().parents[2] / "mod" / "battlemap-mcp-bridge"


def skills_payload_root():
    """Return the bundled Codex skill directories and shared references."""
    packaged = resources.files("battlemap_mcp").joinpath("skills_payload")
    if packaged.is_dir():
        return packaged

    return Path(__file__).resolve().parents[2] / "skills"


def default_state_dir() -> Path:
    """Return the platform configuration root, outside Dungeondraft's data."""
    home = Path.home()
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return home / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))


def dungeondraft_data_dir(
    *,
    _platform: str | None = None,
    _home: Path | None = None,
    _appdata: Path | None = None,
) -> Path:
    """Where Dungeondraft keeps its config.ini, its user data and its default mods folder."""
    platform_name = _platform if _platform is not None else sys.platform
    home = _home if _home is not None else Path.home()
    if platform_name.startswith("win"):
        appdata = _appdata or Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return appdata / "Dungeondraft"
    if platform_name == "darwin":
        return home / "Library" / "Application Support" / "Dungeondraft"
    return home / ".local" / "share" / "Dungeondraft"


def configured_mods_dir(config_path: Path) -> Path | None:
    """The mods folder Dungeondraft is set to load, read from its own config.ini.

    The file is Godot's ConfigFile format: values are Godot literals, and other
    sections hold multi-line dictionaries that configparser rejects outright,
    so only the one key is read, by hand.
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]") and "=" not in line:
            section = line[1:-1].strip()
            continue
        if section != "Mods":
            continue
        match = re.match(r'mods_directory\s*=\s*"((?:[^"\\]|\\.)*)"\s*$', line)
        if match:
            value = re.sub(r"\\(.)", r"\1", match.group(1)).strip()
            return Path(value) if value else None
    return None


def candidate_mods_dirs(
    *,
    _platform: str | None = None,
    _home: Path | None = None,
    _appdata: Path | None = None,
    _program_files: Path | None = None,
) -> list[Path]:
    """Suggest the active Dungeondraft mods directory without creating it.

    The folder Dungeondraft is configured to load always comes first; the
    platform conventions after it are only fallbacks for an unconfigured
    install.
    """
    platform_name = _platform if _platform is not None else sys.platform
    home = _home if _home is not None else Path.home()
    if platform_name.startswith("win"):
        program_files = _program_files or Path(
            os.environ.get("ProgramW6432", os.environ.get("ProgramFiles", r"C:\\Program Files"))
        )
        installed_mods = program_files / "Dungeondraft" / "mods"
        appdata = _appdata or Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates = [appdata / "Dungeondraft" / "mods"]
        if installed_mods.is_dir():
            candidates.insert(0, installed_mods)
    elif platform_name == "darwin":
        candidates = [home / "Library" / "Application Support" / "Dungeondraft" / "mods"]
    else:
        candidates = [home / ".local" / "share" / "Dungeondraft" / "mods"]

    config = (
        dungeondraft_data_dir(_platform=platform_name, _home=home, _appdata=_appdata) / "config.ini"
    )
    configured = configured_mods_dir(config)
    if configured is not None:
        candidates = [configured] + [path for path in candidates if path != configured]
    return candidates


def default_mods_dir() -> Path:
    """Choose the configured directory, or an existing platform fallback."""
    configured = configured_mods_dir(dungeondraft_data_dir() / "config.ini")
    if configured is not None:
        return configured
    candidates = candidate_mods_dirs()
    return next((path for path in candidates if path.is_dir()), candidates[0])


def codex_skills_dir() -> Path:
    """Return Codex's user-scoped skill directory without creating it."""
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "skills"


def claude_code_skills_dir() -> Path:
    """Return Claude Code's user skills directory without creating it."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "skills"


def inspect_skills(destination: Path) -> dict[str, str]:
    """Compare every bundled file, including shared references, without writing."""
    source = Path(skills_payload_root())
    return {
        directory.name: _skill_state(directory, destination / directory.name)
        for directory in sorted(path for path in source.iterdir() if path.is_dir())
    }


def _skill_state(directory: Path, target: Path) -> str:
    """Compare one bundled skill folder with an installed copy."""
    try:
        files = [path for path in directory.rglob("*") if path.is_file()]
        if not target.is_dir() or any(
            not (target / path.relative_to(directory)).is_file() for path in files
        ):
            return "missing or incomplete"
        if any(
            _content_digest(path) != _content_digest(target / path.relative_to(directory))
            for path in files
        ):
            return "differs from bundled version"
        return "current"
    except OSError:
        return "unreadable"


def plan_install(mods_dir: Path, now: datetime, *, state_dir: Path) -> InstallPlan:
    """Describe a fresh bridge installation without touching the filesystem."""
    destination = mods_dir / "battlemap-mcp-bridge"
    requires_force = destination.exists()
    return InstallPlan(
        destination=destination,
        actions=("replace existing bridge",) if requires_force else ("install bridge",),
        requires_force=requires_force,
        now=now,
        records_path=state_dir / "battlemap-mcp" / "installs.json",
    )


def apply_install(plan: InstallPlan, *, force: bool) -> InstallResult:
    """Copy the bridge payload while keeping backups outside Dungeondraft's mods folder."""
    backup_destination = None
    legacy_backups = tuple(
        sorted(plan.destination.parent.glob(f"{plan.destination.name}.backup-*"))
    )
    state_backups_dir = plan.records_path.parent / "backups" / _destination_token(plan.destination)
    legacy_destinations = tuple(state_backups_dir / backup.name for backup in legacy_backups)
    if any(destination.exists() for destination in legacy_destinations):
        raise InstallConflictError(
            "A bridge backup already exists in the installer state directory"
        )

    if plan.destination.exists():
        if not force:
            raise InstallConflictError("Existing bridge requires --force to replace")

        backup_destination = state_backups_dir / (
            f"{plan.destination.name}.backup-{plan.now.strftime('%Y%m%dT%H%M%SZ')}"
        )
        if backup_destination.exists():
            raise InstallConflictError(f"Backup already exists: {backup_destination}")

    # Stage outside mod discovery before moving any existing installation.
    plan.records_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="bridge-stage-", dir=plan.records_path.parent
    ) as staging:
        staged = Path(staging) / "payload"
        copytree(Path(payload_root()), staged)
        restoring: list[tuple[Path, Path]] = []
        owned_backups: list[tuple[Path, Path]] = []
        source_mutation_started = False
        destination_removal_started = False
        destination_removed = False
        installed = False
        try:
            if legacy_backups or backup_destination is not None:
                state_backups_dir.mkdir(parents=True, exist_ok=True)
            pairs = list(zip(legacy_backups, legacy_destinations, strict=True))
            if backup_destination is not None:
                pairs.append((plan.destination, backup_destination))
            # Verify every backup before deleting anything, including across volumes.
            for original, backup in pairs:
                backup.mkdir()
                owned_backups.append((original, backup))
                copytree(original, backup, dirs_exist_ok=True)
                if _file_hashes(original) != _file_hashes(backup):
                    raise OSError(f"Backup verification failed: {backup}")
            for original, backup in pairs:
                source_mutation_started = True
                if original == plan.destination:
                    destination_removal_started = True
                else:
                    restoring.append((original, backup))
                rmtree(original)
                if original == plan.destination:
                    destination_removed = True
            plan.destination.parent.mkdir(parents=True, exist_ok=True)
            # Only clean up a destination we exclusively created.
            plan.destination.mkdir()
            installed = True
            copytree(staged, plan.destination, dirs_exist_ok=True)
            _record_install(plan)
        except Exception as exc:
            if not source_mutation_started:
                # Only discard backups exclusively claimed by this transaction.
                for _, backup in reversed(owned_backups):
                    rmtree(backup)
                if installed and plan.destination.exists():
                    rmtree(plan.destination)
                raise
            if installed and plan.destination.exists():
                rmtree(plan.destination)
            if destination_removal_started and backup_destination is not None:
                if installed or not destination_removed or not plan.destination.exists():
                    copytree(backup_destination, plan.destination, dirs_exist_ok=True)
            for original, backup in reversed(restoring):
                copytree(backup, original, dirs_exist_ok=True)
            # Include prepared legacy copies whose removal was never reached.
            # A failed restore above leaves every recovery copy intact.
            for original, backup in reversed(owned_backups):
                if original == plan.destination and destination_removal_started:
                    continue
                if _file_hashes(original) != _file_hashes(backup):
                    raise OSError(f"Backup restoration verification failed: {backup}") from exc
                rmtree(backup)
            raise
    return InstallResult(
        changed=True,
        destination=plan.destination,
        backup_destination=backup_destination,
    )


def plan_codex_skills_install(destination: Path, now: datetime) -> CodexSkillsInstallPlan:
    """Describe copying the complete bundled skill set without mutating Codex."""
    source_directories = tuple(
        sorted(path for path in Path(skills_payload_root()).iterdir() if path.is_dir())
    )
    return CodexSkillsInstallPlan(
        destination=destination,
        source_directories=source_directories,
        now=now,
    )


def apply_codex_skills_install(
    plan: CodexSkillsInstallPlan, *, force: bool
) -> CodexSkillsInstallResult:
    """Copy bundled skills, preserving replacements outside Codex's skill discovery path."""
    destinations = tuple(plan.destination / source.name for source in plan.source_directories)
    selected = tuple(
        (source, destination)
        for source, destination in zip(plan.source_directories, destinations, strict=True)
        if force or not destination.exists()
    )
    existing_destinations = tuple(
        destination for _, destination in selected if destination.exists()
    )
    backups_dir = plan.destination.parent / "backups" / "battlemap-mcp"
    backups = tuple(
        backups_dir / f"{destination.name}.backup-{plan.now.strftime('%Y%m%dT%H%M%SZ')}"
        for destination in existing_destinations
    )
    legacy_backups = tuple(
        backup
        for source in plan.source_directories
        for backup in sorted(plan.destination.glob(f"{source.name}.backup-*"))
    )
    legacy_destinations = tuple(backups_dir / backup.name for backup in legacy_backups)
    if any(backup.exists() for backup in (*backups, *legacy_destinations)):
        raise InstallConflictError("A skill backup already exists")

    if legacy_backups or backups:
        backups_dir.mkdir(parents=True, exist_ok=True)
    for legacy_backup, backup in zip(legacy_backups, legacy_destinations, strict=True):
        move(str(legacy_backup), str(backup))
    for destination, backup in zip(existing_destinations, backups, strict=True):
        move(str(destination), str(backup))
    for source, destination in selected:
        copytree(source, destination)

    kept = tuple(
        destination
        for source, destination in zip(plan.source_directories, destinations, strict=True)
        if (source, destination) not in selected and _skill_state(source, destination) != "current"
    )
    return CodexSkillsInstallResult(
        destination=plan.destination,
        installed=tuple(destination for _, destination in selected),
        backups=backups,
        kept=kept,
    )


def install_codex_skills(
    destination: Path, now: datetime, *, force: bool
) -> CodexSkillsInstallResult:
    """Install the complete Codex skill bundle for direct callers and tests."""
    return apply_codex_skills_install(plan_codex_skills_install(destination, now), force=force)


def run_install(
    mods_dir: Path,
    *,
    now: datetime,
    state_dir: Path,
    dry_run: bool,
    force: bool,
) -> InstallResult:
    """Plan an installation and apply it only when not running dry."""
    plan = plan_install(mods_dir, now, state_dir=state_dir)
    if dry_run:
        return InstallResult(
            changed=False,
            destination=plan.destination,
            backup_destination=None,
        )
    return apply_install(plan, force=force)


def doctor(mods_dir: Path, *, state_dir: Path, _payload: Path | None = None) -> DoctorReport:
    """Report whether a bridge is present, current, and untouched."""
    destination = mods_dir / "battlemap-mcp-bridge"
    if not destination.is_dir():
        return DoctorReport(
            destination=destination,
            status="missing",
            recommended_action="Run battlemap-mcp install to install the bridge.",
        )

    installed = _file_hashes(destination)
    # Line endings are ignored, as the live identity check does: v1.0.0's
    # Windows companion bundled a CRLF payload while the mod ZIP was LF.
    installed_content = _content_hashes(destination)
    payload = _content_hashes(Path(str(_payload if _payload is not None else payload_root())))
    current = bool(payload) and all(
        installed_content.get(name) == digest for name, digest in payload.items()
    )

    records_path = state_dir / "battlemap-mcp" / "installs.json"
    records = _load_records(records_path)
    expected = next(
        (
            entry
            for entry in records["installs"]
            if entry.get("destination") == str(destination.resolve())
        ),
        None,
    )
    if expected is None:
        if current:
            # A copy this installer did not make but that IS this package's
            # bridge â€” a development checkout linked into the mods folder.
            return DoctorReport(
                destination=destination,
                status="healthy",
                recommended_action=(
                    "Matches this package (not installed by this tool). Restart "
                    "Dungeondraft to load any change."
                ),
            )
        return DoctorReport(
            destination=destination,
            status="unknown",
            recommended_action="Review the bridge, then rerun install with --force to replace it.",
        )

    if expected.get("files") == installed:
        if current:
            return DoctorReport(
                destination=destination,
                status="healthy",
                recommended_action="Start Dungeondraft, open a map, and enable the bridge mod.",
            )
        return DoctorReport(
            destination=destination,
            status="outdated",
            recommended_action=(
                "An unmodified install of an older bridge. Rerun battlemap-mcp "
                "install --force to update it, then restart Dungeondraft."
            ),
        )

    return DoctorReport(
        destination=destination,
        status="modified",
        recommended_action="Review local changes, then rerun install with --force to replace it.",
    )


def uninstall(mods_dir: Path, *, state_dir: Path) -> InstallResult:
    """Remove only an unchanged bridge directory recorded by this installer."""
    destination = mods_dir / "battlemap-mcp-bridge"
    records_path = state_dir / "battlemap-mcp" / "installs.json"
    records = _load_records(records_path)
    destination_text = str(destination.resolve())
    expected = next(
        (entry for entry in records["installs"] if entry.get("destination") == destination_text),
        None,
    )
    if (
        not destination.is_dir()
        or expected is None
        or expected.get("files") != _file_hashes(destination)
    ):
        return InstallResult(False, destination, None)

    rmtree(destination)
    records["installs"] = [
        entry for entry in records["installs"] if entry.get("destination") != destination_text
    ]
    _write_records(records_path, records)
    return InstallResult(True, destination, None)


def _record_install(plan: InstallPlan) -> None:
    """Persist the payload identity outside Dungeondraft's mod directory."""
    records = _load_records(plan.records_path)
    entry = {
        "destination": str(plan.destination.resolve()),
        "bridge_version": _bridge_version(plan.destination),
        "protocol": PROTOCOL_VERSION,
        "files": _file_hashes(plan.destination),
    }
    installs = [
        saved for saved in records["installs"] if saved.get("destination") != entry["destination"]
    ]
    installs.append(entry)
    records["installs"] = installs

    _write_records(plan.records_path, records)


def _load_records(records_path: Path) -> dict[str, Any]:
    """Load saved installation ownership records, or initialise their shape."""
    if not records_path.is_file():
        return {"schema": 1, "installs": []}
    return json.loads(records_path.read_text(encoding="utf-8"))


def _write_records(records_path: Path, records: dict[str, Any]) -> None:
    """Write installer state after its target directory is known to be safe."""
    records_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=records_path.parent, prefix=".installs-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(records, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, records_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _bridge_version(destination: Path) -> str:
    """Read the bridge version from its Dungeondraft manifest."""
    manifest = json.loads(destination.joinpath("mcp_bridge.ddmod").read_text(encoding="utf-8"))
    return str(manifest["version"])


def _file_hashes(directory: Path) -> dict[str, str]:
    """Return SHA-256 checksums keyed by safe, relative payload paths."""
    hashes: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes[str(path.relative_to(directory))] = digest
    return hashes


def _content_digest(path: Path) -> str:
    """Hash a payload file without its CRs, so a CRLF copy matches its LF source."""
    return hashlib.sha256(path.read_bytes().replace(b"\r", b"")).hexdigest()


def _content_hashes(directory: Path) -> dict[str, str]:
    """Like _file_hashes, but line-ending-insensitive; for "same version?" only.

    Install records keep exact bytes, so an edit is still an edit.
    """
    return {
        str(path.relative_to(directory)): _content_digest(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _destination_token(destination: Path) -> str:
    """Return a stable identifier so different mod directories cannot collide in state."""
    return hashlib.sha256(str(destination.resolve()).encode("utf-8")).hexdigest()[:12]
