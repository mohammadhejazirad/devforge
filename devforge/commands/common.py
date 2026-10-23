"""Helpers shared by every command adapter."""

from __future__ import annotations

import json

from devforge.context import Context
from devforge.core.plan import Plan, apply_plan
from devforge.core.versioning import require_version
from devforge.tools.catalog import CatalogError
from devforge.tools.engine import ToolError
from devforge.tools.managed import ManagedTool, load_tool


def emit_json(ctx: Context, payload: object) -> None:
    """Write JSON to stdout. Quiet mode does not suppress this."""
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    ctx.printer.stream.write(text)


def run_plan(ctx: Context, plan: Plan) -> int:
    """Show a plan and apply it unless this invocation is a dry run."""
    ctx.log.info(plan.title or "plan")
    return apply_plan(plan, ctx.apply())


def resolve_tool(ctx: Context, name: str) -> ManagedTool | None:
    """Load one catalog tool, or print an error and return None."""
    try:
        return load_tool(name)
    except (ToolError, CatalogError) as exc:
        ctx.printer.error(str(exc))
        return None


def checked_version(ctx: Context, version: str) -> str | None:
    """Accept a version string, or print why it was refused."""
    try:
        return require_version(version)
    except ValueError as exc:
        ctx.printer.error(str(exc))
        return None
