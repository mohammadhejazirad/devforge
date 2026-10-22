# Contributing to DevForge

Thanks for helping. The English specification in `.docs/AGENTS.md` is the
source of truth for behavior; `.docs/AGENTS.fa.md` is a Persian translation and
both files must stay in sync when the spec changes.

## Ground rules

- All user-facing program text is English only, including menus, prompts,
  errors, and `--help`. Docs may be bilingual; the program is not.
- Terminal only. Do not add GUI dependencies, on desktop or server.
- Python 3.9+ with the standard library only on the runtime path. Do not add a
  runtime dependency without discussion; dev-only tools are fine.
- Be distro-agnostic. Never hardcode "Ubuntu" or any single distribution;
  detect from `/etc/os-release` and `uname -m`.
- Use `subprocess` with argument lists. Never use `shell=True` with
  interpolated input.
- Keep functions small, typed, and readable. Type hints are required.

## Safety

- Never run mutating system commands (package installs, DNS changes) on your
  machine while developing. Use `--dry-run`, fixtures, or containers.
- Every mutating code path must be reachable in `--dry-run` without root.
- Back up configuration files before editing them, and never delete a computed
  path unless it is inside a DevForge-owned directory.
- Mirrors and DNS changes are opt-in and reversible.
- No secrets in the repo, no telemetry by default.

## Workflow

1. Read `.docs/AGENTS.md` first.
2. Inspect the repo before changing anything; do not overwrite existing work.
3. Build in the order given in section 11 of the specification.
4. Ship tests and docs with each change.
5. If a requirement is ambiguous, write your assumption in `tasks.md` instead of
   guessing silently.

## Checks

Run these before opening a pull request:

```bash
python3 -m pytest
ruff check .
ruff format --check .
mypy
shellcheck install.sh    # if you changed shell code
```

`mypy` is installed for Python 3.9 through 3.13. mypy 2.x cannot target 3.9,
and mypy 1.x does not run on 3.14, so CI typechecks on Python 3.12. Pytest and
ruff run on 3.9 and 3.14. `shellcheck` and `shfmt` run when shell files exist.

## Commit style

Keep commits focused: one logical change, with tests and docs. Describe why in
the message, and note assumptions explicitly.

