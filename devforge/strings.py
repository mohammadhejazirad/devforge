"""Centralized English user-facing strings.

The program is English-only (see spec section 2). Keeping strings here makes
that enforceable and auditable in one place.
"""

from __future__ import annotations

APP_TAGLINE = "Developer environment provisioning for Linux"

ASK_BACKUP = "DevForge backs up config files before editing them (*.devforge.bak)."
ASK_SUDO_REASON = "This step needs root privileges: {reason}"

ERR_BAD_USAGE = "Invalid usage: {message}"
ERR_DRY_RUN_NOTE = "Dry run: nothing was changed."
ERR_FAILED = "{action} failed (exit code {code})."
ERR_FILE_WRITE = "Could not write {path}: {message}"
ERR_INTERRUPTED = "Interrupted by user."
ERR_NOT_FOUND = "Command not found: {name}"
ERR_UNKNOWN_COMMAND = "Unknown command: {name}"
ERR_VERSION_INVALID = "Invalid version string: {value!r}"

INFO_DRY_RUN = "Dry run: showing the plan only."
INFO_LOGS_AT = "Logs: {path}"
INFO_PLAN_EMPTY = "Nothing to do; the system is already in the desired state."
INFO_PLAN_HEADER = "Planned actions ({count}):"

OK_DONE = "Done."
OK_UP_TO_DATE = "Already up to date."

PROMPT_CONFIRM = "Proceed?"
PROMPT_PRESS_ENTER = "Press Enter to continue."

WARN_DECLINED = "Declined. Nothing was changed."
WARN_NO_TTY = "Not running in a terminal; assuming no via --yes."
WARN_ROOT = "Running as root. Prefer a normal user with sudo when possible."
WARN_UNVERIFIED_MIRROR = "Mirror {name} is not verified yet; use it at your own risk."
WARN_UNVERIFIED_DNS = "DNS preset {name} is not verified yet; use it at your own risk."

# Marker prefixes, plain ASCII so they survive any terminal.
MARK_OK = "[ok]"
MARK_WARN = "[warn]"
MARK_ERR = "[err]"
MARK_INFO = "[info]"
MARK_STEP = "==>"

DESCRIPTION = (
    "Provision Linux development tools and switch their versions. "
    "Every change is shown as a plan before it runs. "
    "Run devforge with no arguments in a terminal to open the menu."
)

HELP_EXAMPLES = """
Examples:
  devforge
  devforge --help
  devforge --version
  devforge self-update
  devforge info
  devforge status
  devforge status php
  devforge versions node
  devforge --dry-run install node
  devforge install php 8.4
  devforge use node 24.22.1
  devforge pin python 3.13
  devforge update --all
  devforge uninstall node 22.23.4
  devforge mirror list
  devforge dns show
  devforge preset apply web-php
  devforge apply devforge.json
  devforge doctor --offline
"""

HELP_DRY_RUN = "Show the plan and do not change the system."
HELP_YES = "Skip confirmation prompts."
HELP_JSON = "Print machine-readable JSON on stdout."
HELP_NO_COLOR = "Disable colored status markers."
HELP_QUIET = "Hide informational lines. Warnings and errors are still shown."
HELP_VERBOSE = "Show more detail. Repeat for more."

ERR_NO_COMMAND = "No command was given. Run devforge --help to see usage."
ERR_MENU_NEEDS_TTY = "The menu needs a terminal. Pass a command, for example: devforge --help"
ERR_UPDATE_OFFLINE = "Cannot check for DevForge updates while offline."

INFO_CHECKOUT_UPDATE = (
    "This copy is a source checkout. Update it with git pull, "
    "or install a release with install.sh. DevForge will not overwrite a checkout."
)
INFO_RELEASE_AVAILABLE = (
    'A new version is available: {version}. Choose "Update DevForge" to install it.'
)
INFO_RELEASE_READY = "DevForge {version} is available (you have {current})."

OK_RELEASE_CURRENT = "DevForge {version} is already the newest release."
OK_SELF_UPDATED = "Updated DevForge to {version}. Open a new command to use it."

PROMPT_SELF_UPDATE = "Install this DevForge update?"

VERSION_TEMPLATE = "devforge {version}"
