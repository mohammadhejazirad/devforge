"""Native database backups, streamed to private files without shell or credentials."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, cast
from uuid import uuid4

from devforge.context import Context
from devforge.core.log import redact
from devforge.core.plan import ApplyContext, Plan, Step

DATABASES = ("mysql", "mariadb", "postgresql", "mongodb", "redis")


def backup_plan(
    ctx: Context, tool: str, database: str | None = None, client_config: Path | None = None
) -> Plan:
    """Build a local backup using the native client's existing authentication."""
    plan = Plan(title=f"Back up {tool}")
    if tool not in DATABASES:
        plan.blocked = "Backups support MySQL, MariaDB, PostgreSQL, MongoDB, and Redis."
        return plan
    if database is not None and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}", database):
        plan.blocked = "Use a database name of 1-63 letters, digits, underscores, dots or hyphens."
        return plan
    if tool == "postgresql" and not database:
        plan.blocked = "Choose a PostgreSQL database; each backup is a pg_dump custom archive."
        return plan
    if tool == "redis" and database:
        plan.blocked = (
            "Redis RDB backups include the whole instance, not a single logical database."
        )
        return plan
    binary = {
        "mysql": "mysqldump",
        "mariadb": "mariadb-dump",
        "postgresql": "pg_dump",
        "mongodb": "mongodump",
        "redis": "redis-cli",
    }[tool]
    located = ctx.runner.which(binary)
    if not located:
        plan.blocked = f"Missing {binary}. Install the matching database client/tools first."
        return plan
    argv = [located]
    if client_config:
        if tool != "mongodb":
            plan.blocked = (
                "--client-config is for mongodump. Other clients use their native config files."
            )
            return plan
        try:
            if (
                not client_config.is_file()
                or client_config.is_symlink()
                or client_config.stat().st_mode & 0o077
            ):
                raise ValueError(
                    "MongoDB client config must be a regular private file (chmod 600)."
                )
        except (OSError, ValueError) as exc:
            plan.blocked = str(exc)
            return plan
        argv += [f"--config={client_config.resolve()}"]
    extension = "sql"
    if tool in {"mysql", "mariadb"}:
        argv += ["--single-transaction", "--quick", "--routines", "--events", "--triggers"]
        argv += ["--databases", database] if database else ["--all-databases"]
        plan.notes.append(
            "Transactional tables get a consistent snapshot. Avoid DDL during the dump; "
            "nontransactional tables need a maintenance window or a physical backup."
        )
    elif tool == "postgresql":
        argv += ["--no-password", "--format=custom", f"--dbname={database}"]
        extension = "dump"
        plan.notes.append(
            "pg_dump covers one database. Cluster roles and tablespaces need pg_dumpall "
            "--globals-only separately. Use a client compatible with the server."
        )
    elif tool == "mongodb":
        argv += ["--archive", "--gzip"]
        if database:
            argv += [f"--db={database}"]
        extension = "archive.gz"
        plan.notes.append(
            "Quiesce writes for a consistent standalone dump. Replica-set point-in-time "
            "backups require an oplog-aware procedure."
        )
    else:
        extension = "rdb"
        argv += ["--rdb"]
        plan.notes.append(
            "Redis streams a full RDB snapshot; replication permissions are required."
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        ctx.paths.state
        / "backups"
        / tool
        / f"{stamp}-{database or 'all'}-{uuid4().hex[:12]}.{extension}"
    )
    plan.add(
        Step(
            title=f"Save {tool} backup to {destination}",
            kind="database-backup",
            argv=tuple(argv),
            path=str(destination),
            tool=tool,
        )
    )
    plan.notes.append(
        "Uses local native-client authentication; no password is accepted in arguments. "
        "Configure protected client files (.my.cnf, .pgpass), socket authentication, "
        "or the client's supported environment. Backups are private (0600), unencrypted. "
        "Copy them off-host and verify restoration on an isolated database."
    )
    return plan


def apply_backup(step: Step, ctx: ApplyContext) -> None:
    """Publish a successful dump atomically; never leave a partial final backup."""
    destination = Path(step.path)
    expected = ctx.paths.state / "backups" / step.tool
    if (
        step.tool not in DATABASES
        or destination.parent != expected
        or not ctx.paths.contains(destination)
    ):
        raise ValueError("refusing backup outside the database backup directory")
    # Refuse redirected backup directories, including parents inside owned roots.
    for parent in (ctx.paths.state, ctx.paths.state / "backups", expected):
        if parent.is_symlink():
            raise ValueError(f"refusing symlink backup directory: {parent}")
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    expected.chmod(0o700)
    with tempfile.NamedTemporaryFile(
        mode="w+b", dir=expected, prefix=".partial-", delete=False
    ) as f:
        temporary = Path(f.name)
        try:
            if step.tool == "redis":
                result = ctx.runner.run((*step.argv, str(temporary)), timeout=3600)
            else:
                result = ctx.runner.stream(step.argv, cast(BinaryIO, f), timeout=3600)
            if result.code:
                raise OSError(
                    f"{step.tool} backup failed (exit {result.code}): "
                    f"{redact(result.stderr or result.stdout)} "
                    "Check client/server compatibility, authentication, permissions "
                    "and free disk space."
                )
            f.flush()
            if temporary.stat().st_size == 0:
                raise OSError("Database client produced an empty backup; nothing was published.")
            os.fsync(f.fileno())
            temporary.chmod(0o600)
            # link is exclusive: an existing backup or symlink is never overwritten.
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
