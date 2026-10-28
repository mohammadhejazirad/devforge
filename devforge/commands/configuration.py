"""Nginx configuration inspection and validated replacement with rollback."""

from __future__ import annotations

import tempfile
from pathlib import Path

from devforge.commands.common import run_plan
from devforge.context import Context
from devforge.core.plan import ApplyContext, Plan, Step, _run_command, _write_step


def cmd_config(ctx: Context, tool: str, action: str, source: Path | None = None) -> int:
    """Offer a bounded configuration workflow rather than a privileged editor."""
    if tool != "nginx":
        ctx.printer.error("Validated configuration editing currently supports nginx only.")
        return 2
    path = ctx.fs_root / "etc" / "nginx" / "nginx.conf"
    binary = ctx.runner.which("nginx")
    if not binary:
        ctx.printer.error("Nginx was not found. Install it before managing its configuration.")
        return 1
    if action == "show":
        try:
            ctx.printer.raw(path.read_text(encoding="utf-8"))
        except OSError as exc:
            ctx.printer.error(f"Cannot read {path}: {exc}")
            return 1
        return 0
    plan = Plan(title=f"{action} nginx configuration")
    if action == "check":
        plan.add(
            Step(
                title="Validate Nginx configuration",
                kind="command",
                argv=(binary, "-t"),
                sudo=True,
                reason="Nginx checks may read root-owned certificates and logs.",
            )
        )
    elif action == "apply" and source:
        try:
            content = source.read_text(encoding="utf-8")
            if not content.strip() or not path.is_file() or path.is_symlink():
                raise ValueError(
                    "The new configuration must be nonempty and the existing nginx.conf "
                    "must be a regular file. Symlink configurations need manual management."
                )
        except (OSError, ValueError) as exc:
            ctx.printer.error(str(exc))
            return 1
        plan.add(
            Step(
                title=f"Validate and replace {path} from {source}",
                kind="nginx-config",
                argv=(binary, "-t"),
                path=str(path),
                content=content,
                policy="etc",
                sudo=True,
                reason="Changing Nginx configuration requires root.",
            )
        )
        plan.notes.append(
            "Validates the candidate before replacing nginx.conf, checks it again at "
            "the installed path, and restores the preceding contents on failure. "
            "The running service is not reloaded; use the service menu after review."
        )
    else:
        plan.blocked = "Choose show, check, or apply with an edited configuration file path."
    return run_plan(ctx, plan)


def apply_nginx_config(step: Step, ctx: ApplyContext) -> None:
    path = Path(step.path)
    if path != ctx.fs_root / "etc" / "nginx" / "nginx.conf" or path.is_symlink():
        raise ValueError("refusing an unexpected Nginx configuration path")
    original = path.read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".conf") as candidate:
        candidate.write(step.content)
        candidate.flush()
        _run_command(
            Step(
                title="Validate candidate Nginx configuration",
                kind="command",
                argv=(*step.argv, "-c", candidate.name),
                sudo=True,
                reason=step.reason,
            ),
            ctx,
        )
        write = Step(
            title=step.title, kind="write", path=str(path), content=step.content, policy="etc"
        )
        try:
            _write_step(write, ctx)
            _run_command(
                Step(
                    title="Validate installed Nginx configuration",
                    kind="command",
                    argv=step.argv,
                    sudo=True,
                    reason=step.reason,
                ),
                ctx,
            )
        except (OSError, ValueError):
            write.content = original
            _write_step(write, ctx)
            raise
