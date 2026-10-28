"""Shell personalization choices exposed to both interfaces and the CLI."""

from __future__ import annotations

from devforge.commands.common import emit_json, run_plan
from devforge.commands.lifecycle import cmd_install
from devforge.context import Context
from devforge.core.state import load_json
from devforge.core.terminal import STARSHIP_THEMES, ZSH_THEMES, terminal_plan

OPTIONS = (
    ("Install Zsh only", "install-zsh", None),
    ("Enable history suggestions", "autosuggestions", None),
    ("Enable syntax highlighting", "highlighting", None),
    ("Zsh prompt / Minimal - cyan directory", "zsh-theme", "minimal"),
    ("Zsh prompt / Midnight - blue and purple, two lines", "zsh-theme", "midnight"),
    ("Zsh prompt / Classic - user, host and directory", "zsh-theme", "classic"),
    ("Install Starship only", "install-starship", None),
    ("Starship / Minimal - compact Git prompt", "starship-theme", "minimal"),
    ("Starship / Midnight - two lines, blue and purple", "starship-theme", "midnight"),
    ("Starship / Server - user and hostname always visible", "starship-theme", "server"),
    ("Disable history suggestions", "disable-autosuggestions", None),
    ("Disable syntax highlighting", "disable-highlighting", None),
    ("Reset DevForge prompt selection", "reset-prompt", None),
    ("Remove DevForge history suggestion files", "remove-autosuggestions", None),
    ("Remove DevForge syntax highlighting files", "remove-highlighting", None),
    ("Remove managed terminal configuration", "remove", None),
    ("Change my default login shell to Zsh", "default-shell", None),
)


def cmd_terminal(ctx: Context, action: str, theme: str | None = None) -> int:
    if action != "show" and ctx.euid == 0 and ctx.env.get("SUDO_USER", "root") != "root":
        ctx.printer.error(
            "Run terminal setup as your own user without sudo; package steps request "
            "privileges separately. No target account is guessed."
        )
        return 1
    if action in {"install-zsh", "install-starship"}:
        return cmd_install(
            ctx, action.removeprefix("install-"), None, make_default=True, use_package=False
        )
    if action == "show":
        payload = {
            "settings": load_json(ctx.paths.config / "terminal.json"),
            "zsh_themes": list(ZSH_THEMES),
            "starship_themes": list(STARSHIP_THEMES),
        }
        if ctx.as_json:
            emit_json(ctx, payload)
        else:
            ctx.printer.info("Terminal personalization / choose each component separately")
            for number, (label, _action, _theme) in enumerate(OPTIONS, 1):
                ctx.printer.raw(f"  {number:>2}  {label}")
            ctx.printer.raw("Current choices: " + str(payload["settings"]))
        return 0
    return run_plan(ctx, terminal_plan(ctx, action, theme))
