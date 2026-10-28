"""Install, update, switch, and remove every catalog tool.

Operations return a plan. They do not change the machine. The plan engine is
what applies them, and only after confirmation or ``--yes``.
"""

from __future__ import annotations

import re
from pathlib import Path

from devforge.context import Context
from devforge.core.mirrors import MirrorProfile, env_assignments, require_profile, rewrite_urls
from devforge.core.pkgmgr import (
    PackageManagerError,
    comparable,
    install,
    installed_packages,
    lookup_versions,
    refresh,
    remove,
    upgrade,
)
from devforge.core.plan import PIN_NAMES, Plan, Step
from devforge.core.shell import rc_targets, render_block, render_env, render_shim, upsert_block
from devforge.core.state import load_json
from devforge.core.versioning import (
    Version,
    is_valid_version,
    newest_in_line,
    release_line,
    require_version,
)
from devforge.tools.base import Check, InstalledInfo, Scope, ToolStatus
from devforge.tools.catalog import (
    ToolSpec,
    VersionIndex,
    load_catalog,
    load_index,
    refresh_index,
    save_index,
)

_SERVICE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")


class ToolError(ValueError):
    """The request cannot be turned into a safe plan."""


def detect(spec: ToolSpec, ctx: Context) -> InstalledInfo:
    """Find managed copies and the first binary on PATH."""
    managed = _managed_versions(spec, ctx)
    current: str | None = None
    source = "missing"
    found_path: str | None = None
    notes = _coexist_notes(spec, ctx)
    pattern = re.compile(spec.version_regex)
    for binary in spec.binaries:
        located = ctx.runner.which(binary)
        if not located:
            continue
        found_path = located
        source = "devforge" if _is_ours(located, ctx) else "system"
        if spec.version_args:
            result = ctx.runner.run((located, *spec.version_args), timeout=15)
            match = pattern.search(result.stdout + "\n" + result.stderr)
            if match:
                token = match.group(1)
                current = token if is_valid_version(token) else None
            elif result.code != 0:
                notes.append(f"{binary} was found but did not report a version.")
        break
    if spec.strategy == "external" and notes:
        source = "external"
    return InstalledInfo(
        name=spec.name,
        versions=tuple(managed),
        current=current,
        source=source,
        path=found_path,
        notes=tuple(notes),
    )


def status_of(spec: ToolSpec, ctx: Context) -> ToolStatus:
    """Describe what is installed and whether a newer build is known."""
    info = detect(spec, ctx)
    index = _index(spec, ctx)
    latest = _known_newest(index) or None
    kind = "none"
    available: bool | None = False
    target: str | None = None
    if spec.strategy == "external":
        available = False
        kind = "none"
    elif spec.strategy == "package":
        available, kind = _package_update(spec, ctx, info)
        packages = _choose_packages(spec, ctx.system().family, info.current, fallback=False)
        if info.current and packages:
            _, target = lookup_versions(ctx.system().package_manager, packages[0], ctx.runner)
            parsed = comparable(target)
            if (
                spec.category == "runtime"
                and parsed
                and (release_line(spec.name, parsed) != release_line(spec.name, info.current))
            ):
                target = None
                available = None
    elif info.current and latest and is_valid_version(info.current):
        target = newest_in_line(spec.name, info.current, (index.latest, *index.versions))
        available = Version(target) > Version(info.current) if target else None
        kind = spec.strategy if available else "none"
    elif info.current is None and latest:
        available = False
        kind = spec.strategy
    can_install = spec.strategy != "external"
    can_switch = spec.strategy in {"archive", "package", "rustup"} and bool(
        spec.shims or spec.alternatives or spec.project_files or spec.strategy == "rustup"
    )
    can_update = spec.strategy != "external" and (info.current is not None or bool(info.versions))
    can_uninstall = spec.strategy not in {"external", "npm"}
    return ToolStatus(
        name=spec.name,
        summary=spec.summary,
        category=spec.category,
        installed_version=info.current,
        installed_versions=info.versions,
        source=info.source,
        latest=latest,
        update_available=available,
        update_kind=kind,
        path=info.path,
        notes=info.notes,
        can_install=can_install,
        can_update=can_update,
        can_switch=can_switch,
        can_uninstall=can_uninstall,
        update_target=target or None,
        new_release_available=bool(
            latest
            and info.current
            and Version(release_line(spec.name, latest))
            > Version(release_line(spec.name, info.current))
        ),
    )


def install_tool(
    spec: ToolSpec,
    ctx: Context,
    version: str | None,
    *,
    make_default: bool,
    use_package: bool,
) -> Plan:
    """Plan an install. Passing a version keeps every other version in place."""
    if version:
        require_version(version)
    if spec.desktop_only and ctx.system().form_factor == "server":
        return Plan(
            title=spec.name,
            blocked="This GUI requires a desktop. Install KVM on the server "
            "and connect from virt-manager on a desktop over SSH.",
        )
    if spec.name == "kvm" and ctx.system().virtualization == "container":
        return Plan(
            title=spec.name, blocked="KVM host management is unavailable inside a container."
        )
    if spec.strategy == "external":
        return Plan(title=spec.name, blocked=spec.notes)
    if spec.strategy == "npm":
        return _install_npm(spec, ctx, version)
    if spec.strategy == "rustup":
        return _install_rustup(spec, ctx, version, make_default=make_default)
    if spec.strategy == "package" or use_package:
        return _install_package(spec, ctx, version, make_default=make_default, fallback=use_package)
    plan = _install_archive(spec, ctx, version, make_default=make_default)
    dependency = {"composer": "php", "yarn": "node"}.get(spec.name)
    if dependency and not plan.blocked:
        runtime = load_catalog(ctx.data_root)[dependency]
        info = detect(runtime, ctx)
        if info.current is None:
            prerequisite = install_tool(runtime, ctx, None, make_default=True, use_package=False)
            return merge_plans(plan.title, [prerequisite, plan])
    return plan


