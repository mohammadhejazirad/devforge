"""Argument parsing and command dispatch."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import IO, TextIO

from devforge import __version__
from devforge import strings as s
from devforge.commands.common import run_plan
from devforge.commands.configuration import cmd_config
from devforge.commands.files import (
    cmd_apply,
    cmd_export,
    cmd_preset_apply,
    cmd_preset_list,
    cmd_shell,
)
from devforge.commands.inspect import cmd_doctor, cmd_info, cmd_list, cmd_status, cmd_versions
from devforge.commands.lifecycle import cmd_install, cmd_uninstall, cmd_update, cmd_use
from devforge.commands.network import (
    cmd_dns_restore,
    cmd_dns_set,
    cmd_dns_show,
    cmd_dns_test,
    cmd_mirror_list,
    cmd_mirror_reset,
    cmd_mirror_set,
    cmd_mirror_test,
)
from devforge.commands.release import cmd_self_update
from devforge.commands.services import ACTIONS, cmd_service
from devforge.commands.terminal import cmd_terminal
from devforge.context import Context, make_context
from devforge.core.database import DATABASES, backup_plan
from devforge.core.log import redact
from devforge.core.terminal import ACTIONS as TERMINAL_ACTIONS
from devforge.tools.base import Scope
from devforge.tui import cmd_tui
from devforge.ui import Printer


def build_parser() -> argparse.ArgumentParser:
    """Return the top-level parser, including every subcommand."""
    parser = argparse.ArgumentParser(
        prog="devforge",
        description=s.DESCRIPTION,
        epilog=s.HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Python 3.14 colors help from the process TTY, not from the stream
    # help is written to. Keep help plain so it matches 3.9 and NO_COLOR.
    if hasattr(parser, "color"):
        parser.color = False
    parser.add_argument(
        "--version",
        action="version",
        version=s.VERSION_TEMPLATE.format(version=__version__),
    )
    parser.add_argument("--dry-run", action="store_true", help=s.HELP_DRY_RUN)
    parser.add_argument("-y", "--yes", action="store_true", help=s.HELP_YES)
    parser.add_argument("--json", action="store_true", help=s.HELP_JSON)
    parser.add_argument("--no-color", action="store_true", help=s.HELP_NO_COLOR)
    parser.add_argument("-q", "--quiet", action="store_true", help=s.HELP_QUIET)
    parser.add_argument("-v", "--verbose", action="count", default=0, help=s.HELP_VERBOSE)

    commands = parser.add_subparsers(dest="command")

    commands.add_parser("info", help="Show the detected operating system and privileges.")
    doctor = commands.add_parser("doctor", help="Check the machine and every managed tool.")
    doctor.add_argument("--offline", action="store_true", help="Do not contact the network.")
    doctor.add_argument("--online", action="store_true", help="Probe a few upstream URLs.")

    commands.add_parser("list", help="List every tool DevForge can manage.")
    status = commands.add_parser("status", help="Show installed versions and available updates.")
    status.add_argument("tool", nargs="?", help="One tool. Omit it to show every tool.")

    versions = commands.add_parser("versions", help="List known versions for one tool.")
    versions.add_argument("tool")
    versions.add_argument(
        "--refresh", action="store_true", help="Download the upstream index first."
    )

    install = commands.add_parser(
        "install", help="Install a tool, keeping other versions in place."
    )
    install.add_argument("tool")
    install.add_argument(
        "version", nargs="?", help="Version to install. Omit it for the preferred one."
    )
    install.add_argument(
        "--no-default", action="store_true", help="Do not make this version the default."
    )
    install.add_argument(
        "--package",
        action="store_true",
        help="Use the distro package even when an official archive exists.",
    )

    update = commands.add_parser("update", help="Update one tool, or every installed tool.")
    update.add_argument("tool", nargs="?")
    update.add_argument(
        "--all", action="store_true", help="Update every tool that is already installed."
    )

    use = commands.add_parser(
        "use", help="Select a version globally, for a project, or for this shell."
    )
    use.add_argument("tool")
    use.add_argument("version")
    scope = use.add_mutually_exclusive_group()
    scope.add_argument(
        "--global", dest="scope_global", action="store_true", help="Set the user default."
    )
    scope.add_argument("--project", action="store_true", help="Pin the version in this directory.")
    scope.add_argument(
        "--shell", action="store_true", help="Print an export for the current shell."
    )

    pin = commands.add_parser("pin", help="Pin a version in the current directory.")
    pin.add_argument("tool")
    pin.add_argument("version")

    uninstall = commands.add_parser("uninstall", help="Remove a managed version or distro package.")
    uninstall.add_argument("tool")
    uninstall.add_argument("version", nargs="?")
    uninstall.add_argument(
        "--purge", action="store_true", help="Also remove package configuration."
    )

    config = commands.add_parser(
        "config", help="Inspect, validate or apply edited Nginx configuration."
    )
    config.add_argument("tool", choices=("nginx",))
    config.add_argument("action", choices=("show", "check", "apply"))
    config.add_argument("file", nargs="?", type=Path)

    backup = commands.add_parser("backup", help="Create a private native database backup.")
    backup.add_argument("tool", choices=DATABASES)
    backup.add_argument("database", nargs="?", help="Database name; required for PostgreSQL.")
    backup.add_argument(
        "--client-config",
        type=Path,
        help="Private mongodump YAML config for authenticated MongoDB backups.",
    )
    service = commands.add_parser("service", help="Inspect or control a tool's system service.")
    service.add_argument("tool")
    service.add_argument("action", choices=ACTIONS)

    mirror = commands.add_parser("mirror", help="List, select, test, or clear a mirror profile.")
    mirror_cmds = mirror.add_subparsers(dest="mirror_action", required=True)
    mirror_cmds.add_parser("list", help="Show profiles. The default is upstream.")
    mirror_set = mirror_cmds.add_parser("set", help="Use a profile. Pass upstream to clear it.")
    mirror_set.add_argument("name")
    mirror_test = mirror_cmds.add_parser("test", help="Time a request through a profile.")
    mirror_test.add_argument("name", nargs="?")
    mirror_cmds.add_parser("reset", help="Clear the profile and restore a Docker backup.")

    dns = commands.add_parser("dns", help="Show, set, test, or restore DNS.")
    dns_cmds = dns.add_subparsers(dest="dns_action", required=True)
    dns_cmds.add_parser("show", help="Show the resolver and the shipped presets.")
    dns_set = dns_cmds.add_parser("set", help="Switch to a named preset.")
    dns_set.add_argument("name")
    dns_cmds.add_parser("test", help="Resolve example.com.")
    dns_cmds.add_parser("restore", help="Restore the DevForge DNS backup.")

    preset = commands.add_parser("preset", help="List or apply a tool preset.")
    preset_cmds = preset.add_subparsers(dest="preset_action", required=True)
    preset_cmds.add_parser("list", help="Show the shipped presets.")
    preset_apply = preset_cmds.add_parser("apply", help="Install every tool in a preset.")
    preset_apply.add_argument("name")

    apply = commands.add_parser("apply", help="Install the tools listed in a JSON or TOML file.")
    apply.add_argument("file")

    commands.add_parser("export", help="Print a JSON manifest of installed tools.")

    shell = commands.add_parser("shell", help="Install or remove the DevForge PATH block.")
    shell_cmds = shell.add_subparsers(dest="shell_action", required=True)
    shell_cmds.add_parser("install", help="Add the shim directory to the shell rc file.")
    shell_cmds.add_parser("remove", help="Remove the managed block from the shell rc file.")

    tui = commands.add_parser("tui", help="Open the Textual interface. Requires a terminal.")
    tui.add_argument("--plain", action="store_true", help="Use the numbered fallback menu.")
    terminal = commands.add_parser(
        "terminal", help="Choose Zsh plugins and prompt themes individually."
    )
    terminal.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=("show", "install-zsh", "install-starship", *TERMINAL_ACTIONS),
    )
    terminal.add_argument("--theme", choices=("minimal", "midnight", "classic", "server"))
    commands.add_parser(
        "self-update",
        help="Install a newer DevForge release. Managed tools are left in place.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run DevForge. Returns a process status code."""
    parser = build_parser()
    supplied = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(supplied)
    printer = Printer.create(
        no_color=args.no_color,
        quiet=args.quiet,
        verbose=args.verbose,
        assume_yes=args.yes,
        dry_run=args.dry_run,
        out=out,
        err=err,
    )
    if not args.command:
        if not supplied and _menu_tty(printer.stream):
            ctx = make_context(
                printer,
                dry_run=args.dry_run,
                assume_yes=args.yes,
                as_json=args.json,
                offline=False,
            )
            ctx.log.info("devforge")
            try:
                return cmd_tui(ctx, force=True)
            except KeyboardInterrupt:
                printer.error(s.ERR_INTERRUPTED)
                return 1
            except (OSError, ValueError, RuntimeError) as exc:
                printer.error("Cannot complete operation: " + redact(str(exc)))
                return 1
        printer.error(s.ERR_NO_COMMAND)
        parser.print_help(printer.error_stream)
        return 2
    ctx = make_context(
        printer,
        dry_run=args.dry_run,
        assume_yes=args.yes,
        as_json=args.json,
        offline=bool(getattr(args, "offline", False)),
    )
    ctx.log.info(" ".join(sys.argv if argv is None else ["devforge", *list(argv)]))
    try:
        return _dispatch(ctx, args)
    except KeyboardInterrupt:
        printer.error(s.ERR_INTERRUPTED)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        printer.error("Cannot complete operation: " + redact(str(exc)))
        return 1


