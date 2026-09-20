"""Entry-point compatibility tests."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_client_side_effects(monkeypatch, tmp_path):
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.state_paths, "state_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr(cli.installer, "codex_skills_dir", lambda: tmp_path / "codex" / "skills")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(cli.installer, "dungeondraft_data_dir", lambda: tmp_path / "dd-data")
    monkeypatch.setattr(cli.installer, "default_mods_dir", lambda: tmp_path / "default-mods")
    monkeypatch.setattr(
        cli.client_config,
        "claude_registry_paths",
        lambda: {"Claude Code (user scope)": tmp_path / "claude.json"},
    )
    monkeypatch.setattr(
        cli.client_config, "register_client", lambda *_: ClientRegistrationResult(False, None)
    )


def test_no_argument_dispatches_to_the_stdio_server(monkeypatch):
    """Changing the console entry point must not suppress the MCP server."""
    from battlemap_mcp import cli

    calls = 0

    def fake_server_main() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(cli.server, "main", fake_server_main)

    assert cli.main([]) == 0
    assert calls == 1


def test_help_exits_successfully():
    """The installer entry point must offer a standard help path."""
    from battlemap_mcp import cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0


def test_unknown_command_exits_with_argument_error():
    """An invalid command must not be interpreted as an MCP server launch."""
    from battlemap_mcp import cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["not-a-command"])

    assert exc_info.value.code == 2


def test_install_dry_run_prints_a_plan_without_creating_the_mods_directory(
    monkeypatch, tmp_path, capsys
):
    """The CLI preview must not apply a bridge installation."""
    from battlemap_mcp import cli

    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")

    assert cli.main(["install", "--mods-dir", str(mods_dir), "--dry-run"]) == 0

    assert "install bridge" in capsys.readouterr().out
    assert not mods_dir.exists()


def test_noninteractive_install_requires_yes(monkeypatch, tmp_path, capsys):
    """A piped install must require explicit confirmation before writing files."""
    from battlemap_mcp import cli

    class NonInteractiveInput:
        def isatty(self) -> bool:
            return False

    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(cli.sys, "stdin", NonInteractiveInput())
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")

    assert cli.main(["install", "--mods-dir", str(mods_dir)]) == 2

    assert "--yes" in capsys.readouterr().err
    assert not mods_dir.exists()


def test_interactive_install_uses_an_explicit_confirmation_prompt(monkeypatch, tmp_path):
    """An interactive install applies only after the documented prompt is accepted."""
    from battlemap_mcp import cli

    class InteractiveInput:
        def isatty(self) -> bool:
            return True

    prompts: list[str] = []
    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(cli.sys, "stdin", InteractiveInput())
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "y")

    assert cli.main(["install", "--mods-dir", str(mods_dir)]) == 0

    assert prompts == ["Apply these changes? [y/N] "]
    assert mods_dir.joinpath("battlemap-mcp-bridge", "mcp_bridge.ddmod").is_file()


def test_doctor_command_reports_the_recorded_bridge_state(monkeypatch, tmp_path, capsys):
    """The CLI doctor path uses saved hashes and does not require a live bridge."""
    from battlemap_mcp import cli
    from battlemap_mcp.installer import apply_install, plan_install

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"
    apply_install(plan_install(mods_dir, datetime(2026, 9, 7), state_dir=state_dir), force=False)
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: state_dir)

    assert cli.main(["doctor", "--mods-dir", str(mods_dir)]) == 0

    assert "healthy" in capsys.readouterr().out


def test_uninstall_command_requires_yes_and_removes_a_managed_bridge(monkeypatch, tmp_path):
    """The CLI makes the destructive uninstall intent explicit."""
    from battlemap_mcp import cli

    mods_dir = tmp_path / "mods"
    state_dir = tmp_path / "state"
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: state_dir)

    assert cli.main(["install", "--mods-dir", str(mods_dir), "--yes"]) == 0
    assert cli.main(["uninstall", "--mods-dir", str(mods_dir), "--yes"]) == 0

    assert not mods_dir.joinpath("battlemap-mcp-bridge").exists()


def test_install_registers_requested_client_after_copying_the_bridge(monkeypatch, tmp_path):
    """Guided setup invokes client registration only after bridge installation succeeds."""
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    calls: list[tuple[str, Path]] = []
    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.installer, "codex_skills_dir", lambda: tmp_path / "codex" / "skills")
    monkeypatch.setattr(cli.sys, "argv", ["/opt/bin/battlemap-mcp"])
    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda client, executable: (
            calls.append((client, executable))
            or ClientRegistrationResult(registered=True, manual_command=None)
        ),
    )

    assert cli.main(["install", "--mods-dir", str(mods_dir), "--yes", "--client", "codex"]) == 0

    assert calls == [("codex", Path("/opt/bin/battlemap-mcp").resolve())]


def test_codex_install_copies_skills_without_requiring_the_codex_cli(monkeypatch, tmp_path, capsys):
    """Skills are useful even when automatic MCP registration cannot run yet."""
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    mods_dir = tmp_path / "mods"
    codex_home = tmp_path / "codex-home"
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.installer, "codex_skills_dir", lambda: codex_home / "skills")
    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda *_: ClientRegistrationResult(
            registered=False,
            manual_command=["codex", "mcp", "add", "battlemap", "--", "server"],
        ),
    )

    assert cli.main(["install", "--mods-dir", str(mods_dir), "--yes", "--client", "codex"]) == 1

    assert codex_home.joinpath("skills", "battlemap-art-direction", "SKILL.md").is_file()
    output = capsys.readouterr().out
    assert "Codex CLI was not available" in output
    assert "skills installed" in output


def test_claude_install_copies_the_complete_bundle_without_the_cli(monkeypatch, tmp_path, capsys):
    """Claude Code receives all skills and shared references even without its CLI."""
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    mods_dir = tmp_path / "mods"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda *_: ClientRegistrationResult(
            registered=False,
            manual_command=["claude", "mcp", "add", "battlemap", "--", "server"],
        ),
    )

    assert (
        cli.main(["install", "--mods-dir", str(mods_dir), "--yes", "--client", "claude-code"]) == 1
    )

    output = capsys.readouterr().out
    assert "Claude Code CLI was not available; bridge and Claude Code skills installed" in output
    assert "Codex skills" not in output
    source = Path(cli.installer.skills_payload_root())
    for path in source.rglob("*"):
        if path.is_file() and len(path.relative_to(source).parts) > 1:
            assert (tmp_path / "claude" / "skills" / path.relative_to(source)).read_bytes() == (
                path.read_bytes()
            )


def test_manual_client_registration_command_quotes_windows_paths(monkeypatch, tmp_path, capsys):
    """A recovery command remains copyable when the server path contains spaces."""
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    monkeypatch.setattr(cli.sys, "platform", "win32")
    mods_dir = tmp_path / "mods"
    manual_command = [
        "codex",
        "mcp",
        "add",
        "battlemap",
        "--",
        r"C:\\Program Files\\Dungeondraft MCP\\battlemap-mcp.exe",
    ]
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.installer, "codex_skills_dir", lambda: tmp_path / "codex" / "skills")
    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda *_: ClientRegistrationResult(registered=False, manual_command=manual_command),
    )

    assert cli.main(["install", "--mods-dir", str(mods_dir), "--yes", "--client", "codex"]) == 1

    assert subprocess.list2cmdline(manual_command) in capsys.readouterr().out


def test_install_uses_the_discovered_mods_directory_when_none_is_supplied(monkeypatch, tmp_path):
    """Users should not need to locate a standard Dungeondraft installation by hand."""
    from battlemap_mcp import cli

    mods_dir = tmp_path / "Dungeondraft" / "mods"
    mods_dir.mkdir(parents=True)
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.installer, "default_mods_dir", lambda: mods_dir)

    assert cli.main(["install", "--yes"]) == 0

    assert mods_dir.joinpath("battlemap-mcp-bridge", "mcp_bridge.ddmod").is_file()


def test_install_explains_when_the_discovered_mods_directory_requires_elevation(
    monkeypatch, tmp_path, capsys
):
    """A protected Program Files installation must not expose a Python traceback."""
    from battlemap_mcp import cli

    mods_dir = tmp_path / "Program Files" / "Dungeondraft" / "mods"
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.installer, "default_mods_dir", lambda: mods_dir)
    monkeypatch.setattr(
        cli.installer,
        "apply_install",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError),
    )

    assert cli.main(["install", "--yes"]) == 1

    error = capsys.readouterr().err.lower()
    assert "administrator" not in error
    assert "battlemap" in error


def test_codex_skill_permission_error_explains_that_the_bridge_was_installed(
    monkeypatch, tmp_path, capsys
):
    """A protected Codex skill folder must not hide its failure behind a traceback."""
    from battlemap_mcp import cli

    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.installer, "codex_skills_dir", lambda: tmp_path / "codex" / "skills")
    monkeypatch.setattr(
        cli.installer,
        "apply_codex_skills_install",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError),
    )

    assert cli.main(["install", "--mods-dir", str(mods_dir), "--yes", "--client", "codex"]) == 1

    error = capsys.readouterr().err.lower()
    assert "bridge was installed" in error
    assert "codex skills" in error


def test_codex_skill_backup_conflict_does_not_leave_a_traceback(monkeypatch, tmp_path, capsys):
    """A recoverable skills conflict must be reported after the bridge copy succeeds."""
    from battlemap_mcp import cli
    from battlemap_mcp.installer import InstallConflictError

    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.installer, "codex_skills_dir", lambda: tmp_path / "codex" / "skills")
    monkeypatch.setattr(
        cli.installer,
        "apply_codex_skills_install",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(InstallConflictError("backup exists")),
    )

    assert cli.main(["install", "--mods-dir", str(mods_dir), "--yes", "--client", "codex"]) == 1

    error = capsys.readouterr().err.lower()
    assert "bridge was installed" in error
    assert "backup exists" in error


def test_claude_dry_run_does_not_write_skills(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    assert (
        cli.main(
            [
                "install",
                "--mods-dir",
                str(tmp_path / "mods"),
                "--client",
                "claude-code",
                "--dry-run",
            ]
        )
        == 0
    )
    assert "install Claude Code skills" in capsys.readouterr().out
    assert not (tmp_path / "claude").exists()


def test_claude_install_preserves_local_skills_and_force_backs_them_up(monkeypatch, tmp_path):
    from battlemap_mcp import cli

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cli.client_config.shutil, "which", lambda _: None)
    skill = tmp_path / "claude" / "skills" / "battlemap-interiors" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("local version")
    args = ["install", "--mods-dir", str(tmp_path / "mods"), "--client", "claude-code", "--yes"]
    assert cli.main(args) == 0
    assert skill.read_text() == "local version"
    assert cli.main([*args, "--force"]) == 0
    backups = list((tmp_path / "claude" / "backups").rglob("battlemap-interiors.backup-*/SKILL.md"))
    assert len(backups) == 1
    assert backups[0].read_text() == "local version"
    assert skill.read_text() != "local version"


def test_install_preview_reports_runtime_state(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli

    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    assert cli.main(["install", "--mods-dir", str(tmp_path / "mods"), "--dry-run"]) == 0
    assert "runtime state:" in capsys.readouterr().out
    assert not (tmp_path / "state").exists()


def test_transient_install_refuses_registration_before_writing(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli

    monkeypatch.setattr(cli.installer, "codex_skills_dir", lambda: tmp_path / "skills")
    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not register")),
    )
    monkeypatch.setattr(cli.sys, "argv", [str(tmp_path / "uv/archive-v0/abc/bin/server")])
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    assert (
        cli.main(["install", "--mods-dir", str(tmp_path / "mods"), "--client", "codex", "--yes"])
        == 1
    )
    assert "uv tool install" in capsys.readouterr().err
    assert not (tmp_path / "mods").exists()


def test_explicit_durable_launcher_is_registered_without_resolving(monkeypatch, tmp_path):
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    launcher = tmp_path / "bin" / "server"
    calls = []
    monkeypatch.setattr(cli.sys, "argv", [str(tmp_path / "uv/archive-v0/abc/bin/server")])
    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda client, path: calls.append(path) or ClientRegistrationResult(True, None),
    )
    assert (
        cli.main(
            [
                "install",
                "--mods-dir",
                str(tmp_path / "mods"),
                "--client",
                "codex",
                "--server-executable",
                str(launcher),
                "--yes",
            ]
        )
        == 0
    )
    assert calls == [launcher.absolute()]


def test_explicit_mods_mismatch_is_visible_in_preview(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli

    monkeypatch.setattr(cli.installer, "configured_mods_dir", lambda _: tmp_path / "active")
    assert cli.main(["install", "--mods-dir", str(tmp_path / "ignored"), "--dry-run"]) == 0
    assert "Dungeondraft loads mods from" in capsys.readouterr().out
    assert not (tmp_path / "ignored").exists()


def test_doctor_separates_static_log_and_optional_live_evidence(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli

    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(
        cli.installer,
        "latest_log_evidence",
        lambda _: cli.installer.LogEvidence(
            "historical", tmp_path / "logs/godot.log", "/old/mod", 24
        ),
    )
    monkeypatch.setattr(
        cli.installer,
        "live_bridge_identity",
        lambda: cli.installer.LiveIdentity(
            "mismatch",
            "Running source differs.",
            bridge_root=str(tmp_path / "running"),
            process_id=456,
            bridge_sha256="a" * 64,
        ),
    )
    assert cli.main(["doctor", "--mods-dir", str(tmp_path / "mods"), "--live"]) == 1
    output = capsys.readouterr().out
    assert "static files: missing" in output
    assert "latest log (historical; not correlated with live ping)" in output
    assert "protocol: 24" in output
    assert "live identity: mismatch" in output
    assert repr(str(tmp_path / "running")) in output
    assert "process ID: 456" in output
    assert "a" * 64 in output


def test_doctor_without_live_never_contacts_bridge(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli

    monkeypatch.setattr(cli.installer, "default_state_dir", lambda: tmp_path / "state")

    def forbidden():
        pytest.fail("must not connect without --live")

    monkeypatch.setattr(cli.installer, "live_bridge_identity", forbidden)
    assert cli.main(["doctor", "--mods-dir", str(tmp_path / "mods")]) == 1
    assert "live identity: not checked" in capsys.readouterr().out


def test_doctor_defaults_to_discovered_mods_without_creating_files(tmp_path, capsys):
    from battlemap_mcp import cli

    assert cli.main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert str(tmp_path / "default-mods" / "battlemap-mcp-bridge") in output
    assert not (tmp_path / "default-mods").exists()
    assert not (tmp_path / "dd-data").exists()


@pytest.mark.parametrize("status", ["missing", "unknown", "modified", "outdated"])
def test_doctor_static_failures_return_nonzero_even_with_current_live_identity(
    monkeypatch, tmp_path, status
):
    from battlemap_mcp import cli

    monkeypatch.setattr(
        cli.installer,
        "doctor",
        lambda mods_dir, **_: cli.installer.DoctorReport(mods_dir, status, "Review installation."),
    )
    monkeypatch.setattr(
        cli.installer,
        "live_bridge_identity",
        lambda: cli.installer.LiveIdentity("current", "Matches."),
    )
    assert cli.main(["doctor", "--live"]) == 1


@pytest.mark.parametrize("client", ["codex", "claude-code"])
def test_setup_only_installs_skills_and_registers_launcher(monkeypatch, tmp_path, client):
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    def forbidden(*args, **kwargs):
        pytest.fail("setup must not inspect or modify Dungeondraft")

    monkeypatch.setattr(cli.installer, "default_state_dir", forbidden)
    monkeypatch.setattr(cli.installer, "default_mods_dir", forbidden)
    monkeypatch.setattr(cli.installer, "plan_install", forbidden)
    calls = []
    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda c, p: calls.append((c, p)) or ClientRegistrationResult(True, None),
    )
    launcher = tmp_path / "companion.exe"
    assert (
        cli.main(["setup", "--client", client, "--server-executable", str(launcher), "--yes"]) == 0
    )
    directory = tmp_path / ("codex" if client == "codex" else "claude") / "skills"
    assert (directory / "battlemap-interiors" / "SKILL.md").is_file()
    assert calls == [(client, launcher)]
    assert not (tmp_path / "default-mods").exists()


def test_setup_dry_run_is_read_only_and_uses_frozen_executable(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli

    monkeypatch.setattr(cli.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cli.sys, "executable", str(tmp_path / "companion.exe"))
    monkeypatch.setattr(cli.sys, "argv", [str(tmp_path / "_internal" / "entry.py")])
    assert cli.main(["setup", "--client", "codex", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert str(tmp_path / "companion.exe") in output
    assert "entry.py" not in output
    assert not (tmp_path / "codex").exists()


@pytest.mark.parametrize("available", [True, False])
def test_setup_registration_failure_is_nonzero(monkeypatch, tmp_path, capsys, available):
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    monkeypatch.setattr(
        cli.client_config,
        "register_client",
        lambda *_: ClientRegistrationResult(
            False, ["codex", "mcp", "add", "battlemap", "--", "launcher"], available
        ),
    )
    assert cli.main(["setup", "--client", "codex", "--yes"]) == 1
    assert "codex mcp add" in capsys.readouterr().out


def test_version_is_available_offline(capsys):
    from battlemap_mcp import __version__, cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_denied_install_preflight_happens_before_confirmation(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli, preflight

    monkeypatch.setattr(preflight, "directory_write_access", lambda _: "denied")
    monkeypatch.setattr(cli, "_confirm", lambda _: pytest.fail("must not prompt"))
    assert cli.main(["install", "--mods-dir", str(tmp_path / "mods")]) == 1
    assert "denied" in capsys.readouterr().err
    assert not (tmp_path / "mods").exists()


def test_preflight_checks_existing_ancestor_without_creating_destination(tmp_path):
    from battlemap_mcp.preflight import directory_write_access

    destination = tmp_path / "missing" / "mods"
    assert directory_write_access(destination) == "allowed"
    assert not destination.exists()


def test_preflight_rejects_a_file_in_destination_path(tmp_path):
    from battlemap_mcp.preflight import directory_write_access

    occupied = tmp_path / "occupied"
    occupied.write_text("preserve")
    assert directory_write_access(occupied / "mods") == "denied"
    assert occupied.read_text() == "preserve"


def test_setup_noninteractive_requires_yes(monkeypatch, tmp_path):
    from battlemap_mcp import cli

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.main(["setup", "--client", "codex"]) == 2
    assert not (tmp_path / "codex").exists()


def test_setup_preserves_local_skills_and_force_backs_them_up(monkeypatch, tmp_path):
    from battlemap_mcp import cli
    from battlemap_mcp.client_config import ClientRegistrationResult

    monkeypatch.setattr(
        cli.client_config, "register_client", lambda *_: ClientRegistrationResult(True, None)
    )
    skill = tmp_path / "codex" / "skills" / "battlemap-interiors" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("local version")
    args = ["setup", "--client", "codex", "--yes"]
    assert cli.main(args) == 0
    assert skill.read_text() == "local version"
    assert cli.main([*args, "--force"]) == 0
    backups = list((tmp_path / "codex" / "backups").rglob("battlemap-interiors.backup-*/SKILL.md"))
    assert len(backups) == 1
    assert backups[0].read_text() == "local version"
    assert skill.read_text() != "local version"


def test_setup_preview_quotes_posix_command_for_shell(monkeypatch, tmp_path, capsys):
    import shlex

    from battlemap_mcp import cli

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    launcher = tmp_path / "User's Companion" / "server"
    assert (
        cli.main(["setup", "--client", "codex", "--server-executable", str(launcher), "--dry-run"])
        == 0
    )
    command = cli.client_config.registration_argv("codex", launcher)
    assert shlex.join(command) in capsys.readouterr().out


@pytest.mark.parametrize("live_status, expected_code", [("current", 0), ("unavailable", 1)])
def test_brief_connection_check_distinguishes_ready_from_editor_not_running(
    monkeypatch, tmp_path, capsys, live_status, expected_code
):
    from battlemap_mcp import cli, installer

    monkeypatch.setattr(
        installer,
        "doctor",
        lambda *a, **kw: installer.DoctorReport(
            destination=tmp_path / "mods", status="healthy", recommended_action="Current files"
        ),
    )
    monkeypatch.setattr(
        installer,
        "live_bridge_identity",
        lambda: installer.LiveIdentity(live_status, "test identity"),
    )
    assert cli.main(["doctor", "--live", "--brief"]) == expected_code
    output = capsys.readouterr().out
    if expected_code == 0:
        assert "Ready" in output
    else:
        assert "open or create a map" in output
        assert "update the bridge" not in output
    assert "SHA-256" not in output


def test_denied_install_guidance_uses_configured_folder(monkeypatch, tmp_path, capsys):
    from battlemap_mcp import cli, preflight

    monkeypatch.setattr(preflight, "directory_write_access", lambda _: "denied")
    assert cli.main(["install", "--dry-run"]) == 1
    error = capsys.readouterr().err
    assert "then rerun install." in error
    assert "--mods-dir" not in error