def update_tool(spec: ToolSpec, ctx: Context) -> Plan:
    """Plan an upgrade, or an install when the tool is missing."""
    if spec.strategy == "external":
        return Plan(title=spec.name, blocked=spec.notes)
    info = detect(spec, ctx)
    if spec.strategy == "npm":
        return _update_npm(spec, ctx, info)
    if info.current is None and not info.versions:
        return install_tool(spec, ctx, None, make_default=True, use_package=False)
    if spec.strategy == "package":
        return _upgrade_package(spec, ctx, info)
    current = info.current or _default_version(spec, ctx)
    if not current:
        return Plan(title=spec.name, blocked="Select an installed version before updating.")
    if spec.strategy == "rustup":
        located = ctx.runner.which("rustup")
        if not located:
            return Plan(
                title="rust", blocked="Rust is present without rustup; its owner must update it."
            )
        env = _rust_env(ctx) if _is_ours(located, ctx) else ()
        process_env = dict(ctx.env)
        process_env.update(dict(env))
        result = ctx.runner.run((located, "show", "active-toolchain"), env=process_env, timeout=20)
        if result.code != 0 or not result.stdout.startswith("stable-"):
            return Plan(
                title="rust",
                blocked=(
                    "The active Rust toolchain is pinned or not stable. "
                    "Select a version explicitly."
                ),
            )
        return Plan(
            title="Update the stable Rust channel",
            steps=[
                Step(
                    title="Update Rust stable",
                    kind="command",
                    argv=(located, "update", "stable"),
                    env=env,
                )
            ],
        )
    try:
        index = _release_index(spec, ctx)
    except (ValueError, OSError, RuntimeError) as exc:
        return Plan(title=spec.name, blocked=f"Could not refresh {spec.name}: {exc}")
    latest = newest_in_line(spec.name, current, (index.latest, *index.versions))
    if not latest:
        return Plan(
            title=spec.name,
            blocked=(
                f"No stable release is known for {spec.name} {release_line(spec.name, current)}. "
                "Use install to explicitly select another release line."
            ),
        )
    if Version(latest) <= Version(current):
        return Plan(title=spec.name, empty_message=f"{spec.name} {current} is already up to date.")
    return install_tool(spec, ctx, latest, make_default=True, use_package=False)


def use_tool(spec: ToolSpec, ctx: Context, version: str, scope: Scope) -> Plan:
    """Select a version globally, for this project, or for the current shell."""
    if spec.strategy == "external":
        return Plan(title=spec.name, blocked=spec.notes)
    require_version(version)
    if spec.strategy == "archive" and scope is Scope.GLOBAL:
        installed = _managed_versions(spec, ctx)
        matches = [item for item in installed if _matches(item, version.lstrip("v"))]
        if not matches:
            return Plan(
                title=spec.name,
                blocked=(
                    f"{spec.name} {version} is not installed. "
                    f"Run install {spec.name} {version} first."
                ),
            )
        version = max(matches, key=Version)
    if scope is Scope.SHELL:
        env_name = re.sub(r"[^A-Z0-9]", "_", spec.name.upper())
        plan = Plan(title=f"Select {spec.name} {version} for this shell")
        plan.notes.append(f"Run this in your shell: export DEVFORGE_{env_name}_VERSION={version}")
        plan.empty_message = plan.notes[-1]
        return plan
    if scope is Scope.PROJECT:
        return _pin_project(spec, ctx, version)
    if spec.strategy == "rustup":
        return _install_rustup(spec, ctx, version, make_default=True)
    plan = Plan(title=f"Make {spec.name} {version} the default")
    _add_default(plan, spec, ctx, version)
    _add_shims(plan, spec, ctx)
    plan.steps.extend(shell_steps(ctx))
    _add_alternatives(plan, spec, ctx, version)
    if not plan.steps:
        plan.notes.append(
            "This distro package does not support side-by-side defaults. "
            "The system binary stays the default."
        )
        plan.empty_message = plan.notes[-1]
    else:
        plan.notes.append("Open a new shell so the DevForge shims are on PATH.")
    return plan


def uninstall_tool(spec: ToolSpec, ctx: Context, version: str | None, *, purge: bool) -> Plan:
    """Remove a managed version, or the distro packages when that is all there is."""
    if spec.strategy == "external":
        return Plan(title=spec.name, blocked=spec.notes)
    if spec.strategy == "npm":
        return Plan(title=spec.name, blocked=spec.notes)
    if version:
        require_version(version)
    managed = _managed_versions(spec, ctx)
    target = version or (
        _default_version(spec, ctx) if _default_version(spec, ctx) in managed else ""
    )
    if not target and managed:
        target = managed[0]
    if target and target in managed:
        plan = Plan(title=f"Remove {spec.name} {target}")
        version_dir = ctx.paths.install_root / spec.name / target
        if not ctx.paths.contains(version_dir):
            return Plan(title=spec.name, blocked=f"Refusing to delete {version_dir}.")
        plan.add(Step(title=f"Delete {version_dir}", kind="delete", path=str(version_dir)))
        remaining = [item for item in managed if item != target]
        if _default_version(spec, ctx) == target:
            if remaining:
                _add_default(plan, spec, ctx, remaining[0])
            else:
                default_file = ctx.paths.install_root / spec.name / "default"
                plan.add(
                    Step(
                        title=f"Clear the {spec.name} default",
                        kind="delete",
                        path=str(default_file),
                    )
                )
        plan.notes.append("Distro packages, nvm, and pyenv were not touched.")
        return plan
    if spec.strategy == "rustup" and ctx.runner.which("rustup"):
        toolchain = version or "stable"
        argv = ("rustup", "toolchain", "uninstall", toolchain)
        return Plan(
            title=f"Uninstall Rust toolchain {toolchain}",
            steps=[Step(title=f"Uninstall toolchain {toolchain}", kind="command", argv=argv)],
        )
    return _remove_packages(spec, ctx, version, purge=purge)


