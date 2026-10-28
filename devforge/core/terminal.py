"""Opt-in Zsh customization, with pinned plugins and reversible owned blocks."""

from __future__ import annotations

import json
from pathlib import Path

from devforge.context import Context
from devforge.core.plan import Plan, Step
from devforge.core.shell import sh_single
from devforge.core.state import load_json

BEGIN = "# >>> devforge terminal >>>"
END = "# <<< devforge terminal <<<"
PLUGINS = {
    "autosuggestions": (
        "zsh-autosuggestions",
        "v0.7.1",
        "zsh-autosuggestions.zsh",
        "0df7affff21cd87ed298e6a3970ed08a1dd66a6efa676454ee5b091ad503badf",
    ),
    "highlighting": (
        "zsh-syntax-highlighting",
        "0.8.0",
        "zsh-syntax-highlighting.zsh",
        "5981c19ebaab027e356fe1ee5284f7a021b89d4405cc53dc84b476c3aee9cc32",
    ),
}
ZSH_THEMES = {
    "minimal": "%F{cyan}%~%f %# ",
    "midnight": "%F{blue}%n@%m%f %F{magenta}%~%f\n%F{cyan}%#%f ",
    "classic": "%F{green}%n%f@%m %F{blue}%~%f %# ",
}
STARSHIP_THEMES = {
    "minimal": """add_newline = false
format = "$directory$git_branch$git_status$character"
[directory]
style = "bold cyan"
[git_branch]
symbol = "git:"
[character]
success_symbol = "[>](bold green)"
error_symbol = "[>](bold red)"
""",
    "midnight": """add_newline = true
format = "$username$hostname$directory$git_branch$git_status$line_break$character"
[username]
show_always = true
style_user = "bold purple"
format = "[$user]($style) "
[hostname]
ssh_only = false
format = "on [$hostname](bold blue) "
[directory]
style = "bold blue"
[git_branch]
symbol = "git:"
style = "bold purple"
[character]
success_symbol = "[>](bold cyan)"
error_symbol = "[>](bold red)"
""",
    "server": """add_newline = false
format = "$username$hostname$directory$git_branch$cmd_duration$character"
[username]
show_always = true
format = "[$user]($style)@"
[hostname]
ssh_only = false
format = "[$hostname](bold cyan) "
[directory]
style = "bold blue"
[git_branch]
symbol = "git:"
[character]
success_symbol = "[>](bold green)"
error_symbol = "[>](bold red)"
""",
}
ACTIONS = (
    "autosuggestions",
    "highlighting",
    "disable-autosuggestions",
    "disable-highlighting",
    "remove-autosuggestions",
    "remove-highlighting",
    "zsh-theme",
    "starship-theme",
    "reset-prompt",
    "remove",
    "default-shell",
)


def _rc_path(ctx: Context) -> Path:
    custom = ctx.env.get("ZDOTDIR", "")
    base = Path(custom).expanduser() if custom else ctx.paths.home
    home = ctx.paths.home.resolve()
    if not base.is_absolute() or (base.resolve() != home and home not in base.resolve().parents):
        raise ValueError(
            "ZDOTDIR must be an absolute directory inside your home for managed edits."
        )
    path = base / ".zshrc"
    if path.is_symlink():
        raise ValueError(
            "The Zsh config is a symlink. Keep it under your dotfiles manager; "
            "DevForge will not replace that link."
        )
    return path


def _block(existing: str, content: str) -> str:
    if BEGIN not in existing and END not in existing:
        return existing.rstrip("\n") + ("\n\n" if existing else "") + content
    if existing.count(BEGIN) != 1 or existing.count(END) != 1:
        raise ValueError("The DevForge terminal block has duplicate or incomplete markers.")
    start, end = existing.index(BEGIN), existing.index(END)
    if end < start:
        raise ValueError("The DevForge terminal block markers are out of order.")
    end += len(END)
    if existing[end : end + 1] == "\n":
        end += 1
    return existing[:start] + content + existing[end:]


