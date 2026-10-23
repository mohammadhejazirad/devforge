"""Read-only commands: info, doctor, list, status, and versions."""

from __future__ import annotations

import json

from devforge import __version__
from devforge.commands.common import emit_json, resolve_tool
from devforge.context import Context
from devforge.core.mirrors import MirrorError
from devforge.core.net import DownloadError
from devforge.core.state import StateError
from devforge.core.versioning import is_valid_version, sort_versions
from devforge.tools.base import Check
from devforge.tools.catalog import CatalogError, VersionIndex, parse_refresh, save_index
from devforge.tools.engine import active_mirror
from devforge.tools.managed import ManagedTool, all_tools


def cmd_info(ctx: Context) -> int:
    """Print what DevForge detected about this machine."""
    system = ctx.system()
    mirror = _mirror_name(ctx)
    payload = {
        "devforge": __version__,
        "mirror": mirror,
        "system": system.to_dict(),
    }
    if ctx.as_json:
        emit_json(ctx, payload)
        return 0
    ctx.printer.info(f"devforge {__version__}")
    ctx.printer.raw(f"  os:        {system.pretty_name} ({system.family})")
    ctx.printer.raw(f"  version:   {system.version_id or 'unknown'} {system.codename}".rstrip())
    ctx.printer.raw(f"  arch:      {system.arch}  libc: {system.libc}")
    ctx.printer.raw(f"  init:      {system.init}  virt: {system.virtualization}")
    ctx.printer.raw(f"  form:      {system.form_factor} (hint only)")
    ctx.printer.raw(f"  packages:  {system.package_manager or 'none'}")
    ctx.printer.raw(f"  privilege: {system.privilege}")
    ctx.printer.raw(f"  mirror:    {mirror}")
    for warning in system.warnings:
        ctx.printer.warn(warning)
    if system.privilege == "root":
        ctx.printer.warn("Running as root. Prefer a normal user with sudo when possible.")
    return 0


def cmd_list(ctx: Context) -> int:
    """List every tool DevForge can manage."""
    rows = []
    for tool in all_tools():
        if _hidden(ctx, tool):
            continue
        info = tool.detect(ctx)
        rows.append(
            {
                "name": tool.name,
                "category": tool.spec.category,
                "strategy": tool.spec.strategy,
                "summary": tool.spec.summary,
                "installed_version": info.current,
                "source": info.source,
            }
        )
    if ctx.as_json:
        emit_json(ctx, {"tools": rows})
        return 0
    for row in rows:
        current = row["installed_version"] or "not installed"
        ctx.printer.raw(f"{row['name']:<12} {current:<16} {row['summary']}")
    return 0


def cmd_status(ctx: Context, name: str | None) -> int:
    """Show installed versions and whether an update is known."""
    tools = _selected(ctx, name)
    if tools is None:
        return 2
    rows = [tool.status(ctx).to_dict() for tool in tools]
    if ctx.as_json:
        emit_json(ctx, {"tools": rows})
        return 0
    if not rows:
        ctx.printer.ok("No tools to report.")
        return 0
    for row in rows:
        _print_status(ctx, row)
    return 0


def cmd_versions(ctx: Context, name: str, *, refresh: bool) -> int:
    """List known versions. ``--refresh`` updates the on-disk cache."""
    tool = resolve_tool(ctx, name)
    if tool is None:
        return 2
    index = _index_for(ctx, tool)
    if refresh:
        refreshed = _refresh_index(ctx, tool, index)
        if refreshed is None:
            return 1
        index = refreshed
    versions = list(index.versions)
    payload = {
        "tool": tool.name,
        "installed": list(tool.detect(ctx).versions),
        "current": tool.detect(ctx).current,
        "lts": index.lts or None,
        "latest": index.latest or None,
        "versions": versions,
    }
    if ctx.as_json:
        emit_json(ctx, payload)
        return 0
    ctx.printer.info(f"{tool.name} versions")
    if payload["current"]:
        ctx.printer.raw(f"  installed now: {payload['current']}")
    if index.lts:
        ctx.printer.raw(f"  lts:           {index.lts}")
    if index.latest:
        ctx.printer.raw(f"  latest:        {index.latest}")
    shown = versions[:30]
    for version in shown:
        ctx.printer.raw(f"  {version}")
    if len(versions) > len(shown):
        ctx.printer.raw(f"  ... and {len(versions) - len(shown)} more")
    if not versions and not index.latest:
        ctx.printer.warn("No version index is shipped for this tool.")
    return 0


