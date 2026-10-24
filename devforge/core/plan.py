"""Plan, show, confirm, and apply.

Every mutating command builds a :class:`Plan`. ``--dry-run`` shows it and
returns. Applying a plan is the only path that writes or runs commands.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from devforge import strings as s
from devforge.core.archive import ArchiveError, safe_extract
from devforge.core.net import DownloadError, Fetcher, download, parse_checksum_text
from devforge.core.paths import Paths
from devforge.core.pkgmgr import comparable, lookup_versions
from devforge.core.runner import Runner
from devforge.core.state import StateError, backup_file, restore_backup
from devforge.core.versioning import release_line
from devforge.ui import Printer

PIN_NAMES = {
    ".nvmrc",
    ".node-version",
    ".python-version",
    ".php-version",
    ".go-version",
    ".ruby-version",
    ".java-version",
    ".bun-version",
    ".deno-version",
    ".tool-versions",
}


@dataclass
class Step:
    """One planned action. Fields that do not apply stay empty."""

    title: str
    kind: str
    argv: tuple[str, ...] = ()
    sudo: bool = False
    reason: str = ""
    urls: tuple[str, ...] = ()
    dest: str = ""
    sha256: str = ""
    path: str = ""
    content: str = ""
    archive: str = ""
    fmt: str = ""
    policy: str = ""
    group: str = ""
    user: str = ""
    service: str = ""
    checksum_url: str = ""
    checksum_name: str = ""
    env: tuple[tuple[str, str], ...] = ()
    tool: str = ""
    version: str = ""
    manager: str = ""
    packages: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"title": self.title, "kind": self.kind}
        if self.argv:
            payload["argv"] = list(self.argv)
        if self.sudo:
            payload["sudo"] = True
            payload["reason"] = self.reason
        if self.urls:
            payload["urls"] = list(self.urls)
        if self.dest:
            payload["dest"] = self.dest
        if self.sha256:
            payload["sha256"] = self.sha256
        if self.path:
            payload["path"] = self.path
        if self.tool:
            payload.update(
                tool=self.tool,
                version=self.version,
                manager=self.manager,
                packages=list(self.packages),
            )
        return payload


@dataclass
class Plan:
    """A set of actions that are shown before they run."""

    title: str
    steps: list[Step] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blocked: str = ""
    empty_message: str = ""

    def add(self, step: Step) -> None:
        self.steps.append(step)

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "blocked": self.blocked,
            "empty_message": self.empty_message,
            "notes": list(self.notes),
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass
class ApplyContext:
    """The pieces of the app the plan engine is allowed to touch."""

    printer: Printer
    paths: Paths
    runner: Runner
    fetcher: Fetcher
    dry_run: bool
    assume_yes: bool
    as_json: bool
    euid: int
    fs_root: Path
    cwd: Path
    home: Path
    env: Mapping[str, str]


def display_argv(step: Step, euid: int) -> list[str]:
    if step.sudo and euid != 0:
        return ["sudo", "--", *step.argv]
    return list(step.argv)


def show_plan(plan: Plan, ctx: ApplyContext) -> None:
    """Print the plan for a human. JSON output is handled by the caller."""
    if plan.blocked:
        ctx.printer.error(plan.blocked)
        return
    if not plan.steps:
        ctx.printer.ok(plan.empty_message or s.INFO_PLAN_EMPTY)
        for note in plan.notes:
            ctx.printer.info(note)
        return
    ctx.printer.info(s.INFO_PLAN_HEADER.format(count=len(plan.steps)))
    for index, step in enumerate(plan.steps, start=1):
        title = step.title
        if step.sudo and ctx.euid != 0:
            title = f"{title} (sudo: {step.reason})"
        ctx.printer.plan_line(index, title)
        if step.argv:
            rendered = " ".join(shlex.quote(part) for part in display_argv(step, ctx.euid))
            ctx.printer.raw(f"     $ {rendered}")
        for url in step.urls:
            ctx.printer.raw(f"     {url}")
        if step.kind == "download" and not step.sha256:
            ctx.printer.raw(
                "     checksum: resolved from the published checksum file at apply time"
            )
    for note in plan.notes:
        ctx.printer.info(note)


def apply_plan(plan: Plan, ctx: ApplyContext) -> int:
    """Show ``plan`` and, unless this is a dry run, carry it out."""
    if ctx.as_json:
        _write_json(ctx, plan.to_dict())
    else:
        show_plan(plan, ctx)
    if plan.blocked:
        return 1
    if not plan.steps:
        return 0
    if ctx.dry_run:
        if not ctx.as_json:
            ctx.printer.info(s.INFO_DRY_RUN)
        return 0
    if not ctx.printer.confirm():
        ctx.printer.warn(s.WARN_DECLINED)
        return 1
    try:
        for step in plan.steps:
            _apply_step(step, ctx)
    except (DownloadError, ArchiveError, StateError, OSError, ValueError) as exc:
        ctx.printer.error(str(exc))
        return 1
    if not ctx.as_json:
        ctx.printer.ok(s.OK_DONE)
    return 0


def _write_json(ctx: ApplyContext, payload: dict[str, object]) -> None:
    import json

    ctx.printer.stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _apply_step(step: Step, ctx: ApplyContext) -> None:
    if step.kind == "verify-install":
        root = Path(step.path)
        if not ctx.paths.contains(root):
            raise ValueError(f"refusing to verify {root}")
        for binary in step.packages:
            if not any((root / prefix / binary).is_file() for prefix in ("bin", "")):
                raise ValueError(f"Archive is missing the expected executable: {binary}")
        return
    if step.kind == "package-upgrade":
        _package_upgrade_step(step, ctx)
        return
    if step.kind == "command":
        _run_command(step, ctx)
        return
    if step.kind == "download":
        _download_step(step, ctx)
        return
    if step.kind == "extract":
        _extract_step(step, ctx)
        return
    if step.kind == "write":
        _write_step(step, ctx)
        return
    if step.kind == "delete":
        _delete_step(step, ctx)
        return
    if step.kind == "backup":
        path = Path(step.path)
        if not _allowed(path, "etc", ctx) and not ctx.paths.contains(path):
            raise ValueError(f"refusing to back up {path}")
        backup_file(path)
        return
    if step.kind == "restore":
        path = Path(step.path)
        if not _allowed(path, "etc", ctx) and not ctx.paths.contains(path):
            raise ValueError(f"refusing to restore {path}")
        if not restore_backup(path):
            raise StateError(f"no backup exists for {path}")
        return
    if step.kind == "group":
        _group_step(step, ctx)
        return
    if step.kind == "service":
        _service_step(step, ctx)
        return
    if step.kind == "alternatives":
        _alternatives_step(step, ctx)
        return
    if step.kind == "note":
        return
    raise ValueError(f"unknown plan step {step.kind}")


def _package_upgrade_step(step: Step, ctx: ApplyContext) -> None:
    # Check after refresh, immediately before the native upgrade. Runtime
    # packages without a versioned name must never silently cross release lines.
    if step.tool in {"php", "python", "java", "ruby", "dotnet", "node", "go"}:
        for package in step.packages:
            _installed, candidate = lookup_versions(step.manager, package, ctx.runner)
            parsed = comparable(candidate)
            if not parsed or release_line(step.tool, parsed) != release_line(
                step.tool, step.version
            ):
                raise ValueError(
                    f"Cannot safely update {step.tool} {step.version}: {package} candidate "
                    f"is {candidate or 'unknown'}. Select another line explicitly with install."
                )
    _run_command(step, ctx)


_DOTTED_VERSION = re.compile(r"(\d+)\.(\d+)")
_JAVA_MAJOR = re.compile(r"java-(\d+)")
_ALTERNATIVE_LINK = re.compile(r"^/usr/s?bin/[a-z0-9][a-z0-9+._-]{0,40}$")


def _alternatives_step(step: Step, ctx: ApplyContext) -> None:
    """Select a Debian alternative, registering it when the group has no entry.

    ``--set`` fails with "no alternatives for <name>" until ``--install`` has
    created the group. Re-installing a path that is already registered would
    replace its slaves, so a registered target is only selected.
    """
    if step.path and not Path(step.path).exists():
        return
    if len(step.argv) != 4 or step.argv[0] != "update-alternatives" or step.argv[1] != "--set":
        _run_command(step, ctx)
        return
    name, target = step.argv[2], step.argv[3]
    if _ALTERNATIVE_LINK.fullmatch(step.dest) and _alternative_needs_install(name, target, ctx):
        _run_command(
            Step(
                title=f"Register the {name} alternative at {target}",
                kind="command",
                argv=(
                    "update-alternatives",
                    "--install",
                    step.dest,
                    name,
                    target,
                    _alternative_priority(target),
                ),
                sudo=step.sudo,
                reason=step.reason,
            ),
            ctx,
        )
    _run_command(step, ctx)


def _alternative_needs_install(name: str, target: str, ctx: ApplyContext) -> bool:
    result = ctx.runner.run(("update-alternatives", "--query", name), timeout=30)
    if result.code == 0:
        prefix = "Alternative:"
        for line in result.stdout.splitlines():
            if line.startswith(prefix) and line[len(prefix) :].strip() == target:
                return False
        return True
    detail = f"{result.stdout}\n{result.stderr}".lower()
    return "no alternatives" in detail


def _alternative_priority(target: str) -> str:
    """Match Debian's PHP priority: major * 10 + minor, taken from the filename."""
    name = target.rsplit("/", 1)[-1]
    dotted = list(_DOTTED_VERSION.finditer(name))
    if dotted:
        found = dotted[-1]
        return str(int(found.group(1)) * 10 + int(found.group(2)))
    java = list(_JAVA_MAJOR.finditer(target))
    if java:
        return str(int(java[-1].group(1)) * 10)
    return "10"