def doctor_tool(spec: ToolSpec, ctx: Context) -> list[Check]:
    """Report whether this tool looks usable. Missing tools are warnings."""
    info = detect(spec, ctx)
    checks: list[Check] = []
    if info.current:
        checks.append(Check(spec.name, "ok", f"{info.current} ({info.source})"))
    elif info.source == "external":
        checks.append(Check(spec.name, "ok", "detected; DevForge will not change it"))
    elif info.path:
        checks.append(
            Check(spec.name, "warn", f"found at {info.path}, but the version was not recognized")
        )
    else:
        checks.append(Check(spec.name, "warn", "not installed"))
    if spec.name == "kvm":
        device = ctx.fs_root / "dev" / "kvm"
        if not device.exists():
            checks.append(
                Check(
                    "kvm",
                    "warn",
                    "No /dev/kvm device. Check CPU virtualization, "
                    "BIOS/UEFI settings, kernel modules and nested-virtualization support.",
                )
            )
        else:
            import os

            if not os.access(device, os.R_OK | os.W_OK):
                checks.append(
                    Check(
                        "kvm",
                        "warn",
                        "The current user cannot access /dev/kvm. "
                        "Review the distro's kvm/libvirt permission policy.",
                    )
                )
    default = _default_version(spec, ctx)
    if default:
        version_dir = ctx.paths.install_root / spec.name / default
        marker = version_dir / ".devforge-complete"
        if spec.strategy == "archive" and not marker.is_file() and default not in info.versions:
            checks.append(
                Check(spec.name, "error", f"default {default} is selected but not installed")
            )
    for note in info.notes:
        checks.append(Check(spec.name, "ok", note))
    for argv in spec.extra_checks:
        result = ctx.runner.run(argv, timeout=15)
        if result.code == 0:
            checks.append(Check(spec.name, "ok", " ".join(argv)))
        else:
            checks.append(Check(spec.name, "warn", f"{' '.join(argv)} failed"))
    return checks


def shell_steps(ctx: Context) -> list[Step]:
    """Rc updates for the current shell and any rc file that already exists."""
    shell_name = Path(str(ctx.env.get("SHELL", "bash"))).name
    steps: list[Step] = []
    for kind, path in rc_targets(ctx.paths.home, shell_name):
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        block = render_block(kind, ctx.paths.shims)
        updated = upsert_block(existing, block)
        if updated == existing:
            continue
        steps.append(
            Step(
                title=f"Add DevForge shims to {path.name}",
                kind="write",
                path=str(path),
                content=updated,
                policy="rc",
            )
        )
    return steps


def shell_remove_steps(ctx: Context) -> list[Step]:
    from devforge.core.shell import remove_block

    shell_name = Path(str(ctx.env.get("SHELL", "bash"))).name
    steps: list[Step] = []
    for _kind, path in rc_targets(ctx.paths.home, shell_name):
        if not path.is_file():
            continue
        existing = path.read_text(encoding="utf-8")
        updated = remove_block(existing)
        if updated == existing:
            continue
        steps.append(
            Step(
                title=f"Remove DevForge shims from {path.name}",
                kind="write",
                path=str(path),
                content=updated,
                policy="rc",
            )
        )
    return steps


def active_mirror(ctx: Context) -> MirrorProfile | None:
    payload = load_json(ctx.paths.config_file)
    name = payload.get("mirror")
    if not isinstance(name, str) or not name or name == "upstream":
        return None
    return require_profile(ctx.data_root, name)


def merge_plans(title: str, plans: list[Plan]) -> Plan:
    """Combine plans, keeping a single shell-rc edit."""
    blocked = [plan.blocked for plan in plans if plan.blocked]
    if blocked:
        return Plan(title=title, blocked=" ".join(blocked))
    merged = Plan(title=title)
    seen_rc: set[str] = set()
    for plan in plans:
        merged.notes.extend(plan.notes)
        for step in plan.steps:
            if step.kind == "write" and step.policy == "rc":
                if step.path in seen_rc:
                    continue
                seen_rc.add(step.path)
            merged.add(step)
    if not merged.steps:
        merged.empty_message = "Nothing to do; the requested tools are already installed."
    return merged


