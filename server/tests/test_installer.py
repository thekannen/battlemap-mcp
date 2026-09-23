"""Offline tests for safe Dungeondraft bridge installation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXED_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _destination_token(destination):
    """Match the stable state-backup namespace derived from a mod destination."""
    return hashlib.sha256(str(destination.resolve()).encode("utf-8")).hexdigest()[:12]


def test_plan_is_write_free(tmp_path):
    """Previewing an installation must not create a mods or state directory."""
    from battlemap_mcp.installer import plan_install

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"

    plan = plan_install(mods_dir, FIXED_NOW, state_dir=state_dir)

    assert plan.destination == mods_dir / "battlemap-mcp-bridge"
    assert "install bridge" in plan.actions
    assert plan.requires_force is False
    assert not mods_dir.exists()
    assert not state_dir.exists()


def test_apply_install_copies_the_bridge_payload(tmp_path):
    """Applying a fresh plan creates an installable bridge directory."""
    from battlemap_mcp.installer import apply_install, plan_install

    plan = plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")

    result = apply_install(plan, force=False)

    assert result.changed is True
    assert result.backup_destination is None
    assert result.destination.joinpath("mcp_bridge.ddmod").is_file()


def test_modified_bridge_needs_force_and_moves_to_a_state_backup(tmp_path):
    """A forced bridge replacement must not leave another discoverable DD mod."""
    from battlemap_mcp.installer import (
        InstallConflictError,
        apply_install,
        plan_install,
    )

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"
    apply_install(plan_install(mods_dir, FIXED_NOW, state_dir=state_dir), force=False)
    destination = mods_dir / "battlemap-mcp-bridge"
    destination.joinpath("local-note.txt").write_text("preserve me")

    replacement = plan_install(mods_dir, FIXED_NOW, state_dir=state_dir)

    assert replacement.requires_force is True
    with pytest.raises(InstallConflictError):
        apply_install(replacement, force=False)
    result = apply_install(replacement, force=True)

    assert result.backup_destination is not None
    assert result.backup_destination.parent == (
        state_dir / "battlemap-mcp" / "backups" / _destination_token(destination)
    )
    assert not result.backup_destination.is_relative_to(mods_dir)
    assert result.backup_destination.joinpath("local-note.txt").read_text() == "preserve me"


def test_forced_install_migrates_legacy_bridge_backups_out_of_mods(tmp_path):
    """Old installer backups must stop being visible as duplicate Dungeondraft mods."""
    from shutil import copytree

    from battlemap_mcp.installer import apply_install, plan_install

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"
    plan = plan_install(mods_dir, FIXED_NOW, state_dir=state_dir)
    apply_install(plan, force=False)
    legacy_backup = mods_dir / "battlemap-mcp-bridge.backup-20260909T140544Z"
    copytree(plan.destination, legacy_backup)

    result = apply_install(plan_install(mods_dir, FIXED_NOW, state_dir=state_dir), force=True)

    assert not legacy_backup.exists()
    assert (
        state_dir
        / "battlemap-mcp"
        / "backups"
        / _destination_token(plan.destination)
        / legacy_backup.name
    ).is_dir()
    assert result.destination.joinpath("mcp_bridge.ddmod").is_file()


def test_legacy_bridge_backups_from_multiple_mods_directories_do_not_collide(tmp_path):
    """Legacy names shared by different mod roots must remain recoverable."""
    from shutil import copytree

    from battlemap_mcp.installer import apply_install, plan_install

    state_dir = tmp_path / "state"
    mods_dirs = (tmp_path / "mods-a", tmp_path / "mods-b")
    legacy_backups = []
    for mods_dir in mods_dirs:
        plan = plan_install(mods_dir, FIXED_NOW, state_dir=state_dir)
        apply_install(plan, force=False)
        legacy_backup = mods_dir / "battlemap-mcp-bridge.backup-20260909T140544Z"
        copytree(plan.destination, legacy_backup)
        legacy_backups.append((plan.destination, legacy_backup))

    for mods_dir in mods_dirs:
        apply_install(plan_install(mods_dir, FIXED_NOW, state_dir=state_dir), force=True)

    for destination, legacy_backup in legacy_backups:
        assert (
            state_dir
            / "battlemap-mcp"
            / "backups"
            / _destination_token(destination)
            / legacy_backup.name
        ).is_dir()


def test_dry_run_creates_no_directory(tmp_path):
    """A dry run reports a plan but cannot create its missing destination."""
    from battlemap_mcp.installer import run_install

    mods_dir = tmp_path / "missing"

    result = run_install(
        mods_dir,
        now=FIXED_NOW,
        state_dir=tmp_path / "state",
        dry_run=True,
        force=False,
    )

    assert result.changed is False
    assert not mods_dir.exists()


def test_applied_install_records_payload_hashes_outside_the_mod_directory(tmp_path):
    """Ownership records identify the installed payload without altering DD data."""
    from battlemap_mcp.bridge_client import PROTOCOL_VERSION
    from battlemap_mcp.installer import apply_install, plan_install

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"
    plan = plan_install(mods_dir, FIXED_NOW, state_dir=state_dir)

    apply_install(plan, force=False)

    record_path = state_dir / "battlemap-mcp" / "installs.json"
    record = json.loads(record_path.read_text())
    entry = record["installs"][0]
    assert entry["destination"] == str((mods_dir / "battlemap-mcp-bridge").resolve())
    from battlemap_mcp import __version__

    assert entry["bridge_version"] == __version__
    assert entry["protocol"] == PROTOCOL_VERSION
    assert len(entry["files"]["mcp_bridge.ddmod"]) == 64


def test_an_explicit_missing_mods_directory_remains_authoritative(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    configured = tmp_path / "configured"
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    (tmp_path / "config.ini").write_text(
        f'[Mods]\nmods_directory="{configured.as_posix()}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(installer, "dungeondraft_data_dir", lambda: tmp_path)
    monkeypatch.setattr(installer, "candidate_mods_dirs", lambda: [configured, fallback])

    assert installer.default_mods_dir() == configured


def test_doctor_identifies_a_modified_managed_bridge(tmp_path):
    """Doctor reports the bridge state without starting Dungeondraft."""
    from battlemap_mcp.installer import apply_install, doctor, plan_install

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"
    apply_install(plan_install(mods_dir, FIXED_NOW, state_dir=state_dir), force=False)

    healthy = doctor(mods_dir, state_dir=state_dir)
    (mods_dir / "battlemap-mcp-bridge" / "local-note.txt").write_text("changed")
    modified = doctor(mods_dir, state_dir=state_dir)

    assert healthy.status == "healthy"
    assert modified.status == "modified"
    assert "--force" in modified.recommended_action


def test_uninstall_removes_only_a_healthy_recorded_bridge(tmp_path):
    """Uninstall removes an owned payload but leaves a changed one intact."""
    from battlemap_mcp.installer import apply_install, plan_install, uninstall

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"
    apply_install(plan_install(mods_dir, FIXED_NOW, state_dir=state_dir), force=False)
    destination = mods_dir / "battlemap-mcp-bridge"

    removed = uninstall(mods_dir, state_dir=state_dir)

    assert removed.changed is True
    assert not destination.exists()

    destination.mkdir(parents=True)
    destination.joinpath("local-note.txt").write_text("not ours")
    preserved = uninstall(mods_dir, state_dir=state_dir)

    assert preserved.changed is False
    assert destination.joinpath("local-note.txt").is_file()


def test_candidate_mod_directories_follow_supported_platform_conventions(tmp_path):
    """Suggested mods paths are platform-specific hints, never created by lookup."""
    from battlemap_mcp.installer import candidate_mods_dirs

    home = tmp_path / "home"

    assert candidate_mods_dirs(_platform="darwin", _home=home) == [
        home / "Library" / "Application Support" / "Dungeondraft" / "mods"
    ]
    assert candidate_mods_dirs(
        _platform="win32",
        _home=home,
        _appdata=tmp_path / "roaming",
        _program_files=tmp_path / "no-program-files",
    ) == [tmp_path / "roaming" / "Dungeondraft" / "mods"]
    assert candidate_mods_dirs(_platform="linux", _home=home) == [
        home / ".local" / "share" / "Dungeondraft" / "mods"
    ]


def test_windows_candidates_prefer_an_installed_dungeondraft_mods_directory(tmp_path):
    """Windows discovery must find the live app's mods folder before AppData."""
    from battlemap_mcp.installer import candidate_mods_dirs

    program_files = tmp_path / "Program Files"
    installed_mods = program_files / "Dungeondraft" / "mods"
    installed_mods.mkdir(parents=True)
    appdata = tmp_path / "AppData" / "Roaming"

    assert candidate_mods_dirs(
        _platform="win32",
        _home=tmp_path / "home",
        _appdata=appdata,
        _program_files=program_files,
    ) == [installed_mods, appdata / "Dungeondraft" / "mods"]


