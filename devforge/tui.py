"""Numbered terminal menu.

The menu is optional. ``devforge`` with no command prints help and exits.
``devforge tui`` opens the menu when stdin and stdout are terminals.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator

from devforge.commands.files import cmd_preset_apply, cmd_preset_list
from devforge.commands.inspect import cmd_info, cmd_status
from devforge.commands.lifecycle import cmd_install, cmd_uninstall, cmd_update, cmd_use
from devforge.commands.network import cmd_dns_set, cmd_dns_show, cmd_mirror_list, cmd_mirror_set
from devforge.context import Context
from devforge.tools.base import Scope


def cmd_tui(ctx: Context) -> int:
    """Open the menu, or tell the user to pass a command when this is not a terminal."""
    if not _interactive():
        ctx.printer.error("The menu needs a terminal. Pass a command, for example: devforge --help")
        return 2
    return menu(ctx, _stdin_lines())


def menu(ctx: Context, lines: Iterator[str]) -> int:
    """Run the menu from ``lines``. Tests pass a list iterator."""
    actions: tuple[tuple[str, str, Callable[[Context, Iterator[str]], int]], ...] = (
        ("1", "info", _info),
        ("2", "status", _status),
        ("3", "install", _install),
        ("4", "update", _update),
        ("5", "switch default", _switch),
        ("6", "uninstall", _uninstall),
        ("7", "mirrors", _mirrors),
        ("8", "DNS", _dns),
        ("9", "preset", _preset),
    )
    while True:
        ctx.printer.raw("")
        ctx.printer.info("DevForge")
        for key, label, _action in actions:
            ctx.printer.raw(f"  {key}  {label}")
        ctx.printer.raw("  0  exit")
        choice = _ask(ctx, lines, "Choice")
        if choice is None or choice == "0":
            return 0
        action = next((item for item in actions if item[0] == choice), None)
        if action is None:
            ctx.printer.error(f"Unknown choice {choice!r}. Enter a number from the menu.")
            continue
        action[2](ctx, lines)


def _info(ctx: Context, lines: Iterator[str]) -> int:
    del lines
    return cmd_info(ctx)


def _status(ctx: Context, lines: Iterator[str]) -> int:
    name = _ask(ctx, lines, "Tool name (empty for all)")
    if name is None:
        return 0
    return cmd_status(ctx, name or None)


def _install(ctx: Context, lines: Iterator[str]) -> int:
    name = _ask(ctx, lines, "Tool name")
    if not name:
        return 0
    version = _ask(ctx, lines, "Version (empty for the default)")
    if version is None:
        return 0
    return cmd_install(ctx, name, version or None, make_default=True, use_package=False)


def _update(ctx: Context, lines: Iterator[str]) -> int:
    name = _ask(ctx, lines, "Tool name (empty updates every installed tool)")
    if name is None:
        return 0
    if name:
        return cmd_update(ctx, name, all_tools_flag=False)
    return cmd_update(ctx, None, all_tools_flag=True)


def _switch(ctx: Context, lines: Iterator[str]) -> int:
    name = _ask(ctx, lines, "Tool name")
    version = _ask(ctx, lines, "Version")
    scope_text = _ask(ctx, lines, "Scope: global, project, or shell")
    if not name or not version or scope_text is None:
        return 0
    scopes = {"global": Scope.GLOBAL, "project": Scope.PROJECT, "shell": Scope.SHELL}
    scope = scopes.get(scope_text)
    if scope is None:
        ctx.printer.error("Scope must be global, project, or shell.")
        return 2
    return cmd_use(ctx, name, version, scope=scope)


def _uninstall(ctx: Context, lines: Iterator[str]) -> int:
    name = _ask(ctx, lines, "Tool name")
    if not name:
        return 0
    version = _ask(ctx, lines, "Version (empty removes the default)")
    if version is None:
        return 0
    return cmd_uninstall(ctx, name, version or None, purge=False)


def _mirrors(ctx: Context, lines: Iterator[str]) -> int:
    cmd_mirror_list(ctx)
    name = _ask(ctx, lines, "Profile name to activate (empty keeps the current one)")
    if not name:
        return 0
    return cmd_mirror_set(ctx, name)


def _dns(ctx: Context, lines: Iterator[str]) -> int:
    cmd_dns_show(ctx)
    name = _ask(ctx, lines, "Preset name to apply (empty cancels)")
    if not name:
        return 0
    return cmd_dns_set(ctx, name)


def _preset(ctx: Context, lines: Iterator[str]) -> int:
    cmd_preset_list(ctx)
    name = _ask(ctx, lines, "Preset name to apply (empty cancels)")
    if not name:
        return 0
    return cmd_preset_apply(ctx, name)


def _ask(ctx: Context, lines: Iterator[str], prompt: str) -> str | None:
    ctx.printer.stream.write(prompt + ": ")
    ctx.printer.stream.flush()
    try:
        return next(lines).strip()
    except StopIteration:
        return None


def _stdin_lines() -> Iterator[str]:
    yield from sys.stdin


def _interactive() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False