def _install_package(
    spec: ToolSpec,
    ctx: Context,
    version: str | None,
    *,
    make_default: bool,
    fallback: bool,
) -> Plan:
    system = ctx.system()
    if not system.package_manager:
        return Plan(
            title=spec.name,
            blocked=(
                f"No supported package manager is available, so {spec.name} "
                "cannot be installed from distro packages."
            ),
        )
    packages = _choose_packages(spec, system.family, version, fallback=fallback)
    if not packages:
        detail = spec.notes or f"{spec.name} has no distro package for the {system.family} family."
        return Plan(title=spec.name, blocked=detail)
    info = detect(spec, ctx)
    if (
        version
        and system.family not in spec.versioned_packages
        and not (info.current and _matches(info.current, version))
    ):
        return Plan(
            title=spec.name,
            blocked=(
                f"This distro cannot select {spec.name} {version} with its package names. "
                "The requested version will not be substituted with the distro default."
            ),
        )
    satisfied = _satisfied(spec, info, version, system.family)
    if satisfied and spec.name == "kvm":
        try:
            satisfied = len(
                installed_packages(system.package_manager, packages, ctx.runner)
            ) == len(packages)
        except PackageManagerError as exc:
            return Plan(title=spec.name, blocked=str(exc))
    if satisfied:
        plan = Plan(
            title=spec.name, empty_message=f"{spec.name} is already installed ({info.current})."
        )
        plan.notes.extend(info.notes)
        return plan
    plan = Plan(title=f"Install {spec.name}" + (f" {version}" if version else ""))
    try:
        refresh_argv = tuple(refresh(system.package_manager))
        install_argv = tuple(install(system.package_manager, packages))
    except PackageManagerError as exc:
        return Plan(title=spec.name, blocked=str(exc))
    reason = f"Installing {spec.name} uses the system package manager."
    plan.add(
        Step(
            title="Check package database"
            if system.package_manager == "pacman"
            else "Refresh package indexes",
            kind="command",
            argv=refresh_argv,
            sudo=True,
            reason=reason,
        )
    )
    plan.add(
        Step(
            title="Install " + " ".join(packages),
            kind="command",
            argv=install_argv,
            sudo=True,
            reason=reason,
        )
    )
    if version and make_default:
        _add_default(plan, spec, ctx, version)
        _add_shims(plan, spec, ctx)
        _add_alternatives(plan, spec, ctx, version)
    elif make_default and spec.shims:
        _add_shims(plan, spec, ctx)
    if system.package_manager == "pacman":
        plan.notes.append(
            "DevForge never runs pacman -Sy (unsafe partial upgrades). "
            "Run sudo pacman -Syu before managing packages on Arch."
        )
    plan.steps.extend(shell_steps(ctx))
    _add_group_and_services(plan, spec, ctx)
    if spec.notes:
        plan.notes.append(spec.notes)
    plan.notes.extend(info.notes)
    if system.family not in spec.versioned_packages and version:
        plan.notes.append(
            "This distro ships one package for this tool. The requested version may differ."
        )
    return plan


def _install_archive(
    spec: ToolSpec, ctx: Context, version: str | None, *, make_default: bool
) -> Plan:
    archive = spec.archive
    if archive is None:
        return _install_package(spec, ctx, version, make_default=make_default, fallback=True)
    system = ctx.system()
    index = _index(spec, ctx)
    if version is None or re.fullmatch(r"v?\d+(?:\.\d+)?", version):
        try:
            index = _release_index(spec, ctx)
        except (ValueError, OSError, RuntimeError) as exc:
            return Plan(title=spec.name, blocked=f"Could not refresh {spec.name}: {exc}")
    chosen = version or index.preferred()
    if version and re.fullmatch(r"v?\d+(?:\.\d+)?", version):
        matches = [item for item in index.versions if _matches(item, version.lstrip("v"))]
        if not matches:
            return Plan(
                title=spec.name, blocked=f"No published {spec.name} version matches {version}."
            )
        chosen = max(matches, key=Version)
    if not chosen:
        return Plan(title=spec.name, blocked=f"No version is published for {spec.name}.")
    require_version(chosen)
    try:
        token = _arch_token(spec, system.arch, system.libc)
    except ToolError as exc:
        if spec.fallback_packages:
            plan = _install_package(spec, ctx, None, make_default=make_default, fallback=True)
            plan.notes.insert(0, str(exc) + " Falling back to the distro package.")
            return plan
        return Plan(title=spec.name, blocked=str(exc))
    if chosen in _managed_versions(spec, ctx):
        plan = Plan(title=spec.name, empty_message=f"{spec.name} {chosen} is already installed.")
        if make_default:
            _add_default(plan, spec, ctx, chosen)
            _add_shims(plan, spec, ctx)
            plan.steps.extend(shell_steps(ctx))
            if not plan.steps:
                return Plan(
                    title=spec.name, empty_message=f"{spec.name} {chosen} is already installed."
                )
        return plan
    url = archive.url.format(version=chosen, arch=token)
    filename = archive.filename or url.rstrip("/").split("/")[-1]
    mirror = active_mirror(ctx)
    urls = rewrite_urls(url, mirror)
    sha_key = (
        "any"
        if "{arch}" not in archive.url and not archive.arch_map
        else _sha_key(system.arch, system.libc)
    )
    digest = index.checksum(chosen, sha_key)
    checksum_url = ""
    if not digest and archive.checksum_url:
        checksum_url = archive.checksum_url.format(version=chosen, arch=token)
    if not digest and not checksum_url:
        return Plan(
            title=spec.name,
            blocked=(
                f"No SHA256 checksum is published for {spec.name} {chosen} ({sha_key}). "
                "Refresh the version index or pick a pinned version."
            ),
        )
    version_dir = ctx.paths.install_root / spec.name / chosen
    cache = ctx.paths.cache / "archives" / spec.name / filename
    plan = Plan(title=f"Install {spec.name} {chosen}")
    plan.add(
        Step(
            title=f"Download {filename}",
            kind="download",
            urls=urls,
            dest=str(cache),
            sha256=digest,
            checksum_url=checksum_url,
            checksum_name=filename,
            fmt="file" if archive.fmt == "file" else "",
        )
    )
    if archive.fmt == "file":
        target_name = archive.filename or filename
        plan.add(
            Step(
                title=f"Install {target_name} into {version_dir}",
                kind="write",
                path=str(version_dir / target_name),
                content="",
                policy="owned",
            )
        )
        # The bytes come from the download. A write step cannot carry binary
        # content, so the apply path copies the verified file instead.
        plan.steps[-1] = Step(
            title=f"Install {target_name}",
            kind="extract",
            archive=str(cache),
            dest=str(version_dir / target_name),
            fmt="file",
        )
    else:
        plan.add(
            Step(
                title=f"Extract into {version_dir.name}",
                kind="extract",
                archive=str(cache),
                dest=str(version_dir),
                fmt=archive.fmt,
            )
        )
    plan.add(
        Step(
            title="Verify the installed executable layout",
            kind="verify-install",
            path=str(version_dir),
            packages=(archive.filename if spec.shim_kind == "phar" else spec.binaries[0],),
        )
    )
    plan.add(
        Step(
            title="Record a completed install",
            kind="write",
            path=str(version_dir / ".devforge-complete"),
            content=f"{spec.name} {chosen}\n",
            policy="owned",
        )
    )
    if make_default:
        _add_default(plan, spec, ctx, chosen)
    _add_shims(plan, spec, ctx)
    _add_env(plan, ctx)
    plan.steps.extend(shell_steps(ctx))
    plan.notes.extend(detect(spec, ctx).notes)
    if (
        system.libc == "musl"
        and spec.archive is not None
        and "musl" not in spec.archive.libc_arch_map
    ):
        plan.notes.append("This build is the glibc archive. It may not run on musl.")
    plan.notes.append("Open a new shell so the DevForge shims are on PATH.")
    return plan