def test_install_codex_skills_copies_the_full_skill_bundle(tmp_path):
    """Codex setup needs both discoverable skills and their shared references."""
    from battlemap_mcp.installer import install_codex_skills

    result = install_codex_skills(tmp_path / "codex" / "skills", FIXED_NOW, force=False)

    assert result.destination.joinpath("battlemap-art-direction", "SKILL.md").is_file()
    assert result.destination.joinpath("battlemap-visual-review", "SKILL.md").is_file()
    assert result.destination.joinpath("_shared", "build-loop.md").is_file()


def test_codex_skill_install_preserves_existing_skills_and_adds_missing_ones(tmp_path):
    """A local customization cannot prevent installation of the rest of the bundle."""
    from battlemap_mcp.installer import install_codex_skills

    skills_dir = tmp_path / "codex" / "skills"
    install_codex_skills(skills_dir, FIXED_NOW, force=False)
    skills_dir.joinpath("battlemap-art-direction", "local-note.txt").write_text("preserve me")
    missing_skill = skills_dir / "battlemap-visual-review"
    from shutil import rmtree

    rmtree(missing_skill)
    replacement = install_codex_skills(skills_dir, FIXED_NOW, force=False)

    assert (
        skills_dir.joinpath("battlemap-art-direction", "local-note.txt").read_text()
        == "preserve me"
    )
    assert missing_skill.joinpath("SKILL.md").is_file()
    assert replacement.backups == ()


