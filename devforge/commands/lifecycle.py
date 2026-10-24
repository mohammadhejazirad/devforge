"""Install, update, switch, pin, and uninstall."""

from __future__ import annotations

from devforge.commands.common import checked_version, resolve_tool, run_plan
from devforge.context import Context
from devforge.core.plan import Plan
from devforge.tools.base import Scope
from devforge.tools.engine import ToolError, merge_plans, update_tool
from devforge.tools.managed import all_tools


def cmd_install(
    ctx: Context,
    name: str,
    version: str | None,
    *,
    make_default: bool,
    use_package: bool,
) -> int:
    """Plan an install of one tool."""
    tool = resolve_tool(ctx, name)
    if tool is None:
        return 2
    if version is not None:
        checked = checked_version(ctx, version)
        if checked is None:
            return 2
        version = checked
    try:
        plan = tool.install(ctx, version, make_default=make_default, use_package=use_package)
    except (ToolError, ValueError) as exc:
        ctx.printer.error(str(exc))
        return 1
    return run_plan(ctx, plan)


def cmd_update(ctx: Context, name: str | None, *, all_tools_flag: bool) -> int:
    """Update one tool, or every tool that is already installed."""
    if name is None and not all_tools_flag:
        ctx.printer.error("Name a tool, or pass --all to update every installed tool.")
        return 2
    if name is not None and all_tools_flag:
        ctx.printer.error("Pass a tool name or --all, not both.")
        return 2
    if name is not None:
        tool = resolve_tool(ctx, name)
        if tool is None:
            return 2
        try:
            plan = tool.update(ctx)
        except (ToolError, ValueError) as exc:
            ctx.printer.error(str(exc))
            return 1
        return run_plan(ctx, plan)
    plans: list[Plan] = []
    skipped: list[str] = []
    for tool in all_tools():
        info = tool.detect(ctx)
        if info.current is None and not info.versions:
            continue
        try:
            plan = update_tool(tool.spec, ctx)
        except (ToolError, ValueError) as exc:
            skipped.append(f"{tool.name}: {exc}")
            continue
        if plan.blocked:
            skipped.append(f"{tool.name}: {plan.blocked}")
            continue
        plans.append(plan)
    if not plans:
        if skipped:
            return run_plan(ctx, Plan(title="Update installed tools", blocked="; ".join(skipped)))
        ctx.printer.ok("No installed tools to update.")
        return 0
    merged = merge_plans("Update installed tools", plans)
    merged.notes.extend(skipped)
    result = run_plan(ctx, merged)
    return result if result else int(bool(skipped))


def cmd_use(ctx: Context, name: str, version: str, *, scope: Scope) -> int:
    """Select the default, a project pin, or a shell-only version."""
    tool = resolve_tool(ctx, name)
    if tool is None:
        return 2
    checked = checked_version(ctx, version)
    if checked is None:
        return 2
    try:
        plan = tool.use(ctx, checked, scope=scope)
    except (ToolError, ValueError) as exc:
        ctx.printer.error(str(exc))
        return 1
    return run_plan(ctx, plan)


def cmd_uninstall(ctx: Context, name: str, version: str | None, *, purge: bool) -> int:
    """Remove a managed version, or the distro packages when that is the install."""
    tool = resolve_tool(ctx, name)
    if tool is None:
        return 2
    if version is not None:
        checked = checked_version(ctx, version)
        if checked is None:
            return 2
        version = checked
    try:
        plan = tool.uninstall(ctx, version, purge=purge)
    except (ToolError, ValueError) as exc:
        ctx.printer.error(str(exc))
        return 1
    return run_plan(ctx, plan)