def _install_npm(spec: ToolSpec, ctx: Context, version: str | None) -> Plan:
    if not ctx.runner.which("npm"):
        if ctx.runner.which("node"):
            return Plan(title="npm", blocked="Node is present without npm. Reinstall Node first.")
        node = load_catalog(ctx.data_root)["node"]
        plan = install_tool(node, ctx, None, make_default=True, use_package=False)
        if version and not plan.blocked:
            plan.add(_npm_step(ctx, version))
        return plan
    if version:
        return Plan(title=f"Install npm {version}", steps=[_npm_step(ctx, version)])
    info = detect(spec, ctx)
    return Plan(
        title="npm", empty_message=f"npm is already installed ({info.current or 'unknown'})."
    )


def _npm_step(ctx: Context, selector: str) -> Step:
    return Step(
        title=f"Install npm {selector}",
        kind="command",
        argv=("npm", "install", "-g", f"npm@{selector}"),
        env=(("PATH", str(ctx.paths.shims) + ":" + ctx.env.get("PATH", "/usr/bin:/bin")),),
    )


def _update_npm(spec: ToolSpec, ctx: Context, info: InstalledInfo) -> Plan:
    if not ctx.runner.which("npm"):
        return _install_npm(spec, ctx, None)
    if not info.current:
        return Plan(title="npm", blocked="Cannot determine the installed npm release line.")
    return Plan(
        title="Update npm within its current major release",
        steps=[_npm_step(ctx, f"^{Version(info.current).major}")],
    )


def _install_rustup(
    spec: ToolSpec, ctx: Context, version: str | None, *, make_default: bool
) -> Plan:
    toolchain = version or "stable"
    if version:
        require_version(version)
    located = ctx.runner.which("rustup")
    if located and not _is_ours(located, ctx):
        plan = Plan(title=f"Install Rust {toolchain} with the existing rustup")
        plan.add(
            Step(
                title=f"Install toolchain {toolchain}",
                kind="command",
                argv=("rustup", "toolchain", "install", toolchain),
            )
        )
        if make_default:
            plan.add(
                Step(
                    title=f"Make {toolchain} the default",
                    kind="command",
                    argv=("rustup", "default", toolchain),
                )
            )
        plan.notes.append(
            "An existing rustup was found. DevForge will not replace ~/.cargo or ~/.rustup."
        )
        return plan
    if spec.archive is None:
        return Plan(title="rust", blocked="Rust has no installer definition.")
    system = ctx.system()
    try:
        token = _arch_token(spec, system.arch, system.libc)
    except ToolError as exc:
        return Plan(title="rust", blocked=str(exc))
    url = spec.archive.url.format(version="0", arch=token)
    filename = spec.archive.filename or "rustup-init"
    checksum_url = (
        spec.archive.checksum_url.format(version="0", arch=token)
        if spec.archive.checksum_url
        else ""
    )
    digest = (
        _index(spec, ctx).sha256.get("rustup-init", {}).get(_sha_key(system.arch, system.libc), "")
    )
    cache = ctx.paths.cache / "archives" / "rust" / filename
    cargo = ctx.paths.install_root / "rust" / "cargo"
    rustup_home = ctx.paths.install_root / "rust" / "rustup"
    plan = Plan(title=f"Install Rust ({toolchain})")
    plan.add(
        Step(
            title="Download rustup-init",
            kind="download",
            urls=rewrite_urls(url, active_mirror(ctx)),
            dest=str(cache),
            sha256=digest,
            checksum_url=checksum_url,
            checksum_name=filename,
            fmt="file",
        )
    )
    env = (("RUSTUP_HOME", str(rustup_home)), ("CARGO_HOME", str(cargo)))
    plan.add(
        Step(
            title=f"Run rustup-init for {toolchain}",
            kind="command",
            argv=(str(cache), "-y", "--no-modify-path", "--default-toolchain", toolchain),
            env=env,
        )
    )
    for binary in spec.shims:
        plan.add(
            Step(
                title=f"Shim {binary}",
                kind="write",
                path=str(ctx.paths.shims / binary),
                content=_cargo_shim(cargo / "bin" / binary, _rust_env(ctx)),
                policy="owned",
                fmt="executable",
            )
        )
    plan.steps.extend(shell_steps(ctx))
    plan.notes.append(
        "Rust is installed under the DevForge data directory and does not modify ~/.cargo."
    )
    return plan


