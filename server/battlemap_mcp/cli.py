"""Console entry point for the Dungeondraft MCP server and installer."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, client_config, installer, preflight, server, state_paths


def build_parser() -> argparse.ArgumentParser:
    """Build the command parser for opt-in local installation actions."""
    parser = argparse.ArgumentParser(prog="battlemap-mcp")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    setup = commands.add_parser("setup", help="install client skills and register this launcher")
    setup.add_argument("--client", required=True, choices=("codex", "claude-code"))
    setup.add_argument("--server-executable", type=Path, help="durable MCP server launcher")
    for flag in ("--dry-run", "--force", "--yes"):
        setup.add_argument(flag, action="store_true")

    install = commands.add_parser(
        "install", help="install the Dungeondraft bridge and optional skills"
    )
    install.add_argument("--mods-dir", type=Path)
    install.add_argument("--server-executable", type=Path, help="durable MCP server launcher")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--force", action="store_true")
    install.add_argument("--yes", action="store_true")
    install.add_argument("--client", choices=("claude-code", "codex", "none"), default="none")

    doctor = commands.add_parser("doctor", help="check the installed bridge")
    doctor.add_argument("--mods-dir", type=Path)
    doctor.add_argument("--brief", action="store_true", help="show a simple connection result")
    doctor.add_argument(
        "--live", action="store_true", help="authenticate and compare the running bridge"
    )

    uninstall = commands.add_parser("uninstall", help="remove the installed bridge")
    uninstall.add_argument("--mods-dir", required=True, type=Path)
    uninstall.add_argument("--yes", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the stdio MCP server when invoked without a subcommand."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        server.main()
        return 0

    return dispatch_installer(build_parser().parse_args(arguments))


def dispatch_installer(args: argparse.Namespace) -> int:
    """Run an explicitly selected installer command after showing its plan."""
    if args.command == "setup":
        return _setup(args)
    state_dir = installer.default_state_dir()
    if args.command == "doctor":
        report = installer.doctor(
            args.mods_dir or installer.default_mods_dir(), state_dir=state_dir
        )
        if args.brief:
            return _brief_doctor(report, live=args.live)
        print(f"static files: {report.status}: {report.destination}")
        print(report.recommended_action)
        evidence = installer.latest_log_evidence(installer.dungeondraft_data_dir())
        print(f"latest log (historical; not correlated with live ping): {evidence.status}")
        if evidence.path is not None:
            print(f"  log: {evidence.path}")
        print(f"  mod path: {evidence.mod_path!r}; protocol: {evidence.protocol}")
        if len(evidence.mod_paths) > 1:
            print(
                "  Multiple bridge copies discovered; log order does not identify the loaded copy."
            )
            for candidate in evidence.mod_paths:
                print(f"  candidate: {candidate}")
        live_ok = True
        if args.live:
            identity = installer.live_bridge_identity()
            print(f"live identity: {identity.status}: {identity.detail}")
            print(f"  loaded mod root: {identity.bridge_root!r}")
            print(f"  process ID: {identity.process_id}; source SHA-256: {identity.bridge_sha256}")
            if identity.status == "unavailable":
                print(
                    "  Start Dungeondraft, enable Battlemap MCP Bridge, then open or create a map."
                )
                print("  Wait for loading to finish and close any dialogs before checking again.")
            elif identity.bridge_root is None:
                print(
                    "  Loaded path unavailable; update the bridge to report its runtime location."
                )
            live_ok = identity.status == "current"
        else:
            print("live identity: not checked (use --live)")
        for label, path in client_config.claude_registry_paths().items():
            print(f"{label}: {client_config.inspect_registration(path)} [{path}]")
        for label, destination in (
            ("Codex", installer.codex_skills_dir()),
            ("Claude Code", installer.claude_code_skills_dir()),
        ):
            print(f"{label} skills: {destination}")
            for name, status in installer.inspect_skills(destination).items():
                print(f"  {name}: {status}")
        return 0 if report.status == "healthy" and live_ok else 1

    if args.command == "uninstall":
        print(f"remove bridge: {args.mods_dir / 'battlemap-mcp-bridge'}")
        if not _confirm(args.yes):
            return 2
        result = installer.uninstall(args.mods_dir, state_dir=state_dir)
        if not result.changed:
            print("Bridge was not removed because it is unknown or modified.", file=sys.stderr)
            return 1
        print(f"uninstalled: {result.destination}")
        return 0

    if args.command != "install":
        return 2

    executable = _launcher(args.server_executable)
    if args.client != "none":
        try:
            client_config.validate_launcher(executable)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    now = datetime.now(UTC)
    mods_dir = args.mods_dir or installer.default_mods_dir()
    plan = installer.plan_install(mods_dir, now, state_dir=state_dir)
    client_label = "Codex" if args.client == "codex" else "Claude Code"
    skills_dir = (
        installer.codex_skills_dir()
        if args.client == "codex"
        else installer.claude_code_skills_dir()
    )
    skills_plan = (
        installer.plan_codex_skills_install(skills_dir, now)
        if args.client in {"codex", "claude-code"}
        else None
    )
    for action in plan.actions:
        print(action)
    print(f"destination: {plan.destination}")
    print(f"runtime state: {state_paths.state_dir()}")
    configured = installer.configured_mods_dir(installer.dungeondraft_data_dir() / "config.ini")
    if configured is not None and configured.resolve() != mods_dir.resolve():
        print(
            f"Warning: Dungeondraft loads mods from {configured}, not {mods_dir}. "
            "Select the intended directory in Dungeondraft before using this install."
        )
    if skills_plan is not None:
        print(f"install {client_label} skills: {skills_plan.destination}")
    access = preflight.directory_write_access(plan.destination)
    print(f"destination write access: {access}")
    if access == "denied":
        print(
            f"Write access was denied for {plan.destination}. Choose a writable mods directory "
            "in Dungeondraft settings, then rerun install.",
            file=sys.stderr,
        )
        return 1
    if access == "unknown":
        print("Write access could not be verified without modifying files; installation may fail.")
    if args.dry_run:
        return 0

    if not _confirm(args.yes):
        return 2

    try:
        result = installer.apply_install(plan, force=args.force)
    except installer.InstallConflictError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except PermissionError:
        print(
            f"Write access was denied for {plan.destination}. "
            "Choose a writable mods directory in Dungeondraft settings, then rerun install. "
            "Dungeondraft must be configured to load the selected directory.",
            file=sys.stderr,
        )
        return 1

    print(f"installed: {result.destination}")
    if skills_plan is not None:
        try:
            installer.apply_codex_skills_install(skills_plan, force=args.force)
        except installer.InstallConflictError as exc:
            print(
                f"Bridge was installed, but {client_label} skills were not updated: {exc}",
                file=sys.stderr,
            )
            return 1
        except PermissionError:
            print(
                f"Bridge was installed, but write access was denied for {client_label} skills at "
                f"{skills_plan.destination}.",
                file=sys.stderr,
            )
            return 1
        print(f"{client_label} skills installed: {skills_plan.destination}")
    registration = client_config.register_client(
        args.client,
        executable,
    )
    if registration.manual_command is not None:
        client_label = "Codex" if args.client == "codex" else "Claude Code"
        if registration.client_cli_available:
            print(f"{client_label} CLI registration failed. Run:")
        else:
            installed_content = f"bridge and {client_label} skills"
            print(f"{client_label} CLI was not available; {installed_content} installed. Run:")
        print(_display_command(registration.manual_command))
        return 1
    return 0


def _confirm(yes: bool) -> bool:
    """Require explicit consent for every non-dry-run filesystem mutation."""
    if yes:
        return True
    if not sys.stdin.isatty():
        print("Non-interactive install requires --yes.", file=sys.stderr)
        return False
    return input("Apply these changes? [y/N] ").strip().lower() in {"y", "yes"}


def _launcher(override: Path | None) -> Path:
    """A frozen bundle registers its executable, never its internal Python script."""
    return (
        (override or Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
        .expanduser()
        .absolute()
    )


def _setup(args: argparse.Namespace) -> int:
    """Install only client-owned skills and register the durable stdio launcher."""
    executable = _launcher(args.server_executable)
    try:
        command = client_config.registration_argv(args.client, executable)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    destination = (
        installer.codex_skills_dir()
        if args.client == "codex"
        else installer.claude_code_skills_dir()
    )
    plan = installer.plan_codex_skills_install(destination, datetime.now(UTC))
    print(f"install {args.client} skills: {destination}")
    print(f"register launcher: {_display_command(command)}")
    if args.dry_run:
        return 0
    if not _confirm(args.yes):
        return 2
    try:
        result = installer.apply_codex_skills_install(plan, force=args.force)
    except (installer.InstallConflictError, OSError) as exc:
        print(f"Skills installation failed at {destination}: {exc}", file=sys.stderr)
        return 1
    print(f"Skills installed: {result.destination}")
    registration = client_config.register_client(args.client, executable)
    if not registration.registered:
        reason = "failed" if registration.client_cli_available else "was not available"
        print(f"Automatic connection to {args.client} {reason}.")
        if args.client == "codex":
            print("You can connect in the app without installing a command-line tool:")
            print("Settings > MCP servers > Add server; choose STDIO.")
            print("Name: battlemap")
            print(f"Command: {executable}")
            print("Leave arguments empty, save, then restart the connection.")
        else:
            print("If battlemap is already registered at an old location, remove that entry:")
            print("claude mcp remove --scope user battlemap")
            print("Then run this Connect file again. Keep your old companion until it succeeds.")
        print("If the client command-line tool is available, you can also run:")
        print(_display_command(registration.manual_command or command))
        return 1
    print(f"Registered battlemap with {args.client}.")
    print("Setup complete. Fully quit and reopen your AI client to load the connection.")
    print("In Dungeondraft, enable Battlemap MCP Bridge and open a map before using it.")
    return 0


def _brief_doctor(report: installer.DoctorReport, *, live: bool) -> int:
    if report.status != "healthy":
        print("The mod files need attention.")
        print(f"Expected folder: {report.destination}")
        print("Extract the matching mod ZIP into the folder selected under Dungeondraft > Mods.")
        print("Keep one Battlemap MCP Bridge copy, then fully quit and reopen Dungeondraft.")
        return 1
    if not live:
        print("Mod files are ready. Use doctor --live --brief to check the connection.")
        return 0
    identity = installer.live_bridge_identity()
    if identity.status == "current":
        print("Ready: connected to Battlemap MCP Bridge. The mod matches this companion.")
        print("Keep a map open in Dungeondraft. Reopen your AI client after first-time setup.")
        return 0
    if identity.status == "unavailable":
        print("Not connected yet.")
        print(
            "Start Dungeondraft, enable Battlemap MCP Bridge under Mods, then open or create a map."
        )
        print("Wait for loading to finish and close any dialogs, then check again.")
    else:
        print("Dungeondraft is running a different or older Battlemap MCP Bridge.")
        print("Use the mod ZIP from the same release as this companion. Keep only one copy.")
        print("Fully quit and reopen Dungeondraft, then open your map and check again.")
    return 1


def _display_command(command: list[str]) -> str:
    """Render recovery commands using the platform's command-line quoting."""
    return subprocess.list2cmdline(command) if sys.platform == "win32" else shlex.join(command)
