"""Explicit native service controls; all changes use the plan engine."""

from __future__ import annotations

from devforge.commands.common import emit_json, resolve_tool, run_plan
from devforge.context import Context
from devforge.core.plan import Plan, Step

ACTIONS = ("status", "start", "stop", "restart", "reload", "enable", "disable")


def service_plan(ctx: Context, name: str, action: str) -> Plan:
    plan = Plan(title=f"{action} {name}")
    tool = resolve_tool(ctx, name)
    if tool is None:
        plan.blocked = f"Unknown service: {name}"
        return plan
    system = ctx.system()
    services = tool.spec.services.get(system.family) or tool.spec.services.get("default", ())
    if name == "kvm":
        services = ("libvirtd",)
    if not services or action not in ACTIONS:
        plan.blocked = "This tool has no supported service action."
        return plan
    if system.virtualization == "container":
        plan.blocked = (
            "Service management is unavailable inside a container. Manage it on the host."
        )
        return plan
    for service in services:
        argv: tuple[str, ...]
        if system.init == "systemd":
            argv = ("systemctl", "--no-pager", action, service)
        elif system.init == "openrc":
            if action in {"enable", "disable"}:
                argv = ("rc-update", "add" if action == "enable" else "del", service, "default")
            else:
                argv = ("rc-service", service, action)
        else:
            plan.blocked = "Service controls require a running systemd or OpenRC init system."
            return plan
        plan.add(
            Step(
                title=f"{action} {service}",
                kind="command",
                argv=argv,
                sudo=action != "status",
                reason="Managing system services requires root.",
            )
        )
    if name == "kvm":
        plan.notes.append(
            "Uses the monolithic libvirtd service. Hosts with modular libvirt daemons "
            "must manage their virtqemud/virtnetworkd sockets with the distro tools."
        )
    return plan


def cmd_service(ctx: Context, name: str, action: str) -> int:
    plan = service_plan(ctx, name, action)
    if action != "status" or plan.blocked or ctx.dry_run:
        return run_plan(ctx, plan)
    results = [ctx.runner.run(step.argv, timeout=30) for step in plan.steps]
    if ctx.as_json:
        emit_json(
            ctx,
            [
                {"argv": list(r.argv), "code": r.code, "stdout": r.stdout, "stderr": r.stderr}
                for r in results
            ],
        )
    else:
        for result in results:
            ctx.printer.raw(result.stdout.strip())
            if result.stderr:
                ctx.printer.warn(result.stderr.strip())
    return 0 if all(r.code == 0 for r in results) else 1
