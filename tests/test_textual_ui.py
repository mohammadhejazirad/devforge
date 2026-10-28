"""Headless Textual navigation and confirmation tests; no host mutations."""

from __future__ import annotations

import asyncio

from textual.pilot import Pilot
from textual.widgets import OptionList, Select

from devforge.core.runner import ScriptedRunner
from devforge.textual_ui import DevForgeApp, PromptDialog
from tests.support import machine


async def wait_prompt(app: DevForgeApp, pilot: Pilot[None]) -> None:
    for _ in range(50):
        await pilot.pause(0.02)
        if isinstance(app.screen, PromptDialog) and app.screen.focused is not None:
            return
    raise AssertionError("No prompt appeared")


def test_textual_navigation_theme_and_terminal_choices(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")

    async def scenario() -> None:
        app = DevForgeApp(ctx)
        async with app.run_test(size=(110, 36)) as pilot:
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            await pilot.pause()
            navigation = app.query_one("#navigation", OptionList)
            assert navigation.option_count >= 8
            app.show_studio()
            assert app.query_one("#choices", OptionList).option_count == 17
            app.query_one("#ui-theme", Select).value = "nord"
            await pilot.pause()
            assert app.theme == "nord"
            app.route, app.category = "category", "database"
            app.load_category("database")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            assert app.query_one("#choices", OptionList).option_count == 5
            app.route, app.tool_name = "tool", "mysql"
            app.load_tool("mysql")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            choices = app.query_one("#choices", OptionList)
            assert choices.get_option("backups")
            await pilot.press("escape")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            assert app.route == "category"

    asyncio.run(scenario())


def test_textual_cancel_does_not_apply_terminal_changes(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.assume_yes = False
    assert isinstance(ctx.runner, ScriptedRunner)
    ctx.runner.which_map["zsh"] = "/usr/bin/zsh"

    async def scenario() -> None:
        app = DevForgeApp(ctx)
        async with app.run_test(size=(100, 36)) as pilot:
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            app.show_studio()
            app.start_operation("terminal", "zsh-theme", "minimal")
            await wait_prompt(app, pilot)
            assert app.focused is not None
            assert app.focused.id == "cancel"
            assert isinstance(app.screen, PromptDialog)
            assert app.screen.reply.confirm
            assert await pilot.click("#cancel")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            assert not app.busy
            assert not (ctx.paths.home / ".zshrc").exists()
            assert not (ctx.paths.config / "terminal.json").exists()

    asyncio.run(scenario())


def test_textual_accept_applies_only_selected_theme(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.assume_yes = False
    assert isinstance(ctx.runner, ScriptedRunner)
    ctx.runner.which_map["zsh"] = "/usr/bin/zsh"

    async def scenario() -> None:
        app = DevForgeApp(ctx)
        async with app.run_test(size=(100, 38)) as pilot:
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            app.show_studio()
            app.start_operation("terminal", "zsh-theme", "minimal")
            await wait_prompt(app, pilot)
            assert await pilot.click("#accept")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            content = (ctx.paths.home / ".zshrc").read_text()
            assert "PROMPT=" in content
            assert "starship" not in content and "source " not in content
            assert not (ctx.paths.data / "terminal/plugins").exists()

    asyncio.run(scenario())


def test_existing_database_submenus_use_cancellable_textual_dialogs(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)

    async def scenario() -> None:
        app = DevForgeApp(ctx)
        async with app.run_test(size=(100, 38)) as pilot:
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            app.start_operation("tool", "backups", "mysql")
            await wait_prompt(app, pilot)
            assert isinstance(app.screen, PromptDialog)
            assert "mysql / Backups" in app.screen.reply.body
            assert app.screen.query_one("#dialog-options", OptionList).get_option("2")
            await pilot.press("escape")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            assert not (ctx.paths.state / "backups").exists()

    asyncio.run(scenario())


def test_textual_small_ssh_terminal_still_navigates(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian")

    async def scenario() -> None:
        app = DevForgeApp(ctx)
        async with app.run_test(size=(80, 24)) as pilot:
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            app.show_studio()
            await pilot.press("tab", "down", "down")
            assert app.query_one("#choices", OptionList).option_count == 17

    asyncio.run(scenario())


def test_native_privileged_runner_releases_terminal_without_capturing_password(monkeypatch):
    import subprocess
    from contextlib import contextmanager
    from types import SimpleNamespace
    from typing import cast

    from devforge.core.runner import SubprocessRunner
    from devforge.textual_ui import TerminalRunner

    events = []

    class NativeApp:
        @contextmanager
        def suspend(self):
            events.append("suspend")
            yield
            events.append("resume")

    def run(argv, **kwargs):
        assert events == ["suspend"]
        assert "capture_output" not in kwargs and "input" not in kwargs
        assert "stdin" not in kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    runner = TerminalRunner(cast(DevForgeApp, NativeApp()), SubprocessRunner())
    assert runner.run(["sudo", "--", "true"]).code == 0
    assert events == ["suspend", "resume"]


def test_small_terminal_dialog_keeps_cancel_button_reachable(tmp_path):
    ctx, _, _ = machine(tmp_path, "debian-12", family="debian", dry_run=False)

    async def scenario() -> None:
        app = DevForgeApp(ctx)
        async with app.run_test(size=(80, 24)) as pilot:
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            app.start_operation("tool", "backups", "mysql")
            await wait_prompt(app, pilot)
            assert await pilot.click("#cancel")
            await asyncio.wait_for(app.workers.wait_for_complete(), timeout=5)
            assert not app.busy

    asyncio.run(scenario())
