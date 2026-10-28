"""Opt-in shell configuration without executing a login shell or reading history."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from devforge.context import Context
from devforge.core.net import MemoryFetcher, sha256_bytes
from devforge.core.plan import apply_plan
from devforge.core.runner import ScriptedRunner
from devforge.core.state import save_json
from devforge.core.terminal import BEGIN, END, PLUGINS, terminal_plan
from devforge.tools.managed import load_tool
from tests.support import machine


def zsh(ctx: Context) -> ScriptedRunner:
    assert isinstance(ctx.runner, ScriptedRunner)
    ctx.runner.which_map["zsh"] = "/usr/bin/zsh"
    return ctx.runner


@pytest.mark.parametrize(
    "fixture,family,manager",
    [
        ("ubuntu-24.04", "debian", "apt-get"),
        ("fedora", "rhel", "dnf"),
        ("arch", "arch", "pacman"),
        ("opensuse-leap", "suse", "zypper"),
        ("alpine", "alpine", "apk"),
    ],
)
def test_zsh_native_packages_and_portable_starship_plan(tmp_path, fixture, family, manager):
    ctx, _, _ = machine(tmp_path, fixture, family=family)
    plan = load_tool("zsh").install(ctx, None, make_default=True)
    assert not plan.blocked
    assert any(step.argv and step.argv[0] == manager and "zsh" in step.argv for step in plan.steps)
    assert not any(step.argv and step.argv[0] == "chsh" for step in plan.steps)
    starship = load_tool("starship").install(ctx, "1.27.0", make_default=True)
    assert not starship.blocked
    download = next(step for step in starship.steps if step.kind == "download")
    assert "unknown-linux-musl" in download.urls[0]
    assert len(download.sha256) == 64


def test_missing_zsh_does_not_install_other_components(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    for action in ("autosuggestions", "highlighting", "zsh-theme", "starship-theme"):
        plan = terminal_plan(ctx, action, "minimal")
        assert plan.blocked and not plan.steps


def test_theme_is_individual_preserves_rc_and_is_reversible(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    zsh(ctx)
    rc = ctx.paths.home / ".zshrc"
    original = "export KEEP_ME=yes\n# my existing configuration\n"
    rc.write_text(original)
    assert apply_plan(terminal_plan(ctx, "zsh-theme", "midnight"), ctx.apply()) == 0
    configured = rc.read_text()
    assert original.strip() in configured
    assert "PROMPT=" in configured and configured.count(BEGIN) == 1
    assert "starship" not in configured and "source " not in configured
    assert Path(str(rc) + ".devforge.bak").read_text() == original
    assert apply_plan(terminal_plan(ctx, "zsh-theme", "minimal"), ctx.apply()) == 0
    assert rc.read_text().count(BEGIN) == 1
    assert apply_plan(terminal_plan(ctx, "remove"), ctx.apply()) == 0
    assert BEGIN not in rc.read_text() and "KEEP_ME=yes" in rc.read_text()


def test_starship_theme_does_not_overwrite_user_starship_file(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = zsh(ctx)
    assert terminal_plan(ctx, "starship-theme", "server").blocked
    runner.which_map["starship"] = "/usr/bin/starship"
    own_config = ctx.paths.home / ".config/starship.toml"
    own_config.parent.mkdir()
    own_config.write_text("# user original\n")
    plan = terminal_plan(ctx, "starship-theme", "server")
    assert not any(step.kind == "download" for step in plan.steps)
    assert apply_plan(plan, ctx.apply()) == 0
    assert own_config.read_text() == "# user original\n"
    assert "show_always = true" in (ctx.paths.config / "starship.toml").read_text()
    assert "STARSHIP_CONFIG=" in (ctx.paths.home / ".zshrc").read_text()
    assert "syntax-highlighting" not in (ctx.paths.home / ".zshrc").read_text()


def test_pinned_plugin_extracts_only_selected_component_and_loads_last(tmp_path, monkeypatch):
    import devforge.core.terminal as module

    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    zsh(ctx)
    repository, version, filename, _ = PLUGINS["highlighting"]
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as archive:
        payload = b"# plugin fixture\n"
        info = tarfile.TarInfo(f"plugin/{filename}")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    archive_bytes = packed.getvalue()
    monkeypatch.setitem(
        module.PLUGINS, "highlighting", (repository, version, filename, sha256_bytes(archive_bytes))
    )
    url = f"https://codeload.github.com/zsh-users/{repository}/tar.gz/refs/tags/{version}"
    ctx.fetcher = MemoryFetcher({url: archive_bytes})
    assert apply_plan(terminal_plan(ctx, "highlighting"), ctx.apply()) == 0
    rc = ctx.paths.home / ".zshrc"
    assert "zsh-syntax-highlighting.zsh" in rc.read_text()
    assert "autosuggest" not in rc.read_text() and "PROMPT=" not in rc.read_text()
    assert apply_plan(terminal_plan(ctx, "zsh-theme", "minimal"), ctx.apply()) == 0
    content = rc.read_text()
    assert content.index("PROMPT=") < content.index("source ")
    repeated = terminal_plan(ctx, "highlighting")
    assert not any(step.kind == "download" for step in repeated.steps)
    assert apply_plan(terminal_plan(ctx, "remove-highlighting"), ctx.apply()) == 0
    assert "source " not in rc.read_text()
    assert not (ctx.paths.data / "terminal/plugins" / repository / version).exists()


def test_history_plugin_is_local_only_and_no_other_component_selected(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    zsh(ctx)
    plan = terminal_plan(ctx, "autosuggestions")
    rc = next(step.content for step in plan.steps if step.policy == "rc")
    assert "ZSH_AUTOSUGGEST_STRATEGY=(history)" in rc
    assert "zsh-syntax-highlighting" not in rc and "starship" not in rc
    assert "chsh" not in str(plan.to_dict())
    assert apply_plan(plan, ctx.apply()) == 0
    assert not (ctx.paths.home / ".zshrc").exists()


@pytest.mark.parametrize(
    "markers", [BEGIN, END, END + "\n" + BEGIN, BEGIN + "\n" + BEGIN + "\n" + END]
)
def test_malformed_block_does_not_modify_anything(tmp_path, markers):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    zsh(ctx)
    rc = ctx.paths.home / ".zshrc"
    rc.write_text(markers)
    plan = terminal_plan(ctx, "zsh-theme", "minimal")
    assert plan.blocked and not plan.steps
    assert rc.read_text() == markers


def test_sudo_user_and_symlink_rc_are_not_guessed_or_replaced(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    zsh(ctx)
    ctx.euid = 0
    ctx.env = {**ctx.env, "SUDO_USER": "someone"}
    assert terminal_plan(ctx, "zsh-theme", "minimal").blocked
    ctx.euid = 1000
    target = ctx.paths.home / "dotfiles.zsh"
    target.write_text("keep\n")
    (ctx.paths.home / ".zshrc").symlink_to(target)
    assert terminal_plan(ctx, "zsh-theme", "minimal").blocked
    assert target.read_text() == "keep\n"


def test_zdotdir_is_respected_and_external_paths_are_refused(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    zsh(ctx)
    ctx.env = {**ctx.env, "ZDOTDIR": str(ctx.paths.home / ".config/zsh")}
    assert apply_plan(terminal_plan(ctx, "zsh-theme", "minimal"), ctx.apply()) == 0
    assert not (ctx.paths.home / ".zshrc").exists()
    assert (ctx.paths.home / ".config/zsh/.zshrc").is_file()
    ctx.env = {**ctx.env, "ZDOTDIR": str(tmp_path / "other")}
    assert terminal_plan(ctx, "remove").blocked


def test_default_shell_requires_explicit_choice_registered_shell_and_chsh(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    runner = zsh(ctx)
    (ctx.fs_root / "etc/shells").write_text("/bin/bash\n/usr/bin/zsh\n")
    assert terminal_plan(ctx, "default-shell").blocked
    runner.which_map["chsh"] = "/usr/bin/chsh"
    plan = terminal_plan(ctx, "default-shell")
    assert plan.steps[0].argv == ("chsh", "-s", "/usr/bin/zsh")
    assert len(plan.steps) == 1 and not plan.steps[0].sudo
    assert not any("chsh" in step.argv for step in terminal_plan(ctx, "zsh-theme", "minimal").steps)


def test_uninstall_active_zsh_is_blocked(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    ctx.env = {**ctx.env, "SHELL": "/usr/bin/zsh"}
    assert load_tool("zsh").uninstall(ctx, None, purge=False).blocked


def test_unknown_theme_does_not_write_partial_settings(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    zsh(ctx)
    for action in ("zsh-theme", "starship-theme"):
        assert terminal_plan(ctx, action, "malicious;whoami").blocked
    assert not ctx.paths.config.exists()


def test_stale_zdotdir_setting_does_not_leave_hidden_managed_blocks(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    zsh(ctx)
    save_json(ctx.paths.config / "terminal.json", {"rc_path": "/different/.zshrc"})
    assert terminal_plan(ctx, "zsh-theme", "minimal").blocked


def test_native_zsh_themes_pass_syntax_check(tmp_path):
    import shutil

    binary = shutil.which("zsh")
    if not binary:
        pytest.skip("Zsh syntax checker is not installed on this test host")
    assert binary is not None
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    zsh(ctx)
    for theme in ("minimal", "midnight", "classic"):
        assert apply_plan(terminal_plan(ctx, "zsh-theme", theme), ctx.apply()) == 0
        result = subprocess.run([binary, "-n", str(ctx.paths.home / ".zshrc")], capture_output=True)
        assert result.returncode == 0, result.stderr
    assert json.loads((ctx.paths.config / "terminal.json").read_text())["theme"] == "classic"


def test_starship_uninstall_removes_managed_initialization_before_binary(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    runner = zsh(ctx)
    runner.which_map["starship"] = "/usr/bin/starship"
    assert apply_plan(terminal_plan(ctx, "starship-theme", "minimal"), ctx.apply()) == 0
    root = ctx.paths.install_root / "starship"
    version = root / "1.27.0"
    version.mkdir(parents=True)
    (version / ".devforge-complete").write_text("complete")
    (version / "starship").write_text("binary fixture")
    (root / "default").write_text("1.27.0")
    plan = load_tool("starship").uninstall(ctx, "1.27.0", purge=False)
    assert not plan.blocked
    assert apply_plan(plan, ctx.apply()) == 0
    assert "init zsh" not in (ctx.paths.home / ".zshrc").read_text()
    assert not version.exists()


def test_login_shell_protection_uses_account_database_not_only_environment(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")
    (ctx.fs_root / "etc/passwd").write_text(f"dev:x:{ctx.euid}:1000::/home/dev:/bin/zsh\n")
    ctx.env = {**ctx.env, "SHELL": "/bin/bash"}
    assert load_tool("zsh").uninstall(ctx, None, purge=False).blocked