def test_codex_skill_install_force_backs_up_existing_skills(tmp_path):
    """Force is still required to replace a local skill customization."""
    from battlemap_mcp.installer import install_codex_skills

    skills_dir = tmp_path / "codex" / "skills"
    install_codex_skills(skills_dir, FIXED_NOW, force=False)
    skills_dir.joinpath("battlemap-art-direction", "local-note.txt").write_text("preserve me")

    replacement = install_codex_skills(skills_dir, FIXED_NOW, force=True)

    art_direction_backup = next(
        backup
        for backup in replacement.backups
        if backup.name.startswith("battlemap-art-direction")
    )
    assert art_direction_backup.parent == skills_dir.parent / "backups" / "battlemap-mcp"
    assert not art_direction_backup.is_relative_to(skills_dir)
    assert art_direction_backup.joinpath("local-note.txt").read_text() == "preserve me"


def test_codex_skill_force_install_migrates_legacy_backups_out_of_skills(tmp_path):
    """Old skill backups must not remain discoverable as duplicate Codex skills."""
    from shutil import copytree

    from battlemap_mcp.installer import install_codex_skills

    skills_dir = tmp_path / "codex" / "skills"
    install_codex_skills(skills_dir, FIXED_NOW, force=False)
    legacy_backup = skills_dir / "battlemap-art-direction.backup-20260909T140544Z"
    copytree(skills_dir / "battlemap-art-direction", legacy_backup)

    install_codex_skills(skills_dir, FIXED_NOW, force=True)

    assert not legacy_backup.exists()
    assert (skills_dir.parent / "backups" / "battlemap-mcp" / legacy_backup.name).is_dir()


# Shaped like a real Dungeondraft config.ini: Godot ConfigFile literals, and a
# multi-line dictionary in a later section that configparser refuses to read.
CONFIG_INI = """[Display]

current_screen=0

[Files]

recently_opened_maps=[ "/maps/a.dungeondraft_map", "/maps/b.dungeondraft_map" ]

[Mods]

active_mods=[ "thekannen.MCPBridge" ]
mods_directory="{mods}"

[New]

width=35
size_presets={{
}}
"""