def _upgrade_package(spec: ToolSpec, ctx: Context, info: InstalledInfo) -> Plan:
    system = ctx.system()
    packages = _choose_packages(spec, system.family, info.current, fallback=False)
    if not packages or not system.package_manager:
        return Plan(title=spec.name, blocked=f"Cannot upgrade {spec.name} on this system.")
    try:
        argv = tuple(upgrade(system.package_manager, packages))
    except PackageManagerError as exc:
        return Plan(title=spec.name, blocked=str(exc))
    plan = Plan(title=f"Update {spec.name}")
    plan.add(
        Step(
            title="Check package database"
            if system.package_manager == "pacman"
            else "Refresh package indexes",
            kind="command",
            argv=tuple(refresh(system.package_manager)),
            sudo=True,
            reason="Updates require current package indexes.",
        )
    )
    plan.add(
        Step(
            title="Upgrade " + " ".join(packages),
            kind="package-upgrade",
            argv=argv,
            sudo=True,
            reason=f"Upgrading {spec.name} uses the system package manager.",
            tool=spec.name,
            version=info.current or "",
            manager=system.package_manager,
            packages=packages,
        )
    )
    plan.notes.append("Uses the latest package published by the configured distro repositories.")
    return plan


def _remove_packages(spec: ToolSpec, ctx: Context, version: str | None, *, purge: bool) -> Plan:
    system = ctx.system()
    login_zsh = False
    if spec.name == "zsh":
        passwd = ctx.fs_root / "etc" / "passwd"
        if passwd.is_file():
            for line in passwd.read_text(encoding="utf-8").splitlines():
                fields = line.split(":")
                if len(fields) == 7 and fields[2] == str(ctx.euid):
                    login_zsh = Path(fields[6]).name == "zsh"
    if spec.name == "zsh" and (login_zsh or Path(ctx.env.get("SHELL", "")).name == "zsh"):
        return Plan(
            title=spec.name,
            blocked="Zsh is your current login shell. Select another login "
            "shell before uninstalling it, then log in again.",
        )
    if spec.name == "python":
        return Plan(
            title=spec.name,
            blocked="Refusing to remove distro Python: Linux system tools "
            "may depend on it. Remove user-managed versions with their own version manager.",
        )
    if version is None and system.family in spec.versioned_packages:
        version = detect(spec, ctx).current
    packages = _choose_packages(spec, system.family, version, fallback=False)
    if not packages or not system.package_manager:
        return Plan(
            title=spec.name,
            blocked=(
                f"{spec.name} is not a DevForge-managed copy, "
                "and there is no distro package to remove."
            ),
        )
    try:
        packages = tuple(installed_packages(system.package_manager, packages, ctx.runner))
        if not packages:
            return Plan(
                title=spec.name,
                empty_message="No matching distro packages are installed. "
                "If the binary came from a manual install, use its original installer.",
            )
        argv = tuple(remove(system.package_manager, packages, purge=purge))
    except PackageManagerError as exc:
        return Plan(title=spec.name, blocked=str(exc))
    plan = Plan(title=f"Remove {spec.name}")
    if system.package_manager == "apt":
        preview = ctx.runner.run(("apt-get", "--simulate", *argv[1:]), timeout=60)
        if preview.code != 0:
            plan.blocked = "Package removal simulation failed: " + (
                preview.stderr or preview.stdout
            )
            return plan
        protected = {
            "apt",
            "dpkg",
            "sudo",
            "systemd",
            "libc6",
            "python3",
            "openssh-server",
            "network-manager",
            "ubuntu-desktop",
            "linux-image-generic",
        }
        removed = {
            line.split()[1].split(":")[0]
            for line in preview.stdout.splitlines()
            if line.startswith("Remv ") and len(line.split()) > 1
        }
        risky = (removed & protected) - set(packages)
        if risky:
            plan.blocked = "Removal would also remove protected system packages: " + ", ".join(
                sorted(risky)
            )
            return plan
        if preview.stdout.strip():
            plan.notes.append("Native package-manager removal preview:\n" + preview.stdout.strip())
    plan.notes.append(
        "The package manager may remove dependent packages. Database data and VM disks "
        "are never deleted by DevForge itself. Keep a verified backup before removal."
    )
    plan.add(
        Step(
            title=("Purge " if purge else "Remove ") + " ".join(packages),
            kind="command",
            argv=argv,
            sudo=True,
            reason="Removing system packages requires root.",
        )
    )
    if not purge:
        plan.notes.append("Configuration is kept. Pass --purge to remove it too.")
    return plan


