"""Release-line updates, dependencies, and executable archive installations."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from devforge.context import Context
from devforge.core.archive import ArchiveError, safe_extract
from devforge.core.net import MemoryFetcher
from devforge.core.pkgmgr import parse_query
from devforge.core.plan import apply_plan
from devforge.core.runner import ScriptedRunner
from devforge.core.shell import rc_targets, render_shim
from devforge.core.versioning import is_valid_version, newest_in_line
from devforge.tools.base import Scope
from devforge.tools.engine import _managed_versions
from devforge.tools.managed import load_tool
from tests.support import machine


def _installed(ctx: Context, binary: str, version: str, output: str = "") -> ScriptedRunner:
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.which_map[binary] = f"/usr/bin/{binary}"
    args = ["-v"] if binary == "php" else ["--version"]
    runner.when_argv([f"/usr/bin/{binary}", *args], stdout=output or f"v{version}\n")
    return runner


@pytest.mark.parametrize(
    "tool,current,expected",
    [
        ("node", "22.1.0", "22.9.1"),
        ("php", "8.5.1", "8.5.3"),
        ("python", "3.13.1", "3.13.9"),
        ("go", "1.26.1", "1.26.4"),
    ],
)
def test_newest_release_preserves_compatibility_line(tool, current, expected):
    assert (
        newest_in_line(
            tool, current, [expected, "26.0.0", "8.6.0", "3.14.0", "1.27.0", expected + "-rc1"]
        )
        == expected
    )


def test_node_update_refreshes_without_switching_major(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.offline = False
    _installed(ctx, "node", "22.1.0")
    url = "https://nodejs.org/dist/index.json"
    ctx.fetcher = MemoryFetcher(
        {
            url: json.dumps(
                [
                    {"version": "v26.1.0", "lts": False},
                    {"version": "v24.1.0", "lts": "Example"},
                    {"version": "v22.9.1", "lts": "Example"},
                    {"version": "v22.10.0-rc1", "lts": False},
                ]
            ).encode()
        }
    )
    plan = load_tool("node").update(ctx)
    downloads = [step for step in plan.steps if step.kind == "download"]
    assert len(downloads) == 1
    assert "/v22.9.1/" in downloads[0].urls[0]
    assert ctx.fetcher.urls == [url]
    assert downloads[0].checksum_url.endswith("/v22.9.1/SHASUMS256.txt")


def test_refresh_failure_does_not_claim_up_to_date(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.offline = False
    ctx.fetcher = MemoryFetcher()
    _installed(ctx, "node", "22.1.0")
    plan = load_tool("node").update(ctx)
    assert plan.blocked
    assert not plan.steps


def test_partial_node_install_resolves_to_full_version(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    plan = load_tool("node").install(ctx, "22", make_default=True)
    assert not plan.blocked
    assert any("/v22.23.4/" in url for step in plan.steps for url in step.urls)


def test_php_patch_upgrade_refreshes_then_upgrades_same_line(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = _installed(ctx, "php", "8.5.1", "PHP 8.5.1 (cli)\n")
    for package in ("php8.5-cli", "php8.5-fpm"):
        runner.when_argv(
            ["apt-cache", "policy", package], stdout="Installed: 8.5.1-1\nCandidate: 8.5.3-1\n"
        )
    plan = load_tool("php").update(ctx)
    assert apply_plan(plan, ctx.apply()) == 0
    refresh_at = runner.calls.index(("sudo", "--", "apt-get", "update"))
    query_at = runner.calls.index(("apt-cache", "policy", "php8.5-cli"))
    assert refresh_at < query_at
    assert runner.calls[-1] == (
        "sudo",
        "--",
        "apt-get",
        "install",
        "-y",
        "--only-upgrade",
        "--no-remove",
        "php8.5-cli",
        "php8.5-fpm",
    )


def test_package_update_refuses_crossing_php_line(tmp_path):
    ctx, _, _ = machine(tmp_path, "arch", family="arch", dry_run=False)
    runner = _installed(ctx, "php", "8.5.1", "PHP 8.5.1\n")
    runner.when_argv(["pacman", "-Si", "php"], stdout="Version : 8.6.0-1\n")
    assert apply_plan(load_tool("php").update(ctx), ctx.apply()) == 1
    assert not any("--needed" in call for call in runner.calls)


def test_security_revision_is_retained_and_detected(tmp_path):
    assert parse_query("apt", "Installed: 2:8.5.1-1\nCandidate: 2:8.5.1-2\n") == (
        "2:8.5.1-1",
        "2:8.5.1-2",
    )
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    runner = _installed(ctx, "php", "8.5.1", "PHP 8.5.1\n")
    runner.when_argv(
        ["apt-cache", "policy", "php8.5-cli"], stdout="Installed: 2:8.5.1-1\nCandidate: 2:8.5.1-2\n"
    )
    status = load_tool("php").status(ctx)
    assert status.update_available is True
    assert status.update_target == "2:8.5.1-2"
    assert ("dpkg", "--compare-versions", "2:8.5.1-2", "gt", "2:8.5.1-1") in runner.calls


def test_status_distinguishes_new_major_from_update(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    _installed(ctx, "node", "22.23.4")
    status = load_tool("node").status(ctx)
    assert status.update_available is False
    assert status.new_release_available is True
    assert status.update_target == "22.23.4"


def test_missing_npm_installs_node_automatically(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    plan = load_tool("npm").install(ctx, None, make_default=True)
    assert not plan.blocked
    assert any("nodejs.org" in url for step in plan.steps for url in step.urls)


def test_composer_installs_php_dependency(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    plan = load_tool("composer").install(ctx, None, make_default=True)
    assert not plan.blocked
    assert any("php-cli" in step.argv for step in plan.steps)


def test_npm_update_retains_major(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    _installed(ctx, "npm", "10.1.0", "10.1.0\n")
    plan = load_tool("npm").update(ctx)
    assert plan.steps[0].argv[-1] == "npm@^10"


def test_incomplete_installs_are_not_selectable(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    root = ctx.paths.install_root / "node" / "22.0.0"
    root.mkdir(parents=True)
    assert not _managed_versions(load_tool("node").spec, ctx)
    assert load_tool("node").use(ctx, "22", scope=Scope.GLOBAL).blocked
    (root / ".devforge-complete").write_text("ok\n")
    plan = load_tool("node").use(ctx, "22", scope=Scope.GLOBAL)
    assert not plan.blocked
    assert plan.steps[0].content == "22.0.0\n"


def _tar(path: Path, *, link: str) -> None:
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo("node")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for name, body in [
            ("node/bin/node", b"#!/bin/sh\necho node-ok\n"),
            ("node/lib/npm.js", b"#!/bin/sh\necho npm-ok\n"),
        ]:
            member = tarfile.TarInfo(name)
            member.size = len(body)
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(body))
        symlink = tarfile.TarInfo("node/bin/npm")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = link
        archive.addfile(symlink)


def test_node_style_archive_links_install_and_execute(tmp_path):
    archive = tmp_path / "node.tar.gz"
    _tar(archive, link="../lib/npm.js")
    target = tmp_path / "install"
    safe_extract(archive, target, fmt="tar.gz")
    assert (target / "bin/npm").is_symlink()
    assert subprocess.check_output([str(target / "bin/npm")], text=True) == "npm-ok\n"


@pytest.mark.parametrize("link", ["../../../outside", "/etc/passwd", "../bin/npm"])
def test_bad_archive_links_leave_no_partial_install(tmp_path, link):
    archive = tmp_path / "node.tar.gz"
    _tar(archive, link=link)
    target = tmp_path / "install"
    with pytest.raises(ArchiveError):
        safe_extract(archive, target, fmt="tar.gz")
    assert not target.exists()


def test_unversioned_package_shim_falls_back_without_recursion(tmp_path):
    system = tmp_path / "system"
    shims = tmp_path / "shims"
    system.mkdir()
    shims.mkdir()
    binary = system / "php"
    binary.write_text("#!/bin/sh\necho system-php\n")
    binary.chmod(0o755)
    shim = shims / "php"
    shim.write_text(
        render_shim(
            binary="php",
            tool="php",
            root=tmp_path / "tools/php",
            env_file=tmp_path / "env.sh",
            project_files=(),
            system_bins=("php{mm}",),
            shim_kind="exec",
            runtime_env=(),
        )
    )
    shim.chmod(0o755)
    result = subprocess.run(
        [str(shim)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={"PATH": f"{shims}:{system}:/usr/bin:/bin"},
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "system-php\n"


def test_partial_project_pin_executes_latest_matching_managed_install(tmp_path):
    root = tmp_path / "node"
    for version in ("22.9.0", "22.10.0", "24.0.0"):
        prefix = root / version
        (prefix / "bin").mkdir(parents=True)
        (prefix / ".devforge-complete").write_text("ok\n")
        (prefix / "bin/node").write_text(f"#!/bin/sh\necho {version}\n")
        (prefix / "bin/node").chmod(0o755)
    (tmp_path / ".node-version").write_text("22\n")
    shim = tmp_path / "node-shim"
    shim.write_text(
        render_shim(
            binary="node",
            tool="node",
            root=root,
            env_file=tmp_path / "env.sh",
            project_files=(".node-version",),
            system_bins=(),
            shim_kind="exec",
            runtime_env=(),
        )
    )
    shim.chmod(0o755)
    env = os.environ.copy()
    env.pop("DEVFORGE_NODE_VERSION", None)
    assert subprocess.check_output([str(shim)], cwd=tmp_path, env=env, text=True) == "22.10.0\n"


def test_current_shell_is_configured_even_when_another_rc_exists(tmp_path):
    (tmp_path / ".bashrc").write_text("# existing\n")
    assert ("sh", tmp_path / ".zshrc") in rc_targets(tmp_path, "/bin/zsh")


def test_trailing_newline_is_not_a_safe_version():
    assert not is_valid_version("8.5\n")


def test_rpm_security_revisions_are_retained():
    assert parse_query(
        "dnf",
        """Installed Packages