def _write_config(data_dir, mods):
    data_dir.mkdir(parents=True, exist_ok=True)
    escaped_mods = str(mods).replace("\\", "\\\\").replace('"', '\\"')
    (data_dir / "config.ini").write_text(CONFIG_INI.format(mods=escaped_mods), encoding="utf-8")


def test_the_mods_folder_dungeondraft_is_configured_to_load_comes_first(tmp_path):
    """Runtime behavior and validation."""
    from battlemap_mcp.installer import candidate_mods_dirs

    home = tmp_path / "home"
    custom = tmp_path / "Dungeondraft Mods"
    _write_config(home / "Library" / "Application Support" / "Dungeondraft", custom)

    candidates = candidate_mods_dirs(_platform="darwin", _home=home)
    assert candidates[0] == custom
    assert home / "Library" / "Application Support" / "Dungeondraft" / "mods" in candidates


def test_configured_mods_dir_reads_godot_configfile_syntax(tmp_path):
    from battlemap_mcp.installer import configured_mods_dir

    data = tmp_path / "dd"
    # The helper escapes the literal path; pre-escaping it here hides a
    # doubled-separator fixture error on Windows but fails on POSIX.
    _write_config(data, r"C:\Games\DD Mods")
    assert configured_mods_dir(data / "config.ini") == Path(r"C:\Games\DD Mods")


def test_a_mods_directory_key_outside_the_mods_section_is_ignored(tmp_path):
    from battlemap_mcp.installer import configured_mods_dir

    config = tmp_path / "config.ini"
    config.write_text('[Files]\nmods_directory="/not/this"\n\n[Mods]\n', encoding="utf-8")
    assert configured_mods_dir(config) is None


def test_no_config_means_the_platform_default(tmp_path):
    from battlemap_mcp.installer import candidate_mods_dirs, configured_mods_dir

    assert configured_mods_dir(tmp_path / "missing.ini") is None
    home = tmp_path / "home"
    assert candidate_mods_dirs(_platform="linux", _home=home) == [
        home / ".local" / "share" / "Dungeondraft" / "mods"
    ]


def test_doctor_calls_an_untouched_older_install_outdated_not_healthy(tmp_path):
    """Runtime behavior and validation."""
    from datetime import UTC, datetime
    from shutil import copytree

    from battlemap_mcp.installer import apply_install, doctor, payload_root, plan_install

    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    state_dir = tmp_path / "state"
    apply_install(plan_install(mods_dir, datetime.now(UTC), state_dir=state_dir), force=False)
    assert doctor(mods_dir, state_dir=state_dir).status == "healthy"

    newer = tmp_path / "newer-package"
    copytree(Path(str(payload_root())), newer)
    script = newer / "scripts" / "tools" / "mcp_bridge.gd"
    script.write_text(script.read_text(encoding="utf-8") + "\n# newer\n", encoding="utf-8")

    report = doctor(mods_dir, state_dir=state_dir, _payload=newer)
    assert report.status == "outdated"
    assert "--force" in report.recommended_action


def test_an_unrecorded_copy_of_this_package_is_healthy(tmp_path):
    """A development checkout linked into the mods folder is current, not "unknown"."""
    from shutil import copytree

    from battlemap_mcp.installer import doctor, payload_root

    mods_dir = tmp_path / "mods"
    copytree(Path(str(payload_root())), mods_dir / "battlemap-mcp-bridge")
    assert doctor(mods_dir, state_dir=tmp_path / "state").status == "healthy"


def test_skill_inspection_detects_missing_shared_files_and_changed_skills(tmp_path):
    from battlemap_mcp.installer import inspect_skills, install_codex_skills

    target = tmp_path / "claude" / "skills"
    assert set(inspect_skills(target).values()) == {"missing or incomplete"}
    install_codex_skills(target, FIXED_NOW, force=False)
    assert set(inspect_skills(target).values()) == {"current"}
    (target / "_shared" / "build-loop.md").unlink()
    (target / "battlemap-interiors" / "SKILL.md").write_text("local edits")
    report = inspect_skills(target)
    assert report["_shared"] == "missing or incomplete"
    assert report["battlemap-interiors"] == "differs from bundled version"
    assert report["battlemap-art-direction"] == "current"


