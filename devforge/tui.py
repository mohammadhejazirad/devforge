"""Numbered terminal menu.

``devforge`` with no arguments opens this menu when stdin and stdout are both
terminals. Flags alone, and a non-terminal, still print help and exit 2.
``devforge tui`` opens the same menu.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import IO

from devforge import __version__
from devforge import strings as s
from devforge.commands.files import _load_presets, cmd_preset_apply, cmd_shell
from devforge.commands.inspect import cmd_doctor, cmd_info, cmd_status, cmd_versions
from devforge.commands.lifecycle import cmd_install, cmd_uninstall, cmd_update, cmd_use
from devforge.commands.network import cmd_dns_restore, cmd_dns_set, cmd_mirror_reset, cmd_mirror_set
from devforge.commands.release import cmd_self_update
from devforge.context import Context
from devforge.core.dns import DnsError, load_presets
from devforge.core.mirrors import load_profiles
from devforge.core.release import check_newer
from devforge.core.versioning import Version, is_valid_version
from devforge.tools.base import Scope, ToolStatus
from devforge.tools.catalog import load_index
from devforge.tools.engine import _known_newest
from devforge.tools.managed import ManagedTool, all_tools

_CATEGORIES = (
    ("runtime", "Languages"),
    ("manager", "Package tools"),
    ("infra", "Infrastructure"),
    ("service", "Services"),
    ("utility", "Utilities"),
)


def cmd_tui(ctx: Context, *, force: bool = False) -> int:
    """Open the menu, or tell the user to pass a command when this is not a terminal."""
    if not force and not _interactive(ctx.printer.stream):
        ctx.printer.error(s.ERR_MENU_NEEDS_TTY)
        return 2
    return menu(ctx, _stdin_lines())


def menu(ctx: Context, lines: Iterator[str]) -> int:
    """Run the menu from ``lines``. Tests pass a list iterator."""
    ctx.printer.info("Checking installed tools...")
    rows = _inventory(ctx)
    while True:
        _draw_home(ctx, rows)
        choice = _ask(ctx, lines, "Choice")
        if choice is None or choice in {"0", "q", "quit", "exit"}:
            return 0
        action = _ACTIONS.get(choice)
        if action is not None:
            action(ctx, lines)
            _pause(ctx, lines)
            ctx.printer.info("Checking installed tools...")
            rows = _inventory(ctx)
            continue
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(rows):
                if _tool_menu(ctx, lines, rows[index - 1][0]):
                    ctx.printer.info("Checking installed tools...")
                    rows = _inventory(ctx)
                continue
        ctx.printer.error(f"Unknown choice {choice!r}. Enter a number or a letter from the menu.")


def _draw_home(ctx: Context, rows: list[tuple[ManagedTool, str]]) -> None:
    system = ctx.system()
    ctx.printer.raw("")
    ctx.printer.info(f"DevForge {__version__}")
    manager = system.package_manager or "no package manager"
    ctx.printer.raw(f"  {system.pretty_name} ({system.family}) | {manager}")
    notice = check_newer(ctx)
    if notice is not None:
        ctx.printer.info(s.INFO_RELEASE_AVAILABLE.format(version=notice.version))
    ctx.printer.raw("")
    ctx.printer.raw("Tools  (enter a number)")
    grouped: dict[str, list[tuple[int, ManagedTool, str]]] = {}
    for number, (tool, label) in enumerate(rows, start=1):
        grouped.setdefault(tool.spec.category, []).append((number, tool, label))
    shown: set[str] = set()
    for category, title in _CATEGORIES:
        items = grouped.get(category, [])
        if not items:
            continue
        shown.add(category)
        ctx.printer.raw(f"  {title}")
        for number, tool, label in items:
            ctx.printer.raw(f"    {number:>2}  {tool.name:<12} {label}")
    for category, items in grouped.items():
        if category in shown:
            continue
        ctx.printer.raw(f"  {category}")
        for number, tool, label in items:
            ctx.printer.raw(f"    {number:>2}  {tool.name:<12} {label}")
    ctx.printer.raw("")
    ctx.printer.raw("Actions  (enter a letter)")
    for key, label in _ACTION_LABELS:
        ctx.printer.raw(f"   {key}  {label}")
    ctx.printer.raw("   0  Exit")


def _inventory(ctx: Context) -> list[tuple[ManagedTool, str]]:
    rows: list[tuple[ManagedTool, str]] = []
    server = ctx.system().form_factor == "server"
    for tool in all_tools():
        if tool.spec.desktop_only and server:
            continue
        info = tool.detect(ctx)
        if not info.current:
            rows.append((tool, "not installed"))
            continue
        label = info.current
        newest = _known_newest(load_index(ctx.data_root, tool.name, cache=ctx.paths.cache))
        if (
            newest
            and is_valid_version(info.current)
            and is_valid_version(newest)
            and Version(newest) > Version(info.current)
        ):
            label = f"{info.current}  (newer {newest})"
        rows.append((tool, label))
    return rows


def _tool_menu(ctx: Context, lines: Iterator[str], tool: ManagedTool) -> bool:
    """Manage one tool. Returns True when an install, update, or removal ran."""
    status = tool.status(ctx)
    while True:
        options = _tool_options(status)
        ctx.printer.raw("")
        ctx.printer.info(f"{tool.name} - {tool.spec.summary}")
        current = status.installed_version or "not installed"
        ctx.printer.raw(f"  installed:    {current} ({status.source})")
        if status.latest:
            ctx.printer.raw(f"  newest known: {status.latest}")
        if status.update_available is True:
            ctx.printer.raw("  update:       available")
        elif status.installed_version:
            ctx.printer.raw("  update:       up to date")
        for note in status.notes:
            ctx.printer.raw(f"  note:         {note}")
        ctx.printer.raw("")
        for index, (label, _kind) in enumerate(options, start=1):
            ctx.printer.raw(f"  {index}  {label}")
        ctx.printer.raw("  0  back")
        choice = _ask(ctx, lines, "Choice")
        if choice is None or choice == "0":
            return False
        if not choice.isdigit() or not 1 <= int(choice) <= len(options):
            ctx.printer.error("Enter a number from the list.")
            continue
        kind = options[int(choice) - 1][1]
        changed = _run_tool_action(ctx, lines, tool, kind)
        _pause(ctx, lines)
        if changed:
            return True
        status = tool.status(ctx)


def _tool_options(status: ToolStatus) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    if status.can_install:
        options.append(("Install the preferred version", "install"))
        options.append(("Install a specific version", "install-version"))
    if status.can_update:
        options.append(("Update", "update"))
    if status.can_switch:
        options.append(("Switch the default", "switch"))
        options.append(("Pin this directory", "pin"))
    if status.can_uninstall:
        options.append(("Uninstall", "uninstall"))
    options.append(("Show full status", "status"))
    options.append(("List known versions", "versions"))
    return options


def _run_tool_action(ctx: Context, lines: Iterator[str], tool: ManagedTool, kind: str) -> bool:
    if kind == "install":
        cmd_install(ctx, tool.name, None, make_default=True, use_package=False)
        return True
    if kind == "install-version":
        version = _pick_version(ctx, lines, tool)
        if version:
            cmd_install(ctx, tool.name, version, make_default=True, use_package=False)
            return True
        return False
    if kind == "update":
        cmd_update(ctx, tool.name, all_tools_flag=False)
        return True
    if kind == "switch":
        version = _pick_version(ctx, lines, tool)
        scope = _pick_scope(ctx, lines) if version else None
        if version and scope is not None:
            cmd_use(ctx, tool.name, version, scope=scope)
            return True
        return False
    if kind == "pin":
        version = _pick_version(ctx, lines, tool)
        if version:
            cmd_use(ctx, tool.name, version, scope=Scope.PROJECT)
            return True
        return False
    if kind == "uninstall":
        version = _pick_uninstall_version(ctx, lines, tool)
        if version is not None:
            cmd_uninstall(ctx, tool.name, version or None, purge=False)
            return True
        return False
    if kind == "status":
        cmd_status(ctx, tool.name)
        return False
    if kind == "versions":
        cmd_versions(ctx, tool.name, refresh=False)
        return False
    return False


def _pick_version(ctx: Context, lines: Iterator[str], tool: ManagedTool) -> str | None:
    shown = [item for item in tool.available_versions(ctx) if is_valid_version(item)][:15]
    ctx.printer.raw("")
    ctx.printer.info(f"Versions of {tool.name}")
    if not shown:
        ctx.printer.raw("  No version list is shipped. Type the version you want.")
    for index, version in enumerate(shown, start=1):
        ctx.printer.raw(f"  {index:>2}  {version}")
    ctx.printer.raw("   t  type a version")
    ctx.printer.raw("   0  back")
    choice = _ask(ctx, lines, "Version")
    if choice is None or choice in {"", "0"}:
        return None
    if choice == "t":
        typed = _ask(ctx, lines, "Version string")
        return typed or None
    if choice.isdigit() and 1 <= int(choice) <= len(shown):
        return shown[int(choice) - 1]
    ctx.printer.error("Enter a number from the list, or t to type a version.")
    return None


def _pick_scope(ctx: Context, lines: Iterator[str]) -> Scope | None:
    ctx.printer.raw("")
    ctx.printer.raw("  1  for your user (global)")
    ctx.printer.raw("  2  this directory only")
    ctx.printer.raw("  3  this shell only (prints an export)")
    ctx.printer.raw("  0  back")
    choice = _ask(ctx, lines, "Where should this version apply")
    return {"1": Scope.GLOBAL, "2": Scope.PROJECT, "3": Scope.SHELL}.get(choice or "")


def _pick_uninstall_version(ctx: Context, lines: Iterator[str], tool: ManagedTool) -> str | None:
    """Return ``""`` to remove the default, a version string, or None to cancel."""
    ctx.printer.raw("")
    ctx.printer.raw("  1  remove the current default")
    ctx.printer.raw("  2  remove a specific version")
    ctx.printer.raw("  0  back")
    choice = _ask(ctx, lines, "Uninstall")
    if choice == "1":
        return ""
    if choice == "2":
        return _pick_version(ctx, lines, tool)
    return None


def _info(ctx: Context, lines: Iterator[str]) -> None:
    del lines
    cmd_info(ctx)


def _doctor(ctx: Context, lines: Iterator[str]) -> None:
    del lines
    cmd_doctor(ctx, online=False)


def _update_all(ctx: Context, lines: Iterator[str]) -> None:
    del lines
    cmd_update(ctx, None, all_tools_flag=True)


def _self_update(ctx: Context, lines: Iterator[str]) -> None:
    del lines
    cmd_self_update(ctx)


def _help(ctx: Context, lines: Iterator[str]) -> None:
    del lines
    ctx.printer.info("How to use the menu")
    ctx.printer.raw("  Enter a tool number, then choose install, update, switch, pin, or remove.")
    ctx.printer.raw("  Every change shows a plan first. Answer y to apply it.")
    ctx.printer.raw("  Letters open this computer, doctor, presets, mirrors, DNS, and updates.")
    ctx.printer.raw("  The same actions work as commands. A few you will use often:")
    ctx.printer.raw("    devforge status php")
    ctx.printer.raw("    devforge install node")
    ctx.printer.raw("    devforge --dry-run update --all")
    ctx.printer.raw("    devforge self-update")
    ctx.printer.raw("    devforge --help")


def _presets(ctx: Context, lines: Iterator[str]) -> None:
    loaded = _load_presets(ctx.data_root / "presets")
    if isinstance(loaded, str):
        ctx.printer.error(loaded)
        return
    ctx.printer.info("A preset installs several tools. You see the plan before anything changes.")
    for index, preset in enumerate(loaded, start=1):
        names = preset.get("tools", [])
        tools = ", ".join(str(name) for name in names) if isinstance(names, list) else ""
        ctx.printer.raw(f"  {index}  {preset['name']:<16} {preset['summary']} ({tools})")
    ctx.printer.raw("  0  back")
    choice = _ask(ctx, lines, "Preset")
    if choice is None or choice in {"", "0"} or not choice.isdigit():
        return
    index = int(choice)
    if not 1 <= index <= len(loaded):
        ctx.printer.error("Enter a number from the list.")
        return
    name = loaded[index - 1].get("name")
    if isinstance(name, str):
        cmd_preset_apply(ctx, name)


def _mirrors(ctx: Context, lines: Iterator[str]) -> None:
    profiles = list(load_profiles(ctx.data_root).values())
    ctx.printer.info("Pick a download mirror. upstream is the default.")
    for index, profile in enumerate(profiles, start=1):
        mark = "verified" if profile.verified else "unverified"
        ctx.printer.raw(f"  {index}  {profile.name:<12} {mark:<12} {profile.description}")
    clear = len(profiles) + 1
    ctx.printer.raw(f"  {clear}  upstream     clear the mirror and use the original sites")
    ctx.printer.raw("  0  back")
    choice = _ask(ctx, lines, "Mirror")
    if choice is None or choice in {"", "0"} or not choice.isdigit():
        return
    index = int(choice)
    if index == clear:
        cmd_mirror_reset(ctx)
        return
    if not 1 <= index <= len(profiles):
        ctx.printer.error("Enter a number from the list.")
        return
    cmd_mirror_set(ctx, profiles[index - 1].name)


def _dns(ctx: Context, lines: Iterator[str]) -> None:
    try:
        presets = list(load_presets(ctx.data_root / "dns.json").values())
    except DnsError as exc:
        ctx.printer.error(str(exc))
        return
    ctx.printer.info("DNS presets replace the resolver. DevForge keeps a backup.")
    for index, preset in enumerate(presets, start=1):
        mark = "verified" if preset.verified else "unverified"
        servers = " ".join(preset.servers)
        ctx.printer.raw(f"  {index}  {preset.name:<12} {mark:<12} {servers}")
    restore = len(presets) + 1
    ctx.printer.raw(f"  {restore}  restore the DevForge DNS backup")
    ctx.printer.raw("  0  back")
    choice = _ask(ctx, lines, "DNS")
    if choice is None or choice in {"", "0"} or not choice.isdigit():
        return
    index = int(choice)
    if index == restore:
        cmd_dns_restore(ctx)
        return
    if not 1 <= index <= len(presets):
        ctx.printer.error("Enter a number from the list.")
        return
    cmd_dns_set(ctx, presets[index - 1].name)


def _shell(ctx: Context, lines: Iterator[str]) -> None:
    ctx.printer.info("Shell setup puts the DevForge shims on PATH.")
    ctx.printer.raw("  1  add DevForge to your shell")
    ctx.printer.raw("  2  remove DevForge from your shell")
    ctx.printer.raw("  0  back")
    choice = _ask(ctx, lines, "Shell")
    if choice == "1":
        cmd_shell(ctx, "install")
    elif choice == "2":
        cmd_shell(ctx, "remove")


_ACTION_LABELS = (
    ("i", "This computer"),
    ("d", "Doctor (offline check)"),
    ("u", "Update every installed tool"),
    ("p", "Presets"),
    ("m", "Mirrors"),
    ("n", "DNS"),
    ("s", "Shell setup"),
    ("g", "Update DevForge"),
    ("h", "How to use this menu"),
)

_ACTIONS = {
    "i": _info,
    "d": _doctor,
    "u": _update_all,
    "p": _presets,
    "m": _mirrors,
    "n": _dns,
    "s": _shell,
    "g": _self_update,
    "h": _help,
}


def _ask(ctx: Context, lines: Iterator[str], prompt: str) -> str | None:
    ctx.printer.stream.write(prompt + ": ")
    ctx.printer.stream.flush()
    try:
        return next(lines).strip()
    except StopIteration:
        return None


def _pause(ctx: Context, lines: Iterator[str]) -> None:
    _ask(ctx, lines, "Press Enter to continue")


def _stdin_lines() -> Iterator[str]:
    yield from sys.stdin


def _interactive(stream: IO[str] | None = None) -> bool:
    target = sys.stdout if stream is None else stream
    try:
        return bool(sys.stdin.isatty() and target.isatty())
    except (AttributeError, ValueError):
        return False