def _plugin_path(ctx: Context, name: str) -> Path:
    repository, version, filename, _ = PLUGINS[name]
    return ctx.paths.data / "terminal" / "plugins" / repository / version / filename


def _starship(ctx: Context) -> str:
    located = ctx.runner.which("starship")
    if located:
        return located
    shim = ctx.paths.shims / "starship"
    if shim.is_file():
        return str(shim)
    raise ValueError("Install Starship first, then choose its prompt theme.")


def _render(ctx: Context, settings: dict[str, object]) -> str:
    lines = [BEGIN]
    if settings.get("autosuggestions"):
        lines += [
            "HISTFILE=${HISTFILE:-$HOME/.zsh_history}",
            "HISTSIZE=${HISTSIZE:-10000}",
            "SAVEHIST=${SAVEHIST:-10000}",
            "ZSH_AUTOSUGGEST_STRATEGY=(history)",
            "(( $+functions[_zsh_autosuggest_start] )) || source "
            + sh_single(str(_plugin_path(ctx, "autosuggestions"))),
        ]
    prompt = settings.get("prompt")
    theme = str(settings.get("theme", "minimal"))
    if prompt == "zsh":
        if theme not in ZSH_THEMES:
            raise ValueError("Unknown saved Zsh theme. Select a supported theme again.")
        lines += ["PROMPT=" + sh_single(ZSH_THEMES[theme]), "RPROMPT='' "]
    elif prompt == "starship":
        lines += [
            "export STARSHIP_CONFIG=" + sh_single(str(ctx.paths.config / "starship.toml")),
            'eval "$(' + sh_single(_starship(ctx)) + ' init zsh)"',
        ]
    elif prompt is not None:
        raise ValueError("Unknown saved prompt. Select a supported theme again.")
    # Syntax highlighting must load last, after widgets initialized by other plugins/prompts.
    if settings.get("highlighting"):
        lines += [
            "(( $+functions[_zsh_highlight] )) || source "
            + sh_single(str(_plugin_path(ctx, "highlighting")))
        ]
    lines += [END, ""]
    return "\n".join(lines) if len(lines) > 3 else ""