def test_claude_skills_respect_config_directory(monkeypatch, tmp_path):
    from battlemap_mcp.installer import claude_code_skills_dir

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert claude_code_skills_dir() == tmp_path / ".claude" / "skills"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "alternate"))
    assert claude_code_skills_dir() == tmp_path / "alternate" / "skills"


@pytest.mark.parametrize("failure", ["copy", "record"])
def test_failed_replacement_restores_original_and_records(monkeypatch, tmp_path, failure):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    installer.apply_install(plan, force=False)
    (plan.destination / "local.txt").write_text("old install")
    original = installer._file_hashes(plan.destination)
    records = plan.records_path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("injected failure")

    monkeypatch.setattr(installer, "copytree" if failure == "copy" else "_record_install", fail)
    with pytest.raises(OSError, match="injected"):
        installer.apply_install(plan, force=True)
    assert installer._file_hashes(plan.destination) == original
    assert plan.records_path.read_bytes() == records
    assert list(plan.destination.parent.iterdir()) == [plan.destination]


def test_record_replace_failure_keeps_previous_json(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    target = tmp_path / "installs.json"
    target.write_text('{"old": true}')

    def fail(*args, **kwargs):
        raise OSError("record replace failed")

    monkeypatch.setattr(installer.os, "replace", fail)
    with pytest.raises(OSError):
        installer._write_records(target, {"new": True})
    assert target.read_text() == '{"old": true}'


def test_partial_destination_copy_failure_restores_install_and_legacy_backup(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    installer.apply_install(plan, force=False)
    (plan.destination / "local.txt").write_text("original")
    legacy = plan.destination.with_name(plan.destination.name + ".backup-old")
    legacy.mkdir()
    (legacy / "keep.txt").write_text("legacy")
    copy = installer.copytree

    def partial_copy(source, target, *args, **kwargs):
        if target == plan.destination and source.name == "payload":
            target.mkdir(exist_ok=True)
            (target / "partial.txt").write_text("incomplete")
            raise OSError("partial copy")
        return copy(source, target, *args, **kwargs)

    monkeypatch.setattr(installer, "copytree", partial_copy)
    with pytest.raises(OSError, match="partial copy"):
        installer.apply_install(plan, force=True)
    assert (plan.destination / "local.txt").read_text() == "original"
    assert not (plan.destination / "partial.txt").exists()
    assert (legacy / "keep.txt").read_text() == "legacy"


def test_fresh_record_failure_removes_unrecorded_install(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")

    def fail(*args):
        raise OSError("record failure")

    monkeypatch.setattr(installer, "_record_install", fail)
    with pytest.raises(OSError):
        installer.apply_install(plan, force=False)
    assert not plan.destination.exists()
    assert not plan.records_path.exists()


def test_latest_log_evidence_uses_newest_log_and_is_historical(tmp_path):
    import os

    from battlemap_mcp import installer

    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "old.log"
    old.write_text(
        "Battlemap MCP Bridge mod found in /old\n"
        + "[mcp-bridge] listening on 127.0.0.1:8787 (protocol v24)\n"
    )
    recent = logs / "godot.log"
    recent.write_text(
        "Battlemap MCP Bridge mod found in /new\n"
        + "[mcp-bridge] listening on 127.0.0.1:8788 (protocol v25)\n"
    )
    os.utime(old, (10, 10))
    os.utime(recent, (20, 20))
    report = installer.latest_log_evidence(tmp_path)
    assert report.path == recent
    assert report.mod_path == "/new"
    assert report.protocol == 25
    assert report.status == "historical"


def test_duplicate_mod_discovery_does_not_identify_last_copy_as_loaded(tmp_path):
    from battlemap_mcp import installer

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "godot.log").write_text(
        "Mods refreshed.\nBattlemap MCP Bridge mod found in /builtin/bridge.ddmod\n"
        "Battlemap MCP Bridge mod found in /configured/bridge.ddmod\n"
        "[mcp-bridge] listening on 127.0.0.1:8787 (protocol v25)\n"
    )
    report = installer.latest_log_evidence(tmp_path)
    assert report.status == "ambiguous discovery"
    assert report.mod_path is None
    assert report.mod_paths == ("/builtin/bridge.ddmod", "/configured/bridge.ddmod")


def test_latest_log_does_not_reuse_older_success(tmp_path):
    import os

    from battlemap_mcp import installer

    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "old.log"
    old.write_text(
        "Battlemap MCP Bridge mod found in /old\n"
        + "[mcp-bridge] listening on 127.0.0.1:8787 (protocol v25)\n"
    )
    new = logs / "new.log"
    new.write_bytes(b"startup failed\xff\n")
    os.utime(old, (10, 10))
    os.utime(new, (20, 20))
    report = installer.latest_log_evidence(tmp_path)
    assert report.status == "missing evidence"
    assert report.mod_path is None
    assert report.protocol is None


def test_refresh_discards_old_duplicate_discovery_and_deduplicates_paths(tmp_path):
    from battlemap_mcp import installer

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "godot.log").write_text(
        "Mods refreshed.\nBattlemap MCP Bridge mod found in /old\n"
        "Battlemap MCP Bridge mod found in /other\n"
        "[mcp-bridge] listening on 127.0.0.1:8787 (protocol v24)\n"
        "Mods refreshed.\nBattlemap MCP Bridge mod found in /new\n"
        "Battlemap MCP Bridge mod found in /new\n"
    )
    report = installer.latest_log_evidence(tmp_path)
    assert report.status == "missing evidence"
    assert report.mod_path == "/new"
    assert report.mod_paths == ("/new",)
    assert report.protocol is None


def test_log_tail_read_is_bounded(tmp_path):
    from battlemap_mcp import installer

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "godot.log").write_text("Battlemap MCP Bridge mod found in /old\n" + "x" * 300000)
    assert installer.latest_log_evidence(tmp_path).mod_path is None