Name : php-cli
Epoch : 1
Version : 8.5.1
Release : 1.fc44
Available Packages
Name : php-cli
Epoch : 1
Version : 8.5.1
Release : 2.fc44
""",
    ) == ("1:8.5.1-1.fc44", "1:8.5.1-2.fc44")


def test_node_refresh_sorts_releases_and_ignores_prereleases():
    from devforge.tools.catalog import parse_refresh

    versions, lts, latest, _ = parse_refresh(
        "node-index",
        json.dumps(
            [
                {"version": "v22.1.0", "lts": "Example"},
                {"version": "v28.0.0-rc1", "lts": False},
                {"version": "v24.2.0", "lts": "Example"},
                {"version": "v26.1.0", "lts": False},
            ]
        ).encode(),
    )
    assert versions == ["26.1.0", "24.2.0", "22.1.0"]
    assert lts == "24.2.0"
    assert latest == "26.1.0"


def test_update_all_reports_blocked_tools_as_failure(tmp_path, monkeypatch):
    from devforge.commands.lifecycle import cmd_update

    ctx, out, _ = machine(tmp_path, "debian-12", family="debian")
    _installed(ctx, "pyenv", "2.6.0", "pyenv 2.6.0\n")
    monkeypatch.setattr("devforge.commands.lifecycle.all_tools", lambda: [load_tool("pyenv")])
    ctx.as_json = True
    assert cmd_update(ctx, None, all_tools_flag=True) == 1
    assert json.loads(out.getvalue())["blocked"]