def cmd_doctor(ctx: Context, *, online: bool) -> int:
    """Check the machine and every tool. Network probes run only with --online."""
    checks: list[Check] = []
    system = ctx.system()
    for warning in system.warnings:
        checks.append(Check("system", "warn", warning))
    if not system.warnings:
        checks.append(
            Check("system", "ok", f"{system.pretty_name} ({system.family}, {system.arch})")
        )
    checks.extend(_manager_notes(ctx))
    for tool in all_tools():
        if _hidden(ctx, tool):
            continue
        checks.extend(tool.doctor(ctx))
    if online and not ctx.offline:
        checks.extend(_probe_upstreams(ctx))
    elif not online:
        checks.append(Check("network", "ok", "skipped (pass --online to probe upstreams)"))
    failed = any(item.status == "error" for item in checks)
    if ctx.as_json:
        emit_json(
            ctx,
            {
                "ok": not failed,
                "system": system.to_dict(),
                "checks": [item.to_dict() for item in checks],
            },
        )
        return 1 if failed else 0
    for item in checks:
        line = f"{item.name}: {item.message}"
        if item.status == "error":
            ctx.printer.error(line)
        elif item.status == "warn":
            ctx.printer.warn(line)
        else:
            ctx.printer.ok(line)
    return 1 if failed else 0


def _print_status(ctx: Context, row: dict[str, object]) -> None:
    current = row["installed_version"] or "not installed"
    latest = row["latest"] or "unknown"
    update = row["update_available"]
    if update is True:
        update_text = "update available"
    elif update is False:
        update_text = "up to date" if row["installed_version"] else "not installed"
    else:
        update_text = "update unknown"
    flags = []
    if row["can_install"]:
        flags.append("install")
    if row["can_update"]:
        flags.append("update")
    if row["can_switch"]:
        flags.append("switch")
    if row["can_uninstall"]:
        flags.append("uninstall")
    ctx.printer.raw(
        f"{row['name']}: {current} ({row['source']}), newest known {latest}, {update_text}"
    )
    ctx.printer.raw("  actions: " + (", ".join(flags) if flags else "none"))
    notes = row["notes"]
    if isinstance(notes, list):
        for note in notes:
            ctx.printer.raw(f"  note: {note}")


def _selected(ctx: Context, name: str | None) -> list[ManagedTool] | None:
    if name is None:
        return [tool for tool in all_tools() if not _hidden(ctx, tool)]
    tool = resolve_tool(ctx, name)
    if tool is None:
        return None
    return [tool]


def _hidden(ctx: Context, tool: ManagedTool) -> bool:
    return bool(tool.spec.desktop_only and ctx.system().form_factor == "server")


def _mirror_name(ctx: Context) -> str:
    try:
        profile = active_mirror(ctx)
    except (MirrorError, StateError) as exc:
        ctx.printer.warn(str(exc))
        return "upstream"
    if profile is None:
        return "upstream"
    return profile.name


def _index_for(ctx: Context, tool: ManagedTool) -> VersionIndex:
    from devforge.tools.engine import _index

    return _index(tool.spec, ctx)


def _refresh_index(ctx: Context, tool: ManagedTool, index: VersionIndex) -> VersionIndex | None:
    if not index.refresh_url or not index.refresh_format:
        ctx.printer.error(f"{tool.name} has no upstream index to refresh.")
        return None
    try:
        payload = ctx.fetcher.get(index.refresh_url, timeout=20)
        versions, lts, latest, checksums = parse_refresh(index.refresh_format, payload)
    except (DownloadError, CatalogError, OSError) as exc:
        ctx.printer.error(f"Could not refresh {tool.name}: {exc}")
        return None
    merged = {version: dict(arches) for version, arches in index.sha256.items()}
    for version, arches in checksums.items():
        slot = dict(merged.get(version, {}))
        slot.update(arches)
        merged[version] = slot
    kept = [item for item in versions if is_valid_version(item)]
    refreshed = VersionIndex(
        tool=tool.name,
        versions=tuple(sort_versions(kept)),
        lts=lts if is_valid_version(lts) else "",
        latest=latest if is_valid_version(latest) else "",
        sha256=merged,
        refresh_format=index.refresh_format,
        refresh_url=index.refresh_url,
    )
    save_index(ctx.paths.cache, refreshed)
    if not ctx.as_json:
        ctx.printer.ok(f"Saved {len(kept)} {tool.name} versions to the cache.")
    return refreshed


def _manager_notes(ctx: Context) -> list[Check]:
    checks: list[Check] = []
    home = ctx.paths.home
    if (home / ".asdf").is_dir():
        checks.append(Check("asdf", "ok", "asdf is present; DevForge will not modify it"))
    mise = home / ".local" / "share" / "mise"
    if mise.is_dir():
        checks.append(Check("mise", "ok", "mise is present; DevForge will not modify it"))
    return checks


def _probe_upstreams(ctx: Context) -> list[Check]:
    path = ctx.data_root / "upstreams.json"
    checks: list[Check] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Check("network", "warn", f"could not read upstream list: {exc}")]
    if not isinstance(payload, list):
        return [Check("network", "warn", "upstream list is not a JSON list")]
    for item in payload:
        url = str(item)
        try:
            ctx.fetcher.get(url, timeout=2)
        except (DownloadError, OSError) as exc:
            checks.append(Check("network", "warn", f"could not reach {url}: {exc}"))
        else:
            checks.append(Check("network", "ok", url))
    return checks