@pytest.mark.parametrize(
    "reply,status",
    [
        ({}, "unverified"),
        ({"pong": True, "protocol": 24, "bridge_sha256": "a" * 64}, "mismatch"),
        ({"pong": True, "protocol": 25, "bridge_sha256": "a" * 64}, "mismatch"),
    ],
)
def test_live_doctor_does_not_accept_missing_or_wrong_identity(monkeypatch, reply, status):
    from battlemap_mcp import installer

    monkeypatch.setattr(installer.BridgeClient, "request", lambda self, command: reply)
    assert installer.live_bridge_identity().status == status


def test_live_doctor_compares_authenticated_running_source(monkeypatch):
    from battlemap_mcp import installer

    script = Path(installer.payload_root()) / "scripts/tools/mcp_bridge.gd"
    digest = hashlib.sha256(script.read_bytes().replace(b"\r", b"")).hexdigest()
    commands = []

    def request(self, command):
        commands.append(command)
        return {"pong": True, "protocol": 25, "bridge_sha256": digest}

    monkeypatch.setattr(installer.BridgeClient, "request", request)
    identity = installer.live_bridge_identity()
    assert identity.status == "current"
    assert identity.bridge_root is None
    assert identity.process_id is None
    assert commands == ["ping"]


def test_live_doctor_reports_connection_failure(monkeypatch):
    from battlemap_mcp import installer
    from battlemap_mcp.errors import BridgeUnavailableError

    def request(self, command):
        raise BridgeUnavailableError("offline")

    monkeypatch.setattr(installer.BridgeClient, "request", request)
    assert installer.live_bridge_identity().status == "unavailable"


@pytest.mark.parametrize(
    "protocol,digest,status",
    [
        (25, "a" * 64, "mismatch"),
        (24, "a" * 64, "mismatch"),
        (25, None, "unverified"),
    ],
)
def test_live_identity_preserves_reported_location_even_for_old_source(
    monkeypatch,
    tmp_path,
    protocol,
    digest,
    status,
):
    from battlemap_mcp import installer

    root = str(tmp_path / "actually-loaded")
    monkeypatch.setattr(
        installer.BridgeClient,
        "request",
        lambda self, command: {
            "pong": True,
            "protocol": protocol,
            "bridge_sha256": digest,
            "bridge_root": root,
            "process_id": 12345,
        },
    )
    identity = installer.live_bridge_identity()
    assert identity.status == status
    assert identity.bridge_root == root
    assert identity.process_id == 12345
    assert identity.bridge_sha256 == digest