def _pin_project(spec: ToolSpec, ctx: Context, version: str) -> Plan:
    primary = spec.project_files[0] if spec.project_files else ".tool-versions"
    if primary not in PIN_NAMES and primary != ".tool-versions":
        return Plan(title=spec.name, blocked=f"Refusing to write an unexpected pin file {primary}.")
    plan = Plan(title=f"Pin {spec.name} {version} in this project")
    plan.add(
        Step(
            title=f"Write {primary}",
            kind="write",
            path=str(ctx.cwd / primary),
            content=version + "\n",
            policy="project",
        )
    )
    if primary != ".tool-versions":
        path = ctx.cwd / ".tool-versions"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        lines: list[str] = []
        replaced = False
        for line in existing.splitlines():
            if line.split(" ", 1)[0] == spec.tool_key:
                lines.append(f"{spec.tool_key} {version}")
                replaced = True
            else:
                lines.append(line)
        if not replaced:
            lines.append(f"{spec.tool_key} {version}")
        plan.add(
            Step(
                title="Update .tool-versions",
                kind="write",
                path=str(path),
                content="\n".join(line for line in lines if line).rstrip() + "\n",
                policy="project",
            )
        )
    return plan


def _choose_packages(
    spec: ToolSpec, family: str, version: str | None, *, fallback: bool
) -> tuple[str, ...]:
    source = spec.fallback_packages if fallback and spec.fallback_packages else spec.packages
    if version and family in spec.versioned_packages and not fallback:
        return tuple(_expand(item, version, "") for item in spec.versioned_packages[family])
    if version and family in spec.versioned_packages and fallback:
        return tuple(_expand(item, version, "") for item in spec.versioned_packages[family])
    return source.get(family, ())


def _satisfied(spec: ToolSpec, info: InstalledInfo, version: str | None, family: str) -> bool:
    if version and version in info.versions:
        return True
    if info.current is None:
        return False
    if version is None:
        return True
    return _matches(info.current, version)


def _matches(current: str, requested: str) -> bool:
    return current == requested or current.startswith(requested + ".")


def _package_update(spec: ToolSpec, ctx: Context, info: InstalledInfo) -> tuple[bool | None, str]:
    system = ctx.system()
    packages = _choose_packages(spec, system.family, info.current, fallback=False)
    if not packages or not system.package_manager or info.current is None:
        return None, "unknown"
    installed, candidate = lookup_versions(system.package_manager, packages[0], ctx.runner)
    if not installed or not candidate:
        return None, "unknown"
    if installed == candidate:
        return False, "package"
    if system.package_manager == "apt":
        result = ctx.runner.run(
            ("dpkg", "--compare-versions", candidate, "gt", installed), timeout=20
        )
        if result.code not in {0, 1}:
            return None, "unknown"
        return result.code == 0, "package"
    return True, "package"


def _add_default(plan: Plan, spec: ToolSpec, ctx: Context, version: str) -> None:
    plan.add(
        Step(
            title=f"Set the default {spec.name} to {version}",
            kind="write",
            path=str(ctx.paths.install_root / spec.name / "default"),
            content=version + "\n",
            policy="owned",
        )
    )


def _add_shims(plan: Plan, spec: ToolSpec, ctx: Context) -> None:
    if not spec.shims or spec.shim_kind == "cargo":
        return
    root = ctx.paths.install_root / spec.name
    for binary in spec.shims:
        content = render_shim(
            binary=binary,
            tool=spec.name,
            root=root,
            env_file=ctx.paths.env_file,
            project_files=spec.project_files,
            system_bins=spec.system_bins,
            shim_kind=spec.shim_kind,
            runtime_env=spec.runtime_env,
        )
        plan.add(
            Step(
                title=f"Write the {binary} shim",
                kind="write",
                path=str(ctx.paths.shims / binary),
                content=content,
                policy="owned",
                fmt="executable",
            )
        )


def _add_env(plan: Plan, ctx: Context) -> None:
    assignments = env_assignments(active_mirror(ctx))
    content = render_env(assignments)
    current = ctx.paths.env_file.read_text(encoding="utf-8") if ctx.paths.env_file.is_file() else ""
    if content == current:
        return
    plan.add(
        Step(
            title="Write shim environment",
            kind="write",
            path=str(ctx.paths.env_file),
            content=content,
            policy="owned",
        )
    )


# Generic links. --install needs the link; --set only selects a registered path.
_ALTERNATIVE_LINKS = {
    "php": "/usr/bin/php",
    "php-fpm": "/usr/sbin/php-fpm",
    "java": "/usr/bin/java",
}


def _add_alternatives(plan: Plan, spec: ToolSpec, ctx: Context, version: str) -> None:
    if ctx.system().family != "debian":
        return
    added = False
    for name, template in spec.alternatives:
        target = _expand(template, version, ctx.system().arch)
        plan.add(
            Step(
                title=f"Point the {name} alternative at {target}",
                kind="alternatives",
                argv=("update-alternatives", "--set", name, target),
                sudo=True,
                reason=f"Switching the system {name} default requires root.",
                path=target,
                dest=_ALTERNATIVE_LINKS.get(name, ""),
            )
        )
        added = True
    if added:
        plan.notes.append(
            "A Debian alternative that is not registered yet is registered, then selected."
        )