def _run_command(step: Step, ctx: ApplyContext) -> None:
    argv = display_argv(step, ctx.euid)
    env = None
    if step.env:
        env = dict(ctx.env)
        env.update(dict(step.env))
    result = ctx.runner.run(argv, timeout=600, env=env)
    if result.code != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OSError(
            s.ERR_FAILED.format(action=step.title, code=result.code)
            + (f" {detail}" if detail else "")
        )


def _extract_step(step: Step, ctx: ApplyContext) -> None:
    import shutil

    dest = Path(step.dest)
    if not _under(dest, ctx.paths.data) and not ctx.paths.contains(dest):
        raise ValueError(f"refusing to extract into {dest}")
    if step.fmt == "file":
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(step.archive, dest)
        dest.chmod(0o755)
        return
    safe_extract(Path(step.archive), dest, fmt=step.fmt)


def _download_step(step: Step, ctx: ApplyContext) -> None:
    digest = step.sha256
    if not digest:
        if not step.checksum_url or not step.checksum_name:
            raise DownloadError(f"no checksum is available for {step.title}")
        payload = ctx.fetcher.get(step.checksum_url)
        found = parse_checksum_text(payload.decode("utf-8", errors="replace"), step.checksum_name)
        if not found:
            stripped = payload.decode("utf-8", errors="replace").strip().split()
            if len(stripped) == 1 and len(stripped[0]) == 64:
                found = stripped[0].lower()
        if not found:
            raise DownloadError(f"checksum file did not list {step.checksum_name}")
        digest = found
    destination = Path(step.dest)
    download(step.urls, destination, sha256=digest, fetcher=ctx.fetcher)
    if step.fmt == "file":
        destination.chmod(0o755)


