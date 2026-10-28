"""Regression tests for privileged management and database backup failure paths."""

from __future__ import annotations

import builtins
import io
import json
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from devforge.commands.configuration import cmd_config
from devforge.commands.network import cmd_dns_restore, cmd_dns_set
from devforge.commands.services import service_plan
from devforge.context import Context
from devforge.core.database import backup_plan
from devforge.core.net import MemoryFetcher, download, sha256_bytes
from devforge.core.pkgmgr import refresh
from devforge.core.plan import apply_plan
from devforge.core.runner import RunResult, ScriptedRunner, SubprocessRunner
from devforge.core.state import save_json
from devforge.tools.managed import load_tool
from devforge.tui import _tool_options, menu
from devforge.ui import Printer
from tests.support import machine


def client(ctx: Context, binary: str) -> ScriptedRunner:
    assert isinstance(ctx.runner, ScriptedRunner)
    ctx.runner.which_map[binary] = f"/usr/bin/{binary}"
    return ctx.runner


@pytest.mark.parametrize(
    "tool,binary,database",
    [
        ("mysql", "mysqldump", None),
        ("mariadb", "mariadb-dump", "app"),
        ("postgresql", "pg_dump", "app"),
        ("mongodb", "mongodump", None),
        ("redis", "redis-cli", None),
    ],
)
def test_backup_dry_run_does_not_write(tmp_path, tool, binary, database):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    runner = client(ctx, binary)
    plan = backup_plan(ctx, tool, database)
    assert not plan.blocked
    calls = list(runner.calls)
    assert apply_plan(plan, ctx.apply()) == 0
    assert runner.calls == calls
    assert not (ctx.paths.state / "backups").exists()