def _add_group_and_services(plan: Plan, spec: ToolSpec, ctx: Context) -> None:
    system = ctx.system()
    if spec.linux_group and _SERVICE.fullmatch(spec.linux_group):
        user = ctx.env.get("SUDO_USER", "") if ctx.euid == 0 else str(ctx.env.get("USER", ""))
        if user and user != "root":
            plan.add(
                Step(
                    title=f"Add {user} to the {spec.linux_group} group",
                    kind="group",
                    group=spec.linux_group,
                    user=user,
                    sudo=True,
                    reason=f"Joining the {spec.linux_group} group requires root.",
                )
            )
    names = spec.services.get(system.family) or spec.services.get("default", ())
    if spec.name in {"postgresql", "mysql", "mariadb", "mongodb"}:
        plan.notes.append(
            "Initialize the database using the distro's documented procedure if this "
            "is a new data directory, then use the service menu to start it. "
            "Existing data directories are not initialized or reset by DevForge."
        )
        return
    for service in names:
        if _SERVICE.fullmatch(service) is None:
            continue
        if system.virtualization == "container":
            plan.notes.append(f"Not enabling {service} inside a container.")
            continue
        if system.init == "systemd":
            plan.add(
                Step(
                    title=f"Enable and start {service}",
                    kind="command",
                    argv=("systemctl", "enable", "--now", service),
                    sudo=True,
                    reason=f"Starting {service} requires root.",
                )
            )
        elif system.init == "openrc":
            plan.add(
                Step(
                    title=f"Enable {service}",
                    kind="command",
                    argv=("rc-update", "add", service, "default"),
                    sudo=True,
                    reason=f"Starting {service} requires root.",
                )
            )
        else:
            plan.notes.append(f"Start {service} with this machine's init system after the install.")


def _managed_versions(spec: ToolSpec, ctx: Context) -> list[str]:
    root = ctx.paths.install_root / spec.name
    if not root.is_dir():
        return []
    found: list[str] = []
    for child in root.iterdir():
        if (
            child.is_dir()
            and not child.is_symlink()
            and is_valid_version(child.name)
            and (child / ".devforge-complete").is_file()
        ):
            found.append(child.name)
    ordered = sorted((Version(item) for item in found), reverse=True)
    return [item.value for item in ordered]


def _default_version(spec: ToolSpec, ctx: Context) -> str:
    path = ctx.paths.install_root / spec.name / "default"
    if not path.is_file():
        return ""
    token = path.read_text(encoding="utf-8").strip()
    return token if is_valid_version(token) else ""


def _coexist_notes(spec: ToolSpec, ctx: Context) -> list[str]:
    notes: list[str] = []
    for dirname in spec.coexist_dirs:
        if (ctx.paths.home / dirname).exists():
            notes.append(f"{dirname} is present. DevForge will not modify it.")
    for key in spec.coexist_env:
        if ctx.env.get(key):
            notes.append(f"{key} is set. DevForge will leave that setup in place.")
    return notes


def _is_ours(path: str, ctx: Context) -> bool:
    # Use the invocation path rather than resolving a shim's target: it is
    # the shim directory that establishes DevForge ownership.
    candidate = Path(path).absolute()
    return any(root.absolute() in candidate.parents for root in (ctx.paths.data, ctx.paths.shims))


def _known_newest(index: VersionIndex) -> str:
    """The highest published version, ignoring the LTS preference used by install."""
    found = [item for item in (index.latest, *index.versions) if is_valid_version(item)]
    if not found:
        return ""
    return max(found, key=Version)


def _index(spec: ToolSpec, ctx: Context) -> VersionIndex:
    return load_index(ctx.data_root, spec.name, cache=ctx.paths.cache)


def _arch_token(spec: ToolSpec, arch: str, libc: str) -> str:
    archive = spec.archive
    if archive is None:
        return arch
    musl = archive.libc_arch_map.get("musl", {})
    if libc == "musl" and musl:
        if arch not in musl:
            raise ToolError(f"No musl build of {spec.name} is published for {arch}.")
        return musl[arch]
    if archive.arch_map:
        if arch not in archive.arch_map:
            raise ToolError(f"No {spec.name} build is published for {arch}.")
        return archive.arch_map[arch]
    return arch


def _sha_key(arch: str, libc: str) -> str:
    if libc == "musl":
        return f"{arch}-musl"
    return arch


def _expand(template: str, version: str, arch: str) -> str:
    numbers = re.findall(r"\d+", version) if version else []
    major = numbers[0] if numbers else "0"
    minor = numbers[1] if len(numbers) > 1 else "0"
    return (
        template.replace("{version}", version)
        .replace("{major}", major)
        .replace("{minor}", minor)
        .replace("{arch}", arch)
    )


def _rust_env(ctx: Context) -> tuple[tuple[str, str], ...]:
    return (
        ("RUSTUP_HOME", str(ctx.paths.install_root / "rust" / "rustup")),
        ("CARGO_HOME", str(ctx.paths.install_root / "rust" / "cargo")),
    )


def _cargo_shim(binary: Path, env: tuple[tuple[str, str], ...] = ()) -> str:
    exports = "".join(f"export {key}={_sh(value)}\n" for key, value in env)
    return f'#!/bin/sh\nset -eu\n{exports}exec {_sh(str(binary))} "$@"\n'


def _sh(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _release_index(spec: ToolSpec, ctx: Context) -> VersionIndex:
    """Refresh for lifecycle operations; dry runs use known data without cache writes."""
    index = _index(spec, ctx)
    if ctx.offline or ctx.dry_run or not index.refresh_url:
        return index
    updated = refresh_index(index, ctx.fetcher)
    save_index(ctx.paths.cache, updated)
    return updated