def terminal_plan(ctx: Context, action: str, theme: str | None = None) -> Plan:
    """Select one component. Never guess a user or install unrelated components."""
    plan = Plan(title=f"Terminal: {action}")
    try:
        if action not in ACTIONS:
            raise ValueError("Unknown terminal action.")
        if ctx.euid == 0 and ctx.env.get("SUDO_USER", "root") != "root":
            raise ValueError(
                "Run terminal customization as your own user without sudo. "
                "Package steps request sudo separately when required."
            )
        rc = _rc_path(ctx)
        if action == "default-shell":
            zsh = ctx.runner.which("zsh")
            shells = ctx.fs_root / "etc" / "shells"
            if not zsh or not shells.is_file():
                raise ValueError(
                    "Install Zsh and check /etc/shells before changing the login shell."
                )
            allowed = [
                line.strip()
                for line in shells.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            ]
            if zsh not in allowed:
                equivalent = next(
                    (entry for entry in allowed if Path(entry).resolve() == Path(zsh).resolve()),
                    None,
                )
                if equivalent:
                    zsh = equivalent
            if zsh not in allowed:
                raise ValueError(
                    f"{zsh} is not listed in /etc/shells. Ask your system administrator."
                )
            if not ctx.runner.which("chsh"):
                raise ValueError(
                    "chsh is unavailable. Use the account-management tool for this distro."
                )
            plan.add(
                Step(
                    title="Change only your own login shell to Zsh",
                    kind="command",
                    argv=("chsh", "-s", zsh),
                )
            )
            plan.notes.append(
                "This changes the current account's future login shell. "
                "Authentication may be required. Log in again afterwards."
            )
            return plan
        if action in {
            "autosuggestions",
            "highlighting",
            "zsh-theme",
            "starship-theme",
        } and not ctx.runner.which("zsh"):
            raise ValueError(
                "Install Zsh first. No shell, plugin or theme is installed implicitly."
            )
        state = ctx.paths.config / "terminal.json"
        settings: dict[str, object] = dict(load_json(state))
        saved_rc = settings.pop("rc_path", None)
        if saved_rc and saved_rc != str(rc):
            raise ValueError(
                "ZDOTDIR changed. Remove the existing managed terminal setup using "
                "its original ZDOTDIR before configuring another file."
            )
        original = rc.read_text(encoding="utf-8") if rc.exists() else ""
        if action in PLUGINS:
            repository, version, filename, checksum = PLUGINS[action]
            target = _plugin_path(ctx, action)
            if not ctx.paths.contains(target) or target.parent.is_symlink() or target.is_symlink():
                raise ValueError("Refusing an unsafe plugin path.")
            if not target.is_file():
                if target.parent.exists():
                    raise ValueError(
                        f"Incomplete plugin directory: {target.parent}. "
                        "Use Remove for this plugin before retrying."
                    )
                archive = ctx.paths.cache / "terminal" / f"{repository}-{version}.tar.gz"
                plan.add(
                    Step(
                        title=f"Download pinned {repository} {version}",
                        kind="download",
                        urls=(
                            f"https://codeload.github.com/zsh-users/{repository}/tar.gz/refs/tags/{version}",
                        ),
                        dest=str(archive),
                        sha256=checksum,
                    )
                )
                plan.add(
                    Step(
                        title=f"Extract {repository}",
                        kind="extract",
                        archive=str(archive),
                        dest=str(target.parent),
                        fmt="tar.gz",
                    )
                )
                plan.add(
                    Step(
                        title="Verify plugin entry point",
                        kind="verify-install",
                        path=str(target.parent),
                        packages=(filename,),
                    )
                )
            settings[action] = True
        elif action.startswith(("disable-", "remove-")):
            settings.pop(action.split("-", 1)[1], None)
        elif action in {"zsh-theme", "starship-theme"}:
            themes = ZSH_THEMES if action == "zsh-theme" else STARSHIP_THEMES
            if theme not in themes:
                raise ValueError("Choose a theme: " + ", ".join(themes))
            settings.update(prompt="zsh" if action == "zsh-theme" else "starship", theme=theme)
            if action == "starship-theme":
                _starship(ctx)
                plan.add(
                    Step(
                        title=f"Write selected Starship theme: {theme}",
                        kind="write",
                        path=str(ctx.paths.config / "starship.toml"),
                        policy="owned",
                        content=STARSHIP_THEMES[theme],
                    )
                )
        elif action == "reset-prompt":
            settings.pop("prompt", None)
            settings.pop("theme", None)
        elif action == "remove":
            settings = {}
        content = _render(ctx, settings)
        updated = _block(original, content)
        if updated != original:
            plan.add(
                Step(
                    title=f"Update only the DevForge terminal block in {rc}",
                    kind="write",
                    path=str(rc),
                    policy="rc",
                    content=updated,
                )
            )
        settings["rc_path"] = str(rc)
        plan.add(
            Step(
                title="Save terminal component choices",
                kind="write",
                path=str(state),
                policy="owned",
                content=json.dumps(settings, indent=2) + "\n",
            )
        )
        if action.startswith("remove-"):
            component = action.split("-", 1)[1]
            directory = _plugin_path(ctx, component).parent
            if directory.exists():
                plan.add(
                    Step(
                        title=f"Remove DevForge's {component} files only",
                        kind="delete",
                        path=str(directory),
                    )
                )
        plan.notes.append(
            "Existing configuration is preserved outside the marked block and backed up "
            "before edits. Open a new Zsh session to apply or remove settings. "
            "Existing prompt frameworks may load first; the selected prompt overrides "
            "their prompt for this session. No Nerd Font is required."
        )
        if action == "autosuggestions":
            plan.notes.append(
                "Suggestions use only local command history. Commands are not uploaded; "
                "new Zsh sessions keep history in your existing HISTFILE or ~/.zsh_history."
            )
    except (OSError, ValueError) as exc:
        return Plan(title=plan.title, blocked=str(exc))
    return plan