@pytest.mark.parametrize("root,pid", [(None, None), ("relative/mod", True), (12, -1)])
def test_live_identity_does_not_invent_missing_or_invalid_location(monkeypatch, root, pid):
    from battlemap_mcp import installer

    monkeypatch.setattr(
        installer.BridgeClient,
        "request",
        lambda self, command: {
            "pong": True,
            "protocol": 25,
            "bridge_sha256": "a" * 64,
            "bridge_root": root,
            "process_id": pid,
        },
    )
    identity = installer.live_bridge_identity()
    assert identity.bridge_root is None
    assert identity.process_id is None


def test_unreadable_latest_log_does_not_fall_back(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    logs = tmp_path / "logs"
    logs.mkdir()
    newest = logs / "godot.log"
    newest.write_text("private")
    original_open = Path.open

    def refuse(path, *args, **kwargs):
        if path == newest:
            raise PermissionError("unreadable")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    report = installer.latest_log_evidence(tmp_path)
    assert report.status == "unreadable"
    assert report.path == newest
    assert report.mod_path is None


def test_new_mod_load_clears_prior_listening_evidence(tmp_path):
    from battlemap_mcp import installer

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "godot.log").write_text(
        "Battlemap MCP Bridge mod found in /old\n"
        "[mcp-bridge] listening on 127.0.0.1:8787 (protocol v25)\n"
        "Battlemap MCP Bridge mod found in /new\nparse error\n"
    )
    report = installer.latest_log_evidence(tmp_path)
    assert report.mod_path == "/new"
    assert report.protocol is None
    assert report.status == "missing evidence"


@pytest.mark.parametrize("digest", [None, "", 123, "malformed"])
def test_live_doctor_rejects_missing_or_malformed_digest(monkeypatch, digest):
    from battlemap_mcp import installer

    monkeypatch.setattr(
        installer.BridgeClient,
        "request",
        lambda self, _: {"pong": True, "protocol": 25, "bridge_sha256": digest},
    )
    assert installer.live_bridge_identity().status == "unverified"


@pytest.mark.parametrize("legacy_failure", [False, True])
def test_partial_source_removal_keeps_recoverable_original(monkeypatch, tmp_path, legacy_failure):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    installer.apply_install(plan, force=False)
    (plan.destination / "local.txt").write_text("original")
    legacy = plan.destination.with_name(plan.destination.name + ".backup-old")
    legacy.mkdir()
    (legacy / "local.txt").write_text("legacy")
    target = legacy if legacy_failure else plan.destination
    original_hashes = installer._file_hashes(target)
    real_rmtree = installer.rmtree
    real_move = installer.move
    failed = False

    def partial_remove(path, *args, **kwargs):
        nonlocal failed
        if Path(path) == target and not failed:
            failed = True
            (target / "local.txt").unlink()
            raise OSError("partial source removal")
        return real_rmtree(path, *args, **kwargs)

    def cross_volume_move(source, destination):
        if Path(source) == target:
            installer.copytree(source, destination)
            partial_remove(source)
        return real_move(source, destination)

    monkeypatch.setattr(installer, "rmtree", partial_remove)
    monkeypatch.setattr(installer, "move", cross_volume_move)
    with pytest.raises(OSError, match="partial source removal"):
        installer.apply_install(plan, force=True)
    assert installer._file_hashes(target) == original_hashes
    retry = installer.plan_install(
        tmp_path / "mods", FIXED_NOW.replace(day=8), state_dir=tmp_path / "state"
    )
    assert installer.apply_install(retry, force=True).changed


