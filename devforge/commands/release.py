"""Update the DevForge program itself from a published GitHub release."""

from __future__ import annotations

from pathlib import Path

from devforge import __version__
from devforge import strings as s
from devforge.context import Context
from devforge.core.release import (
    ReleaseError,
    apply_release,
    describe_update,
    fetch_digest,
    fetch_latest,
    is_newer,
    is_release_install,
    program_root,
)


def cmd_self_update(ctx: Context, *, root: Path | None = None) -> int:
    """Replace this install with a newer release. A checkout is left alone."""
    install = program_root() if root is None else root
    if not is_release_install(install):
        ctx.printer.info(s.INFO_CHECKOUT_UPDATE)
        return 0
    if ctx.offline:
        ctx.printer.error(s.ERR_UPDATE_OFFLINE)
        return 2
    try:
        notice = fetch_latest(ctx)
        if not is_newer(notice.version):
            ctx.printer.ok(s.OK_RELEASE_CURRENT.format(version=__version__))
            return 0
        digest = fetch_digest(ctx, notice)
    except ReleaseError as exc:
        ctx.printer.error(str(exc))
        return 1
    ctx.printer.info(s.INFO_RELEASE_READY.format(version=notice.version, current=__version__))
    ctx.printer.raw("Planned actions:")
    for line in describe_update(install, notice, digest):
        ctx.printer.raw(f"  {line}")
    if ctx.dry_run:
        ctx.printer.info(s.INFO_DRY_RUN)
        return 0
    if not ctx.printer.confirm(s.PROMPT_SELF_UPDATE):
        ctx.printer.warn(s.WARN_DECLINED)
        return 0
    try:
        apply_release(ctx, notice, digest, install)
    except ReleaseError as exc:
        ctx.printer.error(str(exc))
        return 1
    ctx.printer.ok(s.OK_SELF_UPDATED.format(version=notice.version))
    return 0
