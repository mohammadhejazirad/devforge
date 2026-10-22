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

WARN_NO_TTY = "Not running in a terminal; assuming no via --yes."
WARN_ROOT = "Running as root. Prefer a normal user with sudo when possible."
WARN_UNVERIFIED_MIRROR = "Mirror {name} is not verified yet; use it at your own risk."

# Marker prefixes, plain ASCII so they survive any terminal.
MARK_OK = "[ok]"
MARK_WARN = "[warn]"
MARK_ERR = "[err]"
MARK_INFO = "[info]"
MARK_STEP = "==>"

DESCRIPTION = (
    "Provision Linux development tools and switch their versions. "
    "This build is an early skeleton: it prints help and version only."
)

HELP_EXAMPLES = """
Examples:
  devforge --help
  devforge --version
"""

HELP_DRY_RUN = "Show the plan and do not change the system. No command uses this yet."
HELP_YES = "Skip confirmation prompts. No command uses this yet."
HELP_JSON = "Print machine-readable JSON on stdout. No command uses this yet."
HELP_NO_COLOR = "Disable colored status markers."
HELP_QUIET = "Hide informational lines. Warnings and errors are still shown."
HELP_VERBOSE = "Show more detail. Repeat for more."

ERR_NO_COMMAND = "No command was given. Run devforge --help to see usage."

VERSION_TEMPLATE = "devforge {version}"
