"""Mirror profiles and DNS presets."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, cast

from devforge import strings as s
from devforge.commands.common import emit_json, run_plan
from devforge.context import Context
from devforge.core.dns import (
    DnsError,
    detect_resolver,
    load_presets,
    require_preset,
    resolv_conf_text,
)
from devforge.core.mirrors import MirrorError, MirrorProfile, load_profiles, require_profile
from devforge.core.net import DownloadError
from devforge.core.plan import Plan, Step
from devforge.core.state import StateError, load_json

_LINK = re.compile(r"Link\s+\d+\s+\(([^)]+)\)")


def cmd_mirror_list(ctx: Context) -> int:
    """Show the mirror profiles shipped with DevForge."""
    profiles = list(load_profiles(ctx.data_root).values())
    active = _active_name(ctx)
    if ctx.as_json:
        emit_json(
            ctx,
            {
                "active": active,
                "profiles": [profile.to_dict() for profile in profiles],
            },
        )
        return 0
    ctx.printer.info(f"Active mirror: {active}")
    for profile in profiles:
        mark = "verified" if profile.verified else "unverified"
        ctx.printer.raw(f"  {profile.name:<12} {mark:<12} {profile.description}")
    ctx.printer.raw("The default is upstream. A profile is used only after `devforge mirror set`.")
    return 0


def cmd_mirror_set(ctx: Context, name: str) -> int:
    """Select a mirror profile. ``upstream`` clears the selection."""
    if name == "upstream":
        return cmd_mirror_reset(ctx)
    try:
        profile = require_profile(ctx.data_root, name)
    except MirrorError as exc:
        ctx.printer.error(str(exc))
        return 2
    if not profile.verified:
        ctx.printer.warn(s.WARN_UNVERIFIED_MIRROR.format(name=profile.name))
    try:
        plan = _mirror_plan(ctx, profile)
    except MirrorError as exc:
        ctx.printer.error(str(exc))
        return 1
    return run_plan(ctx, plan)


def cmd_mirror_reset(ctx: Context) -> int:
    """Clear the selected mirror and restore a DevForge docker daemon backup."""
    plan = Plan(title="Reset mirror profile")
    try:
        payload = _config(ctx)
    except MirrorError as exc:
        ctx.printer.error(str(exc))
        return 1
    payload.pop("mirror", None)
    plan.add(
        Step(
            title="Clear the mirror selection",
            kind="write",
            path=str(ctx.paths.config_file),
            content=_dump(payload),
            policy="owned",
        )
    )
    daemon = ctx.fs_root / "etc" / "docker" / "daemon.json"
    backup = Path(str(daemon) + ".devforge.bak")
    if backup.exists() or backup.is_symlink():
        plan.add(Step(title="Restore Docker daemon.json", kind="restore", path=str(daemon)))
    else:
        plan.notes.append("No DevForge backup of Docker daemon.json was found.")
    plan.notes.append("Open a new shell so shims pick up the cleared mirror.")
    return run_plan(ctx, plan)


def cmd_mirror_test(ctx: Context, name: str | None) -> int:
    """Time a small request through the selected profile. This does not change config."""
    try:
        profile = require_profile(ctx.data_root, name) if name else _active_profile(ctx)
    except MirrorError as exc:
        ctx.printer.error(str(exc))
        return 2
    if ctx.offline:
        ctx.printer.warn("Offline mode: mirror reachability was not tested.")
        return 0
    targets = _probe_urls(profile)
    rows: list[dict[str, object]] = []
    failures = 0
    for url in targets:
        started = time.monotonic()
        try:
            ctx.fetcher.get(url, timeout=5)
        except (DownloadError, OSError) as exc:
            failures += 1
            rows.append({"url": url, "ok": False, "error": str(exc)})
            if not ctx.as_json:
                ctx.printer.warn(f"{url} failed: {exc}")
        else:
            elapsed = round((time.monotonic() - started) * 1000)
            rows.append({"url": url, "ok": True, "milliseconds": elapsed})
            if not ctx.as_json:
                ctx.printer.ok(f"{url} responded in {elapsed} ms")
    if ctx.as_json:
        emit_json(ctx, {"profile": profile.name if profile else "upstream", "results": rows})
    return 1 if failures and failures == len(rows) else 0


def cmd_dns_show(ctx: Context) -> int:
    """Show the resolver DevForge would talk to and the current nameserver lines."""
    resolver = detect_resolver(ctx.fs_root, ctx.runner)
    resolv = ctx.fs_root / "etc" / "resolv.conf"
    servers = _nameservers(resolv)
    payload = {
        "resolver": resolver.kind,
        "detail": resolver.detail,
        "resolv_conf": str(resolv),
        "nameservers": servers,
        "presets": [item.to_dict() for item in load_presets(ctx.data_root / "dns.json").values()],
    }
    if ctx.as_json:
        emit_json(ctx, payload)
        return 0
    ctx.printer.info(f"Resolver: {resolver.kind} ({resolver.detail})")
    if servers:
        for server in servers:
            ctx.printer.raw(f"  nameserver {server}")
    else:
        ctx.printer.raw("  no nameserver lines were read")
    ctx.printer.raw("Presets (opt-in):")
    for preset in load_presets(ctx.data_root / "dns.json").values():
        mark = "verified" if preset.verified else "unverified"
        joined = ", ".join(preset.servers)
        ctx.printer.raw(f"  {preset.name:<12} {mark:<12} {joined}")
    return 0


def cmd_dns_set(ctx: Context, name: str) -> int:
    """Plan a DNS change through the resolver this machine actually uses."""
    try:
        preset = require_preset(ctx.data_root / "dns.json", name)
    except DnsError as exc:
        ctx.printer.error(str(exc))
        return 2
    if not preset.verified:
        ctx.printer.warn(s.WARN_UNVERIFIED_DNS.format(name=preset.name))
    if any(server.startswith("10.") for server in preset.servers):
        ctx.printer.warn(
            "This preset uses a 10.x address. It only works on networks that route to it."
        )
    resolver = detect_resolver(ctx.fs_root, ctx.runner)
    plan = Plan(title=f"Set DNS to {preset.name}")
    resolv = ctx.fs_root / "etc" / "resolv.conf"
    plan.add(Step(title=f"Back up {resolv}", kind="backup", path=str(resolv)))
    if resolver.kind == "systemd-resolved":
        link = _resolved_link(ctx)
        if not link:
            plan.blocked = (
                "systemd-resolved is in use, but no link name was detected. "
                "Set the DNS servers in your network tool, or switch the resolver."
            )
            return run_plan(ctx, plan)
        plan.add(
            Step(
                title=f"Point {link} at {preset.name}",
                kind="command",
                argv=("resolvectl", "dns", link, *preset.servers),
                sudo=True,
                reason="Changing DNS through systemd-resolved needs root.",
            )
        )
    elif resolver.kind == "networkmanager":
        connection = _nm_connection(ctx)
        if not connection:
            plan.blocked = (
                "NetworkManager is installed, but no active connection name was detected. "
                "Connect a network and retry, or edit the connection by hand."
            )
            return run_plan(ctx, plan)
        plan.add(
            Step(
                title=f"Set DNS on {connection}",
                kind="command",
                argv=(
                    "nmcli",
                    "connection",
                    "modify",
                    connection,
                    "ipv4.dns",
                    ",".join(preset.servers),
                    "ipv4.ignore-auto-dns",
                    "yes",
                ),
                sudo=True,
                reason="Changing a NetworkManager connection needs root.",
            )
        )
        plan.add(
            Step(
                title=f"Reconnect {connection}",
                kind="command",
                argv=("nmcli", "connection", "up", connection),
                sudo=True,
                reason="Applying NetworkManager DNS needs root.",
            )
        )
    else:
        plan.add(
            Step(
                title=f"Write nameservers for {preset.name}",
                kind="write",
                path=str(resolv),
                content=resolv_conf_text(preset.servers),
                policy="etc",
            )
        )
        if resolver.kind == "resolvconf":
            plan.notes.append(
                "resolvconf may overwrite this file the next time the network changes."
            )
    plan.notes.append("Restore the previous resolver with: devforge dns restore")
    return run_plan(ctx, plan)


def cmd_dns_restore(ctx: Context) -> int:
    """Put the DevForge backup of resolv.conf back."""
    resolv = ctx.fs_root / "etc" / "resolv.conf"
    backup = Path(str(resolv) + ".devforge.bak")
    plan = Plan(title="Restore DNS")
    if not backup.exists() and not backup.is_symlink():
        plan.blocked = f"No DevForge backup exists for {resolv}."
        return run_plan(ctx, plan)
    plan.add(Step(title=f"Restore {resolv}", kind="restore", path=str(resolv)))
    link = (
        _resolved_link(ctx)
        if detect_resolver(ctx.fs_root, ctx.runner).kind == "systemd-resolved"
        else ""
    )
    if link:
        plan.add(
            Step(
                title=f"Revert systemd-resolved link {link}",
                kind="command",
                argv=("resolvectl", "revert", link),
                sudo=True,
                reason="Reverting systemd-resolved needs root.",
            )
        )
    return run_plan(ctx, plan)


def cmd_dns_test(ctx: Context, lookup: Any | None = None) -> int:
    """Resolve a public name with the system resolver."""
    import socket

    def default_lookup(host: str) -> list[object]:
        return list(socket.getaddrinfo(host, 443))

    probe = lookup if lookup is not None else default_lookup
    try:
        found = probe("example.com")
    except OSError as exc:
        ctx.printer.error(f"DNS lookup of example.com failed: {exc}")
        return 1
    if ctx.as_json:
        emit_json(ctx, {"host": "example.com", "results": len(found)})
        return 0
    ctx.printer.ok(f"example.com resolved ({len(found)} results).")
    return 0


def _mirror_plan(ctx: Context, profile: MirrorProfile) -> Plan:
    plan = Plan(title=f"Use mirror profile {profile.name}")
    payload = _config(ctx)
    payload["mirror"] = profile.name
    plan.add(
        Step(
            title=f"Save mirror profile {profile.name}",
            kind="write",
            path=str(ctx.paths.config_file),
            content=_dump(payload),
            policy="owned",
        )
    )
    mirrors = [
        item.mirror for item in profile.rewrites if item.ecosystem == "docker" and item.mirror
    ]
    if mirrors:
        daemon = ctx.fs_root / "etc" / "docker" / "daemon.json"
        try:
            current = _read_daemon(daemon)
        except StateError as exc:
            plan.blocked = str(exc)
            return plan
        existing = current.get("registry-mirrors", [])
        merged_mirrors = [item for item in existing if isinstance(item, str)]
        for mirror in mirrors:
            if mirror not in merged_mirrors:
                merged_mirrors.append(mirror)
        current["registry-mirrors"] = merged_mirrors
        plan.add(
            Step(
                title="Add Docker registry mirrors",
                kind="write",
                path=str(daemon),
                content=_dump(current),
                policy="etc",
            )
        )
        if ctx.system().virtualization == "container":
            plan.notes.append("Docker service changes are skipped inside a container.")
        elif ctx.runner.which("docker"):
            plan.add(
                Step(
                    title="Restart Docker so the registry mirror is used",
                    kind="command",
                    argv=("systemctl", "restart", "docker"),
                    sudo=True,
                    reason="Restarting Docker needs root.",
                )
            )
    if not profile.verified:
        plan.notes.append(s.WARN_UNVERIFIED_MIRROR.format(name=profile.name))
    plan.notes.append(
        "Checksum verification stays on. Distro package repositories are not rewritten."
    )
    return plan


def _config(ctx: Context) -> dict[str, Any]:
    try:
        return dict(load_json(ctx.paths.config_file))
    except StateError as exc:
        raise MirrorError(str(exc)) from exc


def _active_name(ctx: Context) -> str:
    profile = _active_profile(ctx)
    return "upstream" if profile is None else profile.name


def _active_profile(ctx: Context) -> MirrorProfile | None:
    try:
        payload = load_json(ctx.paths.config_file)
    except StateError as exc:
        raise MirrorError(str(exc)) from exc
    name = payload.get("mirror")
    if not isinstance(name, str) or not name or name == "upstream":
        return None
    return require_profile(ctx.data_root, name)


def _probe_urls(profile: MirrorProfile | None) -> tuple[str, ...]:
    if profile is None:
        return ("https://registry-1.docker.io/v2/",)
    found: list[str] = []
    for item in profile.rewrites:
        if item.mirror:
            found.append(item.mirror + "/")
        elif item.value:
            found.append(item.value)
    return tuple(found) or ("https://registry-1.docker.io/v2/",)


def _read_daemon(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"{path} is not valid JSON, so it was left unchanged: {exc}") from exc
    if not isinstance(payload, dict):
        raise StateError(f"{path} is not a JSON object, so it was left unchanged.")
    return cast(dict[str, Any], payload)


def _nameservers(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    servers: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            servers.append(parts[1])
    return servers


def _resolved_link(ctx: Context) -> str:
    result = ctx.runner.run(["resolvectl", "status"], timeout=5)
    if result.code != 0:
        return ""
    match = _LINK.search(result.stdout)
    return match.group(1).strip() if match else ""


def _nm_connection(ctx: Context) -> str:
    result = ctx.runner.run(
        ["nmcli", "-t", "-f", "NAME,STATE", "connection", "show", "--active"],
        timeout=5,
    )
    if result.code != 0:
        return ""
    for line in result.stdout.splitlines():
        name, separator, state = line.partition(":")
        if separator and state.strip() == "activated" and name.strip():
            return name.strip()
    return ""


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