def _dispatch(ctx: Context, args: argparse.Namespace) -> int:
    command = args.command
    if command == "info":
        return cmd_info(ctx)
    if command == "doctor":
        return cmd_doctor(ctx, online=bool(args.online) and not bool(args.offline))
    if command == "list":
        return cmd_list(ctx)
    if command == "status":
        return cmd_status(ctx, args.tool)
    if command == "versions":
        return cmd_versions(ctx, args.tool, refresh=bool(args.refresh))
    if command == "install":
        return cmd_install(
            ctx,
            args.tool,
            args.version,
            make_default=not args.no_default,
            use_package=bool(args.package),
        )
    if command == "update":
        return cmd_update(ctx, args.tool, all_tools_flag=bool(args.all))
    if command == "use":
        if args.shell:
            scope = Scope.SHELL
        elif args.project:
            scope = Scope.PROJECT
        else:
            scope = Scope.GLOBAL
        return cmd_use(ctx, args.tool, args.version, scope=scope)
    if command == "pin":
        return cmd_use(ctx, args.tool, args.version, scope=Scope.PROJECT)
    if command == "uninstall":
        return cmd_uninstall(ctx, args.tool, args.version, purge=bool(args.purge))
    if command == "config":
        return cmd_config(ctx, args.tool, args.action, args.file)
    if command == "backup":
        return run_plan(ctx, backup_plan(ctx, args.tool, args.database, args.client_config))
    if command == "service":
        return cmd_service(ctx, args.tool, args.action)
    if command == "mirror":
        return _mirror(ctx, args)
    if command == "dns":
        return _dns(ctx, args)
    if command == "preset":
        if args.preset_action == "list":
            return cmd_preset_list(ctx)
        return cmd_preset_apply(ctx, args.name)
    if command == "apply":
        return cmd_apply(ctx, Path(args.file))
    if command == "export":
        return cmd_export(ctx)
    if command == "shell":
        return cmd_shell(ctx, str(args.shell_action))
    if command == "terminal":
        return cmd_terminal(ctx, args.action, args.theme)
    if command == "tui":
        return cmd_tui(ctx, plain=args.plain)
    if command == "self-update":
        return cmd_self_update(ctx)
    ctx.printer.error(s.ERR_UNKNOWN_COMMAND.format(name=command))
    return 2


def _mirror(ctx: Context, args: argparse.Namespace) -> int:
    action = args.mirror_action
    if action == "list":
        return cmd_mirror_list(ctx)
    if action == "set":
        return cmd_mirror_set(ctx, args.name)
    if action == "test":
        return cmd_mirror_test(ctx, args.name)
    if action == "reset":
        return cmd_mirror_reset(ctx)
    ctx.printer.error(s.ERR_UNKNOWN_COMMAND.format(name=action))
    return 2


def _dns(ctx: Context, args: argparse.Namespace) -> int:
    action = args.dns_action
    if action == "show":
        return cmd_dns_show(ctx)
    if action == "set":
        return cmd_dns_set(ctx, args.name)
    if action == "test":
        return cmd_dns_test(ctx)
    if action == "restore":
        return cmd_dns_restore(ctx)
    ctx.printer.error(s.ERR_UNKNOWN_COMMAND.format(name=action))
    return 2


def _menu_tty(stream: IO[str]) -> bool:
    """True when both stdin and the output stream are terminals."""
    try:
        return bool(sys.stdin.isatty() and stream.isatty())
    except (AttributeError, ValueError):
        return False


def entrypoint() -> None:
    """Console-script entry. Propagates the status code."""
    sys.exit(main())
