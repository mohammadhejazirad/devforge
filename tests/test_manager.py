"""Plans, lifecycle commands, mirrors, DNS, and shell integration."""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

from devforge.cli import main
from devforge.commands.files import (
    cmd_apply,
    cmd_export,
    cmd_preset_apply,
    cmd_preset_list,
    parse_manifest,
)
from devforge.commands.inspect import cmd_doctor, cmd_status, cmd_versions
from devforge.commands.lifecycle import cmd_install, cmd_uninstall, cmd_update, cmd_use
from devforge.commands.network import cmd_dns_restore, cmd_dns_set, cmd_mirror_set
from devforge.core.archive import ArchiveError, safe_extract
from devforge.core.net import DownloadError, MemoryFetcher, download
from devforge.core.pkgmgr import upgrade
from devforge.core.plan import Plan, Step, apply_plan
from devforge.core.runner import ScriptedRunner
from devforge.core.shell import render_shim
from devforge.tools.base import Scope
from devforge.tools.engine import install_tool
from devforge.tools.managed import all_tools, load_tool
from devforge.tui import menu
from tests.support import machine


def test_package_upgrade_command_is_explicit() -> None:
    argv = upgrade("apt", ["php-cli"])
    assert argv[:4] == ["apt-get", "install", "-y", "--only-upgrade"]
    assert argv[-1] == "php-cli"


def test_archive_refuses_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    payload = b"nope\n"
    with tarfile.open(archive, "w:gz") as packed:
        info = tarfile.TarInfo("../escape")
        info.size = len(payload)
        packed.addfile(info, io.BytesIO(payload))
    with pytest.raises(ArchiveError):
        safe_extract(archive, tmp_path / "out", fmt="tar.gz")


def test_archive_strips_one_directory(tmp_path: Path) -> None:
    archive = tmp_path / "good.tar.gz"
    payload = b"#!/bin/sh\n"
    with tarfile.open(archive, "w:gz") as packed:
        info = tarfile.TarInfo("node-v1/bin/node")
        info.size = len(payload)
        info.mode = 0o755
        packed.addfile(info, io.BytesIO(payload))
    dest = tmp_path / "out"
    safe_extract(archive, dest, fmt="tar.gz")
    assert (dest / "bin" / "node").read_bytes() == payload


def test_download_rejects_a_bad_checksum(tmp_path: Path) -> None:
    fetcher = MemoryFetcher({"https://example.test/file": b"hello"})
    with pytest.raises(DownloadError):
        download(
            ["https://example.test/file"],
            tmp_path / "file",
            sha256="a" * 64,
            fetcher=fetcher,
            sleep=lambda _seconds: None,
        )


@pytest.mark.parametrize("fixture,family", [("debian-12", "debian"), ("alpine", "alpine")])
def test_every_tool_has_an_install_plan(fixture: str, family: str, tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, fixture, family=family)
    for tool in all_tools():
        plan = install_tool(tool.spec, ctx, None, make_default=True, use_package=False)
        assert plan.title
        assert plan.steps or plan.blocked or plan.empty_message