def test_destination_created_by_other_writer_is_not_deleted(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    real_mkdir = Path.mkdir

    def competing_mkdir(path, *args, **kwargs):
        if path == plan.destination and not path.exists():
            real_mkdir(path)
            (path / "other.txt").write_text("other writer")
        return real_mkdir(path, *args, **kwargs)

    real_copytree = installer.copytree

    def competing_copy(source, destination, *args, **kwargs):
        if destination == plan.destination and not destination.exists():
            destination.mkdir(parents=True, exist_ok=True)
        return real_copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(installer, "copytree", competing_copy)
    monkeypatch.setattr(Path, "mkdir", competing_mkdir)
    with pytest.raises(FileExistsError):
        installer.apply_install(plan, force=False)
    assert (plan.destination / "other.txt").read_text() == "other writer"


def test_retry_after_failed_install_reuses_verified_legacy_backup(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    installer.apply_install(plan, force=False)
    legacy = plan.destination.with_name(plan.destination.name + ".backup-old")
    legacy.mkdir()
    (legacy / "local.txt").write_text("legacy")
    record = installer._record_install

    def fail(*args):
        raise OSError("record failure")

    monkeypatch.setattr(installer, "_record_install", fail)
    with pytest.raises(OSError, match="record failure"):
        installer.apply_install(plan, force=True)
    assert (legacy / "local.txt").read_text() == "legacy"
    monkeypatch.setattr(installer, "_record_install", record)
    retry = installer.plan_install(
        tmp_path / "mods", FIXED_NOW.replace(day=8), state_dir=tmp_path / "state"
    )
    result = installer.apply_install(retry, force=True)
    assert result.changed
    assert not legacy.exists()
    backups = list((plan.records_path.parent / "backups").rglob("local.txt"))
    assert any(path.read_text() == "legacy" for path in backups)


def test_failed_legacy_restoration_retains_state_backup(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    installer.apply_install(plan, force=False)
    legacy = plan.destination.with_name(plan.destination.name + ".backup-old")
    legacy.mkdir()
    (legacy / "local.txt").write_text("legacy")
    copytree = installer.copytree

    def fail_record(*args):
        raise OSError("record failure")

    def fail_restore(source, destination, *args, **kwargs):
        if destination == legacy:
            raise OSError("restore failure")
        return copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(installer, "_record_install", fail_record)
    monkeypatch.setattr(installer, "copytree", fail_restore)
    with pytest.raises(OSError, match="restore failure"):
        installer.apply_install(plan, force=True)
    copies = list((plan.records_path.parent / "backups").rglob("local.txt"))
    assert any(path.read_text() == "legacy" for path in copies)


@pytest.mark.parametrize("failure", ["second_copy", "checksum"])
def test_preparation_failure_cleans_only_owned_backups_and_allows_retry(
    monkeypatch, tmp_path, failure
):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    installer.apply_install(plan, force=False)
    for name in ("a", "b"):
        legacy = plan.destination.with_name(plan.destination.name + ".backup-" + name)
        legacy.mkdir()
        (legacy / "keep.txt").write_text(name)
    original = installer._file_hashes(plan.destination)
    copytree = installer.copytree

    def fail_copy(source, destination, *args, **kwargs):
        if destination.name.endswith(".backup-b"):
            destination.mkdir(exist_ok=True)
            (destination / "partial.txt").write_text("partial")
            if failure == "second_copy":
                raise OSError("partial backup copy")
            return destination
        return copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(installer, "copytree", fail_copy)
    with pytest.raises(OSError):
        installer.apply_install(plan, force=True)
    assert installer._file_hashes(plan.destination) == original
    monkeypatch.setattr(installer, "copytree", copytree)
    assert installer.apply_install(plan, force=True).changed


def test_raced_backup_directory_is_never_removed(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    plan = installer.plan_install(tmp_path / "mods", FIXED_NOW, state_dir=tmp_path / "state")
    installer.apply_install(plan, force=False)
    real_mkdir = Path.mkdir
    raced = []

    def competing_mkdir(path, *args, **kwargs):
        if ".backup-" in path.name and not path.exists():
            real_mkdir(path)
            (path / "other.txt").write_text("other backup")
            raced.append(path)
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", competing_mkdir)
    with pytest.raises(FileExistsError):
        installer.apply_install(plan, force=True)
    assert len(raced) == 1
    assert (raced[0] / "other.txt").read_text() == "other backup"