def _write_step(step: Step, ctx: ApplyContext) -> None:
    path = Path(step.path)
    if not _allowed(path, step.policy, ctx):
        raise ValueError(f"refusing to write {path}")
    if path.exists() or path.is_symlink():
        backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(step.content, encoding="utf-8")
    if step.fmt == "executable":
        path.chmod(0o755)


def _delete_step(step: Step, ctx: ApplyContext) -> None:
    path = Path(step.path)
    if not ctx.paths.contains(path):
        raise ValueError(f"refusing to delete {path}; it is not inside a DevForge directory")
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        _remove_tree(path)
        return
    raise ValueError(f"refusing to delete missing path {path}")


def _remove_tree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _group_step(step: Step, ctx: ApplyContext) -> None:
    user = step.user
    if not user or user == "root":
        return
    current = ctx.runner.run(["id", "-nG", user], timeout=5)
    if current.code == 0 and step.group in current.stdout.split():
        return
    _run_command(
        Step(
            title=step.title,
            kind="command",
            argv=("usermod", "-aG", step.group, user),
            sudo=True,
            reason=step.reason,
        ),
        ctx,
    )


def _service_step(step: Step, ctx: ApplyContext) -> None:
    if not step.argv:
        return
    _run_command(step, ctx)


def _allowed(path: Path, policy: str, ctx: ApplyContext) -> bool:
    if policy == "owned":
        return ctx.paths.contains(path) or _under(path, ctx.paths.data)
    if policy == "rc":
        return path.name in {".bashrc", ".zshrc", "config.fish"} and _under(path, ctx.home)
    if policy == "project":
        try:
            return path.parent.resolve() == ctx.cwd.resolve() and path.name in PIN_NAMES
        except OSError:
            return False
    if policy == "etc":
        allowed = {
            os.path.abspath(ctx.fs_root / "etc" / "resolv.conf"),
            os.path.abspath(ctx.fs_root / "etc" / "docker" / "daemon.json"),
        }
        return os.path.abspath(path) in allowed
    return False


def _under(path: Path, root: Path) -> bool:
    """True when ``path`` is inside ``root``. The root itself is not allowed."""
    try:
        target = path.expanduser().resolve()
        resolved = root.expanduser().resolve()
    except OSError:
        return False
    return target != resolved and resolved in target.parents


def current_user(env: Mapping[str, str]) -> str:
    """The account a group change should touch. Root uses ``SUDO_USER`` when set."""
    if os.geteuid() == 0:
        sudo_user = env.get("SUDO_USER", "")
        if sudo_user and sudo_user != "root":
            return sudo_user
        return ""
    return env.get("USER", "")
