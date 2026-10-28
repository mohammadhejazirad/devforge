"""Textual front end over the same plan engine used by CLI and plain menus."""

from __future__ import annotations

import io
import os
import re
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from threading import Event
from typing import BinaryIO, ClassVar, Optional

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    OptionList,
    RichLog,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from devforge import __version__
from devforge.commands.terminal import OPTIONS as TERMINAL_OPTIONS
from devforge.commands.terminal import cmd_terminal
from devforge.context import Context
from devforge.core.log import redact
from devforge.core.release import check_newer
from devforge.core.runner import Runner, RunResult, SubprocessRunner
from devforge.tools.managed import all_tools, load_tool
from devforge.tui import _ACTIONS, _CATEGORIES, _run_tool_action, _tool_options
from devforge.ui import Printer


@dataclass
class Reply:
    body: str
    confirm: bool = False
    ready: Event = field(default_factory=Event)
    value: str | None = None


class PromptDialog(ModalScreen[Optional[str]]):
    """A cancellable prompt; confirmation always focuses the safe button."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]
    CSS = """
    PromptDialog { align: center middle; background: $background 70%; }
    #dialog { width: 85%; max-width: 110; height: 85%; max-height: 90%;
              border: round $accent; background: $surface; padding: 1 2; }
    #dialog-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #dialog-body { height: 1fr; min-height: 1; max-height: 45vh; margin-bottom: 1;
                   border: none; padding: 0; }
    #dialog-options { height: 1fr; min-height: 1; max-height: 24vh; margin-bottom: 1;
                      border: none; padding: 0; }
    #dialog-buttons { height: 3; align: right middle; }
    #dialog-buttons Button { margin-left: 1; }
    """

    def __init__(self, reply: Reply) -> None:
        super().__init__()
        self.reply = reply

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(
                "Review plan before applying" if self.reply.confirm else "Choose an option",
                id="dialog-title",
            )
            with VerticalScroll(id="dialog-body"):
                yield Static(Text(self.reply.body))
            if not self.reply.confirm:
                matches = re.findall(r"^\s*(\d+|t)\s{2,}(.+)$", self.reply.body, re.MULTILINE)
                # Only the final displayed menu: reset when numbering restarts.
                choices: dict[str, str] = {}
                for key, label in matches:
                    if key == "1":
                        choices.clear()
                    choices[key] = label
                if choices:
                    yield OptionList(
                        *(Option(Text(label), id=key) for key, label in choices.items()),
                        id="dialog-options",
                    )
                yield Input(placeholder="Enter a value, or select an option above", id="answer")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    "Apply changes" if self.reply.confirm else "Continue",
                    variant="warning" if self.reply.confirm else "primary",
                    id="accept",
                )

    def on_mount(self) -> None:
        self.query_one("#cancel" if self.reply.confirm else "#answer").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
        elif self.reply.confirm:
            self.dismiss("y")
        else:
            self.dismiss(self.query_one("#answer", Input).value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BridgeStream(io.StringIO):
    def __init__(self, app: DevForgeApp) -> None:
        super().__init__()
        self.app = app

    def write(self, value: str) -> int:
        count = super().write(value)
        if value.strip():
            self.app.call_from_thread(self.app.append_log, value.rstrip())
        return count

    def take(self) -> str:
        value = self.getvalue()
        self.seek(0)
        self.truncate()
        return value


class DialogPrinter(Printer):
    def __init__(self, app: DevForgeApp, ctx: Context, stream: BridgeStream) -> None:
        super().__init__(
            stream=stream,
            error_stream=stream,
            color=False,
            assume_yes=ctx.assume_yes,
            dry_run=ctx.dry_run,
        )
        self.app = app
        self.buffer = stream

    def confirm(self, question: str = "Apply this plan?", *, default: bool = False) -> bool:
        if self.assume_yes:
            return True
        return self.app.ask(self.buffer.take() + "\n" + question, confirm=True) == "y"


class DialogLines(Iterator[str]):
    def __init__(self, app: DevForgeApp, stream: BridgeStream) -> None:
        self.app, self.stream = app, stream

    def __next__(self) -> str:
        response = self.app.ask(self.stream.take())
        if response is None:
            raise StopIteration
        return response


class TerminalRunner:
    """Give sudo/PAM the real terminal while Textual releases its input driver."""

    def __init__(self, app: DevForgeApp, runner: Runner) -> None:
        self.app, self.runner = app, runner

    def which(self, name: str) -> str | None:
        return self.runner.which(name)

    def stream(self, argv: Sequence[str], output: BinaryIO, *, timeout: float = 3600) -> RunResult:
        return self.runner.stream(argv, output, timeout=timeout)

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> RunResult:
        if isinstance(self.runner, SubprocessRunner) and argv[0] in {"sudo", "chsh"}:
            command_env = dict(os.environ if env is None else env)
            command_env["LC_ALL"] = "C"
            with self.app.suspend():
                try:
                    code = subprocess.run(
                        argv, check=False, timeout=timeout, env=command_env, cwd=cwd
                    ).returncode
                    result = RunResult(tuple(argv), code, "", "")
                except subprocess.TimeoutExpired:
                    result = RunResult(tuple(argv), 124, "", "Command timed out.")
                except OSError as exc:
                    result = RunResult(tuple(argv), 127, "", str(exc))
            return result
        return self.runner.run(argv, timeout=timeout, env=env, cwd=cwd)


class DevForgeApp(App[None]):
    """Browse categories on the left; manage only the selected tool on the right."""

    TITLE = "DevForge"
    SUB_TITLE = "Linux workstation & server management"
    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
        ("ctrl+r", "refresh", "Refresh"),
        ("ctrl+p", "command_palette", "Commands"),
    ]
    CSS = """
    Screen { background: $background; }
    #machine { height: 3; padding: 1 2 0 2; color: $text-muted; }
    #workspace { height: 1fr; padding: 0 1; }
    #sidebar { width: 33; min-width: 24; border: round $primary-muted; padding: 1; }
    #sidebar Label { color: $accent; text-style: bold; margin-bottom: 1; }
    #navigation { height: 1fr; border: none; }
    #ui-theme { width: 100%; margin-top: 1; }
    #main { width: 1fr; margin-left: 1; }
    #details { height: auto; min-height: 4; padding: 1 2; border: round $primary-muted; }
    #choices { height: 45%; min-height: 7; border: round $primary-muted; margin-top: 1; }
    #activity { height: 1fr; border: round $primary-muted; margin-top: 1; padding: 0 1; }
    #busy { height: 3; display: none; }
    .busy #busy { display: block; }
    """

    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.theme = "tokyo-night"
        self.route = "home"
        self.tool_name: str | None = None
        self.category = "runtime"
        self.busy = False
        self.pending: list[Reply] = []
        self.tool_actions: list[tuple[str, str]] = []
        self.visible_tools: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Detecting Linux host...", id="machine")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Label(f"DEVFORGE  {__version__}")
                yield OptionList(id="navigation")
                yield Select(
                    [
                        (title, value)
                        for title, value in (
                            ("Tokyo Night", "tokyo-night"),
                            ("Catppuccin", "catppuccin-mocha"),
                            ("Nord", "nord"),
                            ("Dracula", "dracula"),
                            ("Light", "textual-light"),
                        )
                    ],
                    value="tokyo-night",
                    allow_blank=False,
                    id="ui-theme",
                )
            with Vertical(id="main"):
                yield Static(
                    "Choose a category or open Terminal studio.\nEvery change shows a plan first.",
                    id="details",
                )
                yield OptionList(id="choices")
                yield LoadingIndicator(id="busy")
                yield RichLog(id="activity", wrap=True, markup=False, max_lines=3000)
        yield Footer()

    def on_mount(self) -> None:
        self.initialize()

    @work(thread=True, group="browse")
    def initialize(self) -> None:
        system = self.ctx.system()
        self.call_from_thread(
            self.ready,
            f"{system.pretty_name}  /  {system.arch}  /  "
            f"{system.package_manager or 'no package manager'}  /  {system.form_factor}",
        )
        notice = check_newer(self.ctx)
        if notice is not None:
            self.call_from_thread(
                self.append_log,
                f"DevForge {notice.version} is available. "
                "Choose Update DevForge in the sidebar to review the update.",
            )

    def ready(self, summary: str) -> None:
        self.query_one("#machine", Static).update(summary)
        self.query_one("#navigation", OptionList).add_options(
            [
                *(Option(title, id=f"category:{category}") for category, title in _CATEGORIES),
                Option("Terminal studio", id="studio"),
                Option("System information", id="global:i"),
                Option("Doctor (offline)", id="global:d"),
                Option("Update installed tools", id="global:u"),
                Option("Presets", id="global:p"),
                Option("Mirrors", id="global:m"),
                Option("DNS", id="global:n"),
                Option("Shell PATH setup", id="global:s"),
                Option("Update DevForge", id="global:g"),
            ]
        )
        self.query_one("#navigation").focus()
        self.append_log("Ready. Components and prompt themes are installed only when selected.")

    def append_log(self, text: str) -> None:
        self.query_one("#activity", RichLog).write(Text(redact(text)))

    def on_select_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, str):
            self.theme = event.value

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.busy:
            self.notify("Finish or cancel the active operation first.")
            return
        key = event.option.id or ""
        if event.option_list.id == "navigation":
            self.tool_name = None
            if key.startswith("category:"):
                self.category = key.split(":", 1)[1]
                self.route = "category"
                self.load_category(self.category)
            elif key == "studio":
                self.show_studio()
            elif key.startswith("global:"):
                self.start_operation("global", key.split(":", 1)[1])
        elif event.option_list.id == "choices":
            if self.route == "category":
                self.tool_name = key
                self.route = "tool"
                self.load_tool(key)
            elif self.route == "tool" and self.tool_name:
                if key == "terminal":
                    self.show_studio()
                else:
                    self.start_operation("tool", key, self.tool_name)
            elif self.route == "studio":
                _label, action, theme = TERMINAL_OPTIONS[int(key)]
                self.start_operation("terminal", action, theme)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id != "choices" or self.route != "studio":
            return
        _label, action, theme = TERMINAL_OPTIONS[int(event.option.id or "0")]
        preview = Text("TERMINAL STUDIO / " + (theme or action).upper() + "\n", style="bold")
        if action in {"zsh-theme", "starship-theme"}:
            if theme in {"midnight", "server", "classic"}:
                preview.append("user@host ", style="bold magenta")
            preview.append("~/project ", style="bold cyan")
            if action == "starship-theme":
                preview.append("git:main ", style="bold blue")
            preview.append("\n> " if theme == "midnight" else "> ", style="bold green")
            preview.append("\nPreview only. Select to review the configuration plan.")
        else:
            preview.append(_label + "\nOnly this component will be changed after plan review.")
        self.query_one("#details", Static).update(preview)

    def show_studio(self) -> None:
        self.route = "studio"
        self.query_one("#details", Static).update(
            "TERMINAL STUDIO\nZsh, local history suggestions, highlighting and prompts "
            "are separate "
            "choices. Pick one theme. Nothing is preselected for installation.\n"
            "Zsh Minimal: ~/project >   |   Starship: ~/project git:main >"
        )
        choices = self.query_one("#choices", OptionList)
        choices.clear_options().add_options(
            Option(label, id=str(i)) for i, (label, _, _) in enumerate(TERMINAL_OPTIONS)
        )

    @work(thread=True, exclusive=True, group="browse")
    def load_category(self, category: str) -> None:
        options = []
        server = self.ctx.system().form_factor == "server"
        for tool in all_tools():
            if tool.spec.category == category and not (server and tool.spec.desktop_only):
                info = tool.detect(self.ctx)
                options.append(
                    Option(Text(f"{tool.name:<16} {info.current or 'not installed'}"), id=tool.name)
                )
        self.call_from_thread(self.category_ready, category, options)

    def category_ready(self, category: str, options: list[Option]) -> None:
        if self.route != "category" or self.category != category:
            return
        title = dict(_CATEGORIES)[category]
        self.query_one("#details", Static).update(
            Text(f"{title}\nSelect a tool to manage installed versions and its related operations.")
        )
        self.query_one("#choices", OptionList).clear_options().add_options(options)

    @work(thread=True, exclusive=True, group="browse")
    def load_tool(self, name: str) -> None:
        status = load_tool(name).status(self.ctx)
        self.call_from_thread(
            self.tool_ready,
            name,
            f"{name.upper()}  /  {status.installed_version or 'not installed'}"
            f"  /  {status.source}\n"
            f"{status.summary}\nUpdate target: {status.update_target or 'unknown'}",
            _tool_options(status),
        )

    def tool_ready(self, name: str, summary: str, options: list[tuple[str, str]]) -> None:
        if self.route != "tool" or self.tool_name != name:
            return
        self.query_one("#details", Static).update(Text(summary))
        self.query_one("#choices", OptionList).clear_options().add_options(
            Option(label, id=kind) for label, kind in options
        )

    def start_operation(self, kind: str, action: str, argument: str | None = None) -> None:
        self.busy = True
        self.add_class("busy")
        self.execute(kind, action, argument)

    @work(thread=True, group="operation")
    def execute(self, kind: str, action: str, argument: str | None) -> None:
        stream = BridgeStream(self)
        ctx = replace(
            self.ctx,
            printer=DialogPrinter(self, self.ctx, stream),
            runner=TerminalRunner(self, self.ctx.runner),
        )
        lines = DialogLines(self, stream)
        try:
            if kind == "terminal":
                cmd_terminal(ctx, action, argument)
            elif kind == "tool" and argument:
                _run_tool_action(ctx, lines, load_tool(argument), action)
            elif kind == "global":
                _ACTIONS[action](ctx, lines)
        except (OSError, ValueError, RuntimeError) as exc:
            self.call_from_thread(self.append_log, "Operation failed: " + redact(str(exc)))
        finally:
            self.call_from_thread(self.operation_done)

    def operation_done(self) -> None:
        self.busy = False
        self.remove_class("busy")
        if self.route == "tool" and self.tool_name:
            self.load_tool(self.tool_name)

    def ask(self, body: str, *, confirm: bool = False) -> str | None:
        reply = Reply(body, confirm)
        self.call_from_thread(self.open_prompt, reply)
        reply.ready.wait()
        return reply.value

    def open_prompt(self, reply: Reply) -> None:
        self.pending.append(reply)

        def done(value: str | None) -> None:
            reply.value = value
            reply.ready.set()
            self.pending.remove(reply)

        self.push_screen(PromptDialog(reply), done)

    async def action_back(self) -> None:
        if self.busy:
            return
        if self.route == "tool":
            self.tool_name = None
            self.route = "category"
            self.load_category(self.category)
        else:
            self.query_one("#navigation").focus()

    def action_refresh(self) -> None:
        if self.busy:
            return
        if self.route == "tool" and self.tool_name:
            self.load_tool(self.tool_name)
        elif self.route == "category":
            self.load_category(self.category)

    async def action_quit(self) -> None:
        if self.busy:
            self.notify("An operation is active. Finish it or cancel its dialog before quitting.")
            return
        self.exit()

    def on_unmount(self) -> None:
        for reply in self.pending:
            reply.value = None
            reply.ready.set()


def run_textual(ctx: Context) -> int:
    previous = os.environ.get("NO_COLOR")
    if not ctx.printer.color:
        os.environ["NO_COLOR"] = "1"
    try:
        DevForgeApp(ctx).run()
    finally:
        if previous is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = previous
    return 0