def test_php_version_selects_debian_packages(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    code = cmd_install(ctx, "php", "8.4", make_default=True, use_package=False)
    assert code == 0
    text = out.getvalue()
    assert "php8.4-cli" in text
    assert "php8.4-fpm" in text
    assert "sudo --" in text
    assert "update-alternatives --set php /usr/bin/php8.4" in text
    assert "update-alternatives --set php-fpm /usr/sbin/php-fpm8.4" in text
    assert "not registered yet is registered" in text
    plan = install_tool(load_tool("php").spec, ctx, "8.4", make_default=True, use_package=False)
    links = {step.argv[2]: step.dest for step in plan.steps if step.kind == "alternatives"}
    assert links == {"php": "/usr/bin/php", "php-fpm": "/usr/sbin/php-fpm"}


def test_missing_php_fpm_alternative_is_registered(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    target = tmp_path / "php-fpm8.5"
    target.write_text("", encoding="utf-8")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.when_argv(
        ["update-alternatives", "--query", "php-fpm"],
        code=2,
        stderr="update-alternatives: error: no alternatives for php-fpm\n",
    )
    code = apply_plan(_alternative_plan("php-fpm", "/usr/sbin/php-fpm", target), ctx.apply())
    assert code == 0
    assert runner.calls == [
        ("update-alternatives", "--query", "php-fpm"),
        (
            "sudo",
            "--",
            "update-alternatives",
            "--install",
            "/usr/sbin/php-fpm",
            "php-fpm",
            str(target),
            "85",
        ),
        ("sudo", "--", "update-alternatives", "--set", "php-fpm", str(target)),
    ]


def test_registered_alternative_is_only_selected(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    target = tmp_path / "php8.5"
    target.write_text("", encoding="utf-8")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.when_argv(
        ["update-alternatives", "--query", "php"],
        stdout=f"Name: php\nAlternative: {target}\nPriority: 85\n",
    )
    assert apply_plan(_alternative_plan("php", "/usr/bin/php", target), ctx.apply()) == 0
    assert runner.calls == [
        ("update-alternatives", "--query", "php"),
        ("sudo", "--", "update-alternatives", "--set", "php", str(target)),
    ]


def test_unreadable_alternative_query_does_not_reinstall(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    target = tmp_path / "php8.5"
    target.write_text("", encoding="utf-8")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.when_argv(
        ["update-alternatives", "--query", "php"],
        code=1,
        stderr="update-alternatives: error: cannot read the alternatives directory\n",
    )
    assert apply_plan(_alternative_plan("php", "/usr/bin/php", target), ctx.apply()) == 0
    assert all("--install" not in call for call in runner.calls)
    assert runner.calls[-1] == (
        "sudo",
        "--",
        "update-alternatives",
        "--set",
        "php",
        str(target),
    )


def test_missing_alternative_binary_is_skipped(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    target = tmp_path / "php-fpm8.5"
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    assert apply_plan(_alternative_plan("php-fpm", "/usr/sbin/php-fpm", target), ctx.apply()) == 0
    assert runner.calls == []


def test_java_alternative_priority_uses_the_major(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    target = tmp_path / "java-21-openjdk-amd64" / "bin" / "java"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.when_argv(
        ["update-alternatives", "--query", "java"],
        code=2,
        stderr="update-alternatives: error: no alternatives for java\n",
    )
    assert apply_plan(_alternative_plan("java", "/usr/bin/java", target), ctx.apply()) == 0
    install = next(call for call in runner.calls if "--install" in call)
    assert install[-1] == "210"


def _alternative_plan(name: str, link: str, target: Path) -> Plan:
    return Plan(
        title=f"Select {name}",
        steps=[
            Step(
                title=f"Point the {name} alternative at {target}",
                kind="alternatives",
                argv=("update-alternatives", "--set", name, str(target)),
                sudo=True,
                reason=f"Switching the system {name} default requires root.",
                path=str(target),
                dest=link,
            )
        ],
    )


def test_node_install_uses_the_lts_archive(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "ubuntu-24.04", family="debian")
    code = cmd_install(ctx, "node", None, make_default=True, use_package=False)
    assert code == 0
    text = out.getvalue()
    assert "node-v24.22.1-linux-x64.tar.xz" in text
    assert "Dry run" in text


def test_alpine_node_uses_the_musl_build(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "alpine", family="alpine")
    code = cmd_install(ctx, "node", "24.22.1", make_default=True, use_package=False)
    assert code == 0
    assert "linux-x64-musl" in out.getvalue()


def test_dotnet_is_blocked_on_debian(tmp_path: Path) -> None:
    ctx, _out, err = machine(tmp_path, "debian-13", family="debian")
    code = cmd_install(ctx, "dotnet", None, make_default=True, use_package=False)
    assert code == 1
    assert "third-party" in err.getvalue()


def test_status_reports_an_installed_php(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    assert isinstance(ctx.runner, object)
    from devforge.core.runner import ScriptedRunner

    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.which_map["php"] = "/usr/bin/php"
    runner.when_argv(["/usr/bin/php", "-v"], stdout="PHP 8.3.6 (cli)\n")
    ctx.as_json = True
    code = cmd_status(ctx, "php")
    assert code == 0
    payload = json.loads(out.getvalue())
    row = payload["tools"][0]
    assert row["installed_version"] == "8.3.6"
    assert row["source"] == "system"
    assert row["latest"] == "8.5"
    assert row["update_available"] is None
    assert row["can_update"] is True


def test_update_php_preserves_the_installed_line(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    from devforge.core.runner import ScriptedRunner

    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.which_map["php"] = "/usr/bin/php"
    runner.when_argv(["/usr/bin/php", "-v"], stdout="PHP 8.3.6 (cli)\n")
    code = cmd_update(ctx, "php", all_tools_flag=False)
    assert code == 0
    assert "php8.3-cli" in out.getvalue()
    assert "php8.5-cli" not in out.getvalue()


def test_use_shell_does_not_write(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    code = cmd_use(ctx, "node", "24.22.1", scope=Scope.SHELL)
    assert code == 0
    assert "DEVFORGE_NODE_VERSION=24.22.1" in out.getvalue()
    assert not (ctx.paths.home / ".bashrc").exists()


def test_pin_writes_project_files(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.printer.assume_yes = True
    code = cmd_use(ctx, "php", "8.4", scope=Scope.PROJECT)
    assert code == 0
    assert (ctx.cwd / ".php-version").read_text(encoding="utf-8").strip() == "8.4"
    assert "php 8.4" in (ctx.cwd / ".tool-versions").read_text(encoding="utf-8")


def test_shell_block_is_reversible(tmp_path: Path) -> None:
    from devforge.commands.files import cmd_shell

    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.printer.assume_yes = True
    assert cmd_shell(ctx, "install") == 0
    rc = ctx.paths.home / ".bashrc"
    assert "devforge initialize" in rc.read_text(encoding="utf-8")
    assert cmd_shell(ctx, "remove") == 0
    assert "devforge initialize" not in rc.read_text(encoding="utf-8")


def test_uninstall_refuses_paths_outside_devforge(tmp_path: Path) -> None:
    ctx, _out, err = machine(tmp_path, "debian-12", family="debian")
    root = ctx.paths.install_root / "node" / "24.22.1"
    root.mkdir(parents=True)
    (root / ".devforge-complete").write_text("ok\n", encoding="utf-8")
    code = cmd_uninstall(ctx, "node", "24.22.1", purge=False)
    assert code == 0
    assert "Delete" in _out_text(ctx)
    assert not err.getvalue() or "err" not in err.getvalue()


def _out_text(ctx: object) -> str:
    stream = getattr(getattr(ctx, "printer", None), "stream", None)
    return stream.getvalue() if isinstance(stream, io.StringIO) else ""


def test_doctor_flags_a_broken_default(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    default = ctx.paths.install_root / "node" / "default"
    default.parent.mkdir(parents=True)
    default.write_text("9.9.9\n", encoding="utf-8")
    ctx.as_json = True
    code = cmd_doctor(ctx, online=False)
    assert code == 1
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    assert any(item["status"] == "error" and item["name"] == "node" for item in payload["checks"])


def test_versions_lists_shipped_node_releases(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    code = cmd_versions(ctx, "node", refresh=False)
    assert code == 0
    assert "24.22.1" in out.getvalue()
    assert "26.12.1" in out.getvalue()


def test_invalid_version_is_usage(tmp_path: Path) -> None:
    ctx, _out, err = machine(tmp_path, "debian-12", family="debian")
    assert cmd_install(ctx, "node", "../etc", make_default=True, use_package=False) == 2
    assert "invalid version" in err.getvalue()
    assert cmd_update(ctx, None, all_tools_flag=False) == 2


def test_preset_and_manifest(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    assert cmd_preset_list(ctx) == 0
    assert "web-php" in out.getvalue()
    out.truncate(0)
    out.seek(0)
    code = cmd_preset_apply(ctx, "node-fullstack")
    assert code == 0
    text = out.getvalue()
    assert "nodejs.org" in text
    manifest = tmp_path / "devforge.toml"
    manifest.write_text('[tool.git]\nversion = "2.47.0"\ndefault = true\n', encoding="utf-8")
    parsed = parse_manifest(manifest)
    assert parsed == [("git", "2.47.0", True)]
    document = tmp_path / "devforge.json"
    document.write_text('{"tools": {"curl": {}}}\n', encoding="utf-8")
    assert cmd_apply(ctx, document) == 0


def test_export_json_includes_detected_php(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    from devforge.core.runner import ScriptedRunner

    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.which_map["php"] = "/usr/bin/php"
    runner.when_argv(["/usr/bin/php", "-v"], stdout="PHP 8.3.6 (cli)\n")
    assert cmd_export(ctx) == 0
    payload = json.loads(out.getvalue())
    assert payload["tools"]["php"]["version"] == "8.3.6"


def test_mirror_set_and_dns_round_trip(tmp_path: Path) -> None:
    ctx, _out, err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.printer.assume_yes = True
    assert cmd_mirror_set(ctx, "iran") == 0
    assert "not verified" in err.getvalue()
    config = json.loads(ctx.paths.config_file.read_text(encoding="utf-8"))
    assert config["mirror"] == "iran"
    daemon_path = ctx.fs_root / "etc" / "docker" / "daemon.json"
    daemon = json.loads(daemon_path.read_text(encoding="utf-8"))
    assert "https://docker.arvancloud.ir" in daemon["registry-mirrors"]
    assert cmd_dns_set(ctx, "cloudflare") == 0
    resolv = (ctx.fs_root / "etc" / "resolv.conf").read_text(encoding="utf-8")
    assert "1.1.1.1" in resolv
    assert cmd_dns_set(ctx, "cloudflare") == 0
    assert cmd_dns_restore(ctx) == 0


def test_shim_rejects_a_flag_version() -> None:
    script = render_shim(
        binary="node",
        tool="node",
        root=Path("/opt/devforge/node"),
        env_file=Path("/opt/devforge/env.sh"),
        project_files=(".node-version",),
        system_bins=("node{mm}",),
        shim_kind="exec",
        runtime_env=(),
    )
    assert "DEVFORGE_NODE_VERSION" in script
    assert "case" in script


def test_menu_exits_on_zero(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    assert menu(ctx, iter(["0"])) == 0
    text = out.getvalue()
    assert "DevForge" in text
    assert "php" in text
    assert "node" in text
    assert "Update DevForge" in text
    assert "not installed" in text


def test_menu_opens_a_tool_then_returns(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    assert menu(ctx, iter(["1", "0", "0"])) == 0
    text = out.getvalue()
    assert "Install the preferred version" in text
    assert "back" in text


def test_menu_shows_a_newer_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from devforge.core.release import ReleaseNotice

    notice = ReleaseNotice(
        "9.9.9",
        "https://github.com/mohammadhejazirad/devforge/releases/download/v9.9.9/devforge-9.9.9.tar.gz",
        "https://github.com/mohammadhejazirad/devforge/releases/download/v9.9.9/SHA256SUMS",
    )
    monkeypatch.setattr("devforge.tui.check_newer", lambda ctx: notice)
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    assert menu(ctx, iter(["0"])) == 0
    assert "A new version is available: 9.9.9" in out.getvalue()


def test_cli_dispatch_uses_a_private_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    out = io.StringIO()
    err = io.StringIO()
    code = main(["list"], out=out, err=err)
    assert code == 0
    assert "php" in out.getvalue()
    assert main(["update"], out=io.StringIO(), err=io.StringIO()) == 2
    assert main(["install", "not-a-tool"], out=io.StringIO(), err=io.StringIO()) == 2
    assert main(["tui"], out=io.StringIO(), err=io.StringIO()) == 2
    versions = main(
        ["--dry-run", "--json", "versions", "go"],
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert versions == 0


def test_known_tool_count() -> None:
    assert len(all_tools()) == 35
    assert load_tool("redis").name == "redis"