def test_backup_publishes_private_file_without_overwrite(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = client(ctx, "mysqldump")
    runner.when(lambda a: a[0] == "/usr/bin/mysqldump", replace_result(stdout="SQL dump"))
    plan = backup_plan(ctx, "mysql", "app")
    destination = Path(plan.steps[0].path)
    assert apply_plan(plan, ctx.apply()) == 0
    assert destination.read_bytes() == b"SQL dump"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert apply_plan(plan, ctx.apply()) == 1
    assert destination.read_bytes() == b"SQL dump"
    assert not list(destination.parent.glob(".partial-*"))


def replace_result(*, stdout: str = "", code: int = 0, stderr: str = "") -> RunResult:

    return RunResult((), code, stdout, stderr)


@pytest.mark.parametrize("code,payload", [(1, "partial dump"), (0, "")])
def test_failed_and_empty_backups_are_not_published(tmp_path, code, payload):
    ctx, _, err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = client(ctx, "pg_dump")
    runner.when(
        lambda a: a[0] == "/usr/bin/pg_dump",
        replace_result(code=code, stdout=payload, stderr="password=hidden" if code else ""),
    )
    plan = backup_plan(ctx, "postgresql", "app")
    assert apply_plan(plan, ctx.apply()) == 1
    assert not Path(plan.steps[0].path).exists()
    assert not list(Path(plan.steps[0].path).parent.iterdir())
    assert "hidden" not in err.getvalue()


def test_backups_refuse_symlink_directory(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    client(ctx, "mysqldump")
    target = tmp_path / "elsewhere"
    target.mkdir()
    ctx.paths.state.mkdir(parents=True)
    (ctx.paths.state / "backups").symlink_to(target, target_is_directory=True)
    assert apply_plan(backup_plan(ctx, "mysql"), ctx.apply()) == 1
    assert not list(target.iterdir())


@pytest.mark.parametrize("name", ["--help", "postgresql://host/db", "../app", "app;rm", ""])
def test_backup_database_names_cannot_inject_options(tmp_path, name):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    client(ctx, "pg_dump")
    assert backup_plan(ctx, "postgresql", name).blocked


def test_postgres_requires_name_and_redis_cannot_select_one(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    assert backup_plan(ctx, "postgresql").blocked
    assert backup_plan(ctx, "redis", "0").blocked
    assert backup_plan(ctx, "nginx").blocked
    assert backup_plan(ctx, "mysql").blocked


def test_mongodb_credentials_stay_in_private_config(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    client(ctx, "mongodump")
    config = tmp_path / "mongo.yml"
    config.write_text("password: confidential\n")
    config.chmod(0o644)
    assert backup_plan(ctx, "mongodb", client_config=config).blocked
    config.chmod(0o600)
    plan = backup_plan(ctx, "mongodb", client_config=config)
    assert not plan.blocked
    assert "confidential" not in json.dumps(plan.to_dict())
    assert f"--config={config}" in plan.steps[0].argv


def test_streaming_runner_preserves_binary_output_and_errors(tmp_path):
    target = tmp_path / "dump"
    with target.open("wb") as output:
        result = SubprocessRunner().stream(
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.buffer.write(bytes([0,255,10]));"
                "sys.stderr.write('diagnostic')",
            ],
            output,
        )
    assert result.code == 0
    assert target.read_bytes() == bytes([0, 255, 10])
    assert result.stderr == "diagnostic"


def test_state_and_download_do_not_follow_predictable_temporary_symlinks(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    state = tmp_path / "state.json"
    Path(str(state) + ".tmp").symlink_to(victim)
    save_json(state, {"ok": True})
    archive = tmp_path / "download"
    Path(str(archive) + ".partial").symlink_to(victim)
    download(
        ["https://test/file"],
        archive,
        sha256=sha256_bytes(b"data"),
        fetcher=MemoryFetcher({"https://test/file": b"data"}),
    )
    assert victim.read_text() == "keep"
    assert archive.read_bytes() == b"data"


def test_eof_does_not_confirm_even_when_default_is_yes(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    def eof():
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    assert not Printer.create(out=Terminal()).confirm(default=True)


def test_nginx_config_rolls_back_after_installed_validation_failure(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = client(ctx, "nginx")
    target = ctx.fs_root / "etc/nginx/nginx.conf"
    target.parent.mkdir()
    target.write_text("original\n")
    source = tmp_path / "edited.conf"
    source.write_text("new\n")
    runner.when_argv(["sudo", "--", "/usr/bin/nginx", "-t"], code=1, stderr="invalid config")
    assert cmd_config(ctx, "nginx", "apply", source) == 1
    assert target.read_text() == "original\n"
    assert Path(str(target) + ".devforge.bak").read_text() == "original\n"


def test_nginx_config_dry_run_and_candidate_failure_leave_original(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    runner = client(ctx, "nginx")
    target = ctx.fs_root / "etc/nginx/nginx.conf"
    target.parent.mkdir()
    target.write_text("original\n")
    source = tmp_path / "edited.conf"
    source.write_text("new\n")
    assert cmd_config(ctx, "nginx", "apply", source) == 0
    assert target.read_text() == "original\n"
    ctx.dry_run = False
    runner.when(lambda a: "-c" in a, replace_result(code=1, stderr="bad candidate"))
    assert cmd_config(ctx, "nginx", "apply", source) == 1
    assert target.read_text() == "original\n"


def test_removal_filters_missing_packages_and_checks_dependency_preview(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.when_argv(["dpkg-query", "-W", "-f=${db:Status-Status}", "nginx"], stdout="installed")
    runner.when_argv(
        ["apt-get", "--simulate", "remove", "-y", "nginx"],
        stdout="Remv nginx [1.0]\nRemv openssh-server [1.0]",
    )
    plan = load_tool("nginx").uninstall(ctx, None, purge=False)
    assert "protected" in plan.blocked
    assert not any(call[:3] == ("apt-get", "remove", "-y") for call in runner.calls)
    assert load_tool("python").uninstall(ctx, None, purge=False).blocked


def test_absent_package_removal_is_a_noop(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    plan = load_tool("nginx").uninstall(ctx, None, purge=False)
    assert not plan.steps and plan.empty_message


def test_kvm_server_gui_restriction_and_service_commands(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    ctx._system = replace(ctx.system(), form_factor="server", init="systemd", virtualization="none")
    assert load_tool("kvm-gui").install(ctx, None, make_default=True).blocked
    plan = load_tool("kvm").install(ctx, None, make_default=True)
    assert not plan.blocked
    assert not any(step.kind == "group" for step in plan.steps)
    assert service_plan(ctx, "kvm", "start").steps[0].argv[-1] == "libvirtd"
    assert service_plan(ctx, "redis", "start").steps[0].argv[-1] == "redis-server"
    ctx._system = replace(ctx.system(), virtualization="container")
    assert service_plan(ctx, "nginx", "restart").blocked
    assert load_tool("kvm").install(ctx, None, make_default=True).blocked


def test_backup_options_live_under_their_database(tmp_path):
    ctx, out, _ = machine(tmp_path, "debian-12", family="debian")
    options = dict(_tool_options(load_tool("mysql").status(ctx)))
    assert options["Database backups"] == "backups"
    assert "Database backups" not in dict(_tool_options(load_tool("nginx").status(ctx)))
    assert menu(ctx, iter(["0"])) == 0
    assert "Databases" in out.getvalue()
    assert "Virtualization / KVM" in out.getvalue()


def test_arch_preflight_never_refreshes_indexes_without_full_upgrade():
    assert refresh("pacman") == ["pacman", "-Dk"]


def test_networkmanager_dns_restores_connection_settings(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = client(ctx, "nmcli")
    runner.when_argv(
        ["nmcli", "-t", "-f", "NAME,STATE", "connection", "show", "--active"],
        stdout="wired:activated\n",
    )
    runner.when_argv(["nmcli", "-g", "ipv4.dns", "connection", "show", "wired"], stdout="")
    runner.when_argv(
        ["nmcli", "-g", "ipv4.ignore-auto-dns", "connection", "show", "wired"], stdout="no\n"
    )
    assert cmd_dns_set(ctx, "cloudflare") == 0
    assert cmd_dns_restore(ctx) == 0
    assert (
        "sudo",
        "--",
        "nmcli",
        "connection",
        "modify",
        "wired",
        "ipv4.dns",
        "",
        "ipv4.ignore-auto-dns",
        "no",
    ) in runner.calls
    assert not (ctx.paths.state / "networkmanager-dns.json").exists()


def test_log_refuses_symlink_target(tmp_path):
    from devforge.core.log import FileLog

    victim = tmp_path / "victim"
    victim.write_text("keep")
    logs = tmp_path / "logs"
    logs.mkdir()
    path = logs / "devforge.log"
    path.symlink_to(victim)
    log = FileLog(path)
    log.info("do not append")
    assert victim.read_text() == "keep"
    assert not log.enabled


def test_successful_command_keeps_json_stdout_parseable(tmp_path):
    ctx, out, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.as_json = True
    runner = client(ctx, "nginx")
    runner.when(lambda a: "-t" in a, replace_result(stdout="native output"))
    assert cmd_config(ctx, "nginx", "check") == 0
    assert json.loads(out.getvalue())["steps"][0]["kind"] == "command"


def test_versioned_php_removal_targets_detected_line(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    runner = client(ctx, "php")
    runner.when_argv(["/usr/bin/php", "-v"], stdout="PHP 8.5.12 (cli)")
    runner.when_argv(
        ["dpkg-query", "-W", "-f=${db:Status-Status}", "php8.5-cli"], stdout="installed"
    )
    plan = load_tool("php").uninstall(ctx, None, purge=False)
    assert not plan.blocked
    assert plan.steps[0].argv == ("apt-get", "remove", "-y", "php8.5-cli")


def test_installed_database_menu_lists_only_its_own_backups(tmp_path):
    from devforge.tui import _backup_menu

    ctx, out, _ = machine(tmp_path, "debian-12", family="debian")
    root = ctx.paths.state / "backups"
    (root / "mysql").mkdir(parents=True)
    (root / "redis").mkdir()
    (root / "mysql" / "my.sql").write_text("dump")
    (root / "redis" / "other.rdb").write_text("redis")
    assert not _backup_menu(ctx, iter(["2", "0"]), load_tool("mysql"))
    assert "my.sql" in out.getvalue()
    assert "other.rdb" not in out.getvalue()


def test_resolved_dns_restores_prior_servers_without_resetting_other_link_settings(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = client(ctx, "resolvectl")
    link = ctx.fs_root / "etc/resolv.conf"
    link.symlink_to("/run/systemd/resolve/stub-resolv.conf")
    runner.when_argv(["resolvectl", "status"], stdout="Link 2 (eth0)\n")
    runner.when_argv(["resolvectl", "dns", "eth0"], stdout="Link 2 (eth0): 9.9.9.9 2620:fe::fe\n")
    assert cmd_dns_set(ctx, "cloudflare") == 0
    assert cmd_dns_restore(ctx) == 0
    assert ("sudo", "--", "resolvectl", "dns", "eth0", "9.9.9.9", "2620:fe::fe") in runner.calls
    assert not any("revert" in call for call in runner.calls)
    assert link.is_symlink()


def test_redis_backup_reads_native_rdb_file_without_redirecting_status_output(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = client(ctx, "redis-cli")

    def write_rdb(argv: tuple[str, ...]) -> bool:
        if "--rdb" not in argv:
            return False
        Path(argv[-1]).write_bytes(b"REDIS0011\x00\xff")
        return True

    runner.when(write_rdb, replace_result(stdout="Transfer finished"))
    plan = backup_plan(ctx, "redis")
    assert apply_plan(plan, ctx.apply()) == 0
    assert Path(plan.steps[0].path).read_bytes() == b"REDIS0011\x00\xff"


def test_backup_command_timeout_is_a_failure(tmp_path):
    target = tmp_path / "partial"
    with target.open("wb") as output:
        result = SubprocessRunner().stream(
            [sys.executable, "-c", "import time;time.sleep(5)"], output, timeout=0.05
        )
    assert result.code == 124
    assert "timed out" in result.stderr


def test_generated_launcher_ignores_hostile_import_paths(tmp_path):
    import os
    import subprocess

    from devforge.core.release import _write_launcher

    root = tmp_path / "app"
    package = root / "devforge"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "__main__.py").write_text("print('trusted')")
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    (hostile / "runpy.py").write_text("raise RuntimeError('untrusted runpy')")
    (hostile / "devforge.py").write_text("raise RuntimeError('untrusted package')")
    launcher = tmp_path / "devforge"
    _write_launcher(launcher, root)
    result = subprocess.run(
        [str(launcher)],
        env={**os.environ, "PYTHONPATH": str(hostile)},
        cwd=hostile,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "trusted"
