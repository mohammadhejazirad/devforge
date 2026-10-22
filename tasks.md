# DevForge — Task Tracker

Source of truth: `.docs/AGENTS.md` (English). `.docs/AGENTS.fa.md` was read in full and matches it section by section; no differences found.

Rules for this file: a task is checked only after it was actually run or tested. Each completed task gets a log entry (date, what, files, verification, problems/assumptions).

The previous copy of this tracker lived at `.docs/tasks.md` (phase 0 only). That path now points here.

## Phase 0 — Spec review

- [x] Read `.docs/AGENTS.md` and `.docs/AGENTS.fa.md` completely; inspect repo state

## Phase 1 — Project skeleton

- [x] `README.md`, `LICENSE` placeholder, `CONTRIBUTING.md`
- [x] `pyproject.toml` (no runtime deps; dev extras: ruff, mypy, pytest)
- [x] Package layout: `devforge/{__init__,__main__,cli}.py`, `core/`, `tools/`, `data/`, `tests/`, `docs/`
- [x] Centralized English strings + output markers (`[ok]`/`[warn]`/`[err]`, `NO_COLOR`, non-TTY)
- [x] `core/log.py`: log file under `~/.local/state/devforge/logs/`, secret redaction
- [ ] CI: the 1.0.0 push ran on GitHub Actions and failed. Python 3.9 and 3.14 passed. mypy parsed pytest 9 (`match`, Python 3.10+) under a 3.9 target, and shfmt rejected the four-space `install.sh`. The follow-up commit fixes both. This box stays open until that run is green.
- [x] Verify: `python -m devforge --help` works; ruff/mypy/pytest pass locally

## Phase 2 — Environment detection (`core/system.py`)

- [ ] Parse `/etc/os-release` (`ID`, `ID_LIKE`, `VERSION_ID`, `VERSION_CODENAME`) into a distro family
- [ ] Arch (`uname -m` → amd64/arm64/...), libc (glibc/musl), init system, container/WSL/VM
- [ ] Desktop-vs-server as a hint (env vars, `systemctl get-default`, DE packages)
- [ ] Root/sudo availability, disk space, RAM, proxy env
- [ ] Unknown/too-new distro: clear message + fallback, never a traceback
- [ ] Fixture tests: Debian 12/13, Ubuntu 22.04/24.04/26.04, Fedora, Rocky, Alma, CentOS Stream, RHEL, Arch, Manjaro, openSUSE Leap/Tumbleweed, Alpine, Linux Mint, Pop!_OS, unknown
- [ ] `devforge info` / `devforge doctor` (detection part), `--json`

## Phase 3 — Package manager, state, plan

- [ ] `core/pkgmgr.py`: apt/dnf/yum/pacman/zypper/apk abstraction that builds commands, never runs them directly
- [ ] `core/state.py`: JSON state DB, atomic writes, `*.devforge.bak` backups, owned-path guard for deletions
- [ ] `core/plan.py`: plan → show → confirm (`-y`) → apply; `--dry-run`; sudo reasons shown
- [ ] Tests run everything in dry-run or against tmp dirs only

## Phase 4 — Network, mirrors, DNS

- [ ] `core/net.py`: retries with backoff, resume, multi-source fallback, SHA256 verify, proxy env, offline cache
- [ ] `core/mirrors.py` + `devforge/data/mirrors/*.json`: `mirror list|set|test|reset`, opt-in, reversible
- [ ] `core/dns.py`: detect resolver (systemd-resolved/NetworkManager/resolvconf/static), `dns show|set|test|restore`, backup before change
- [ ] Tests use local HTTP server/fixtures and tmp file roots; no host DNS changes

## Phase 5 — First tools via shared `Tool` interface

- [ ] `tools/base.py`: `Tool` protocol, `InstalledInfo`, `Version`, `Scope`, `Check`, strict version regexes
- [ ] Node.js (side-by-side versions, `.nvmrc`/`.node-version`/`.tool-versions`, coexist with nvm)
- [ ] Python (coexist with pyenv/distro python)
- [ ] Go (official tarballs, `GOPROXY` mirror)
- [ ] Docker (+ Compose; distro repo or official repo; group membership)
- [ ] PHP (CLI + FPM, `update-alternatives` where relevant)
- [ ] Shell integration: managed rc block with begin/end markers (bash/zsh/fish), reversible
- [ ] Dry-run plan tests for each tool on several distro fixtures

## Phase 6 — TUI, presets, bootstrap

- [ ] `tui.py`: stdlib interactive menus; hide GUI-only options on servers
- [ ] Presets (`web-php`, `node-fullstack`, `go-backend`, `devops`) + `devforge apply <file>` / export
- [ ] `install.sh`: POSIX sh, python3 >= 3.9 check (install with consent), pinned release, SHA256 verify, `~/.local/share/devforge` + symlink
- [ ] shellcheck + container test with/without python3 (CI)

## Later (out of current scope)

- [ ] Remaining tools (Rust, Java, Ruby, .NET, Bun, Deno, databases, infra tools)
- [ ] Container integration-test matrix in GitHub Actions
- [ ] Release packaging, checksums, signatures

---

## Log

### 2026-10-23 — Phase 0: spec review

- What: Read both spec files in full and inspected the repo.
- Files: `.docs/tasks.md` (original tracker, now a pointer).
- Repo state at review: `.docs/AGENTS.md`, `.docs/AGENTS.fa.md`, `.docs/tasks.md`, `.vscode/settings.json`. No application code.
- Problems: The prompt names `.docs/Agent.md` and `.docs/Agent.fa.md`. The repo has `.docs/AGENTS.md` and `.docs/AGENTS.fa.md`. Those were the files read.
- Verification: Compared sections 1–11 directly, including the non-interactive mode and preset bullets.

### 2026-10-23 — Phase 1: project skeleton

- What: Added the package layout, English CLI (`--help`, `--version`, global flags), status markers, redacting file log, XDG path guard, strict version checks, docs, and CI. No subcommands yet.
- Files: `README.md`, `LICENSE`, `CONTRIBUTING.md`, `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml`, `conftest.py`, `docs/README.md`, `docs/architecture.md`, `devforge/**`, `tests/**`, `tasks.md`, `.docs/tasks.md` (pointer). Restored `.vscode/settings.json`, `.docs/AGENTS.md`, and `.docs/AGENTS.fa.md` after unrelated edits appeared.
- Verification:
  - Host Python 3.14.4: `ruff check`, `ruff format --check`, `pytest` (39 passed), `python3 -m devforge --help` (exit 0), `--version` prints `devforge 0.1.0`, no command exits 2.
  - Container `python:3.9-slim` (3.9.25), offline wheels: `ruff check`, `ruff format --check`, `mypy` (18 files, no issues), `pytest` (39 passed), `--help`.
- Not run: GitHub Actions itself. `shellcheck` and `shfmt` were not run locally because the tree has no `*.sh` files. The CI shell job exits 0 in that case. Container DNS could not resolve PyPI (`127.0.0.53` / `192.168.1.1`), so the 3.9 run used wheels downloaded on the host.
- Problems: Mid-session the tree also contained `devforge/ui.py`, `devforge/strings.py`, `core/paths.py`, `core/versioning.py`, and `docs/architecture.md`, while `pyproject.toml` pointed at a missing `entrypoint`. Those were kept and wired up. Duplicate `core/text.py` and `core/output.py` were removed. A version sort that ranked every final release above every pre-release (so `0.9` > `1.0-rc1`) was fixed.

### 2026-10-23 — Release 1.0.0 installer

- What: Bumped the version to 1.0.0, set the license to MIT, and added `install.sh`. It downloads the pinned GitHub release archive, checks SHA256, and installs the `devforge` command under `~/.local` or `/usr/local` for root. It does not run another remote script. Python is installed with the system package manager only after a terminal yes, or when `DEVFORGE_INSTALL_PYTHON=1`.
- Files: `install.sh`, `scripts/build_release.py`, `tests/test_install.py`, `README.md`, `LICENSE`, `pyproject.toml`, `devforge/__init__.py`, `tasks.md`.
- Verification: shellcheck 0.10.0; pytest 44 passed on Python 3.14.4, including an install into a temp prefix and rejection of a bad checksum and a path-escaping archive. Release SHA256 `0edf8516776568e607898ba573cb8272a841589d1296a4cdfe97fc5affd654c9`.
- Not done on the host: no package install, no DNS change, and the installer was not pointed at `~/.local`.
- After publish: `curl` of `main/install.sh` into `DEVFORGE_PREFIX=/tmp/devforge-e2e/root` installed 1.0.0. `devforge --version` printed `devforge 1.0.0`. The release asset SHA256 matched the pin. Actions run `39856215737` on `main` failed; see the next entry.

### 2026-10-23 — CI fixes after the 1.0.0 publish

- What: `shfmt` in CI now uses `-i 4 -ci`, which matches `install.sh`. mypy skips the pytest package so pytest 9 syntax is not parsed as Python 3.9. `tests` is a package, so the existing `tests.*` mypy override applies, including untyped pytest decorators.
- Files: `.github/workflows/ci.yml`, `pyproject.toml`, `tests/__init__.py`, `tasks.md`.
- Verification: local ruff and pytest (44 passed) on Python 3.14.4. shellcheck 0.10.0 and `shfmt -i 4 -ci -d` are clean. mypy 1.20.2 on Python 3.12 in `python:3.12-slim`, with wheels downloaded on the host, reported no issues. The container has no curl, so its install tests are not the host result.
- Not done: the GitHub Actions re-run is the remaining check. The release archive is unchanged because these files are not inside it.

---

## Decisions

1. **Spec location:** the spec files stay in `.docs/`. Section 4 shows `AGENTS.md` at the root, but they will not be moved or copied unless the maintainer asks.
2. **Tracker location:** the living checklist is this root `tasks.md`, as requested for the session. `.docs/tasks.md` only points here.
3. **Logging module name:** `core/log.py` instead of `core/logging.py`, so it never shadows the stdlib `logging` module.
4. **Data format:** mirror and version data will use JSON because `tomllib` exists only in Python 3.11+ and the runtime must stay on the stdlib on 3.9.
5. **Type syntax:** every module uses `from __future__ import annotations`, so `list[...]` and `X | None` hints work on 3.9.
6. **Packaging:** `pyproject.toml` with setuptools and zero runtime dependencies. Dev tools (ruff, mypy, pytest) go in an optional `dev` extra only.
7. **Side effects:** system-touching code will take injectable runners and root paths so tests never touch the host.
8. **License:** MIT for the 1.0.0 public release. The spec allowed MIT or Apache-2.0 and the maintainer had not chosen; a public installer cannot ship with no license. Apache-2.0 can replace it later if the maintainer prefers.
9. **Version:** `1.0.0` is the first installable release. The CLI still prints help and version only. Provisioning commands are not in this release. Global flags are parsed; `--help`, `--version`, and `--no-color` change behavior.
10. **CI Python:** pytest and ruff on 3.9 and 3.14. This machine is 3.14.4, so 3.14 is the pinned "latest" rather than a floating version. mypy stays on the 1.x line (`mypy>=1.13,<2`) because mypy 2 refuses a 3.9 target, and that line does not run on Python 3.14, so the mypy job uses Python 3.12. pytest is pinned to `<9` only on Python 3.9, because pytest 9 requires Python 3.10+. mypy does not parse pytest, and `shfmt` checks `install.sh` with `-i 4 -ci`.
11. **Log path:** `$XDG_STATE_HOME/devforge/logs/devforge.log` when that variable is absolute, otherwise `~/.local/state/devforge/logs/devforge.log`. Relative XDG values are ignored. Append-only, with a 2MB rotation. Directory mode `0700`, file mode `0600`. Newlines in a message are folded into one line. A logging failure disables that logger and does not crash the program.
12. **Markers:** `[ok]` and `[info]` go to stdout. `[warn]` and `[err]` go to stderr. Color is on when stdout is a TTY, unless `NO_COLOR` is set, `TERM=dumb`, or `--no-color` is passed. `FORCE_COLOR` turns color on for a non-TTY. Help text from argparse is always plain, including on Python 3.14.
13. **Console script:** `devforge` calls `devforge.cli:entrypoint`, which exits with the status code from `main`. `python -m devforge` uses `__main__.py`.
14. **One string module and one printer:** user-facing strings live in `devforge/strings.py`. Markers and prompts live in `devforge/ui.py`.
15. **Versions:** one optional leading `v` is allowed. Digits compare numerically. A final release sorts after a pre-release with the same numbers (`1.0` > `1.0-rc1`), and `1.0-rc1` still sorts after `0.9`.
16. **Owned paths:** `core/paths.py` is the only place XDG directories are derived. `contains` is false for the owned root itself and for anything outside it, so a later delete cannot target the root or an escaped path.

## Open Questions (for maintainer)

1. Final project name (spec says "DevForge" is a working name).
2. License: shipped as MIT for 1.0.0 so the public installer is actually licensed. Say if this should be Apache-2.0 instead.
3. Minimum Python version: 3.9 as stated, or higher? (3.11 would allow stdlib `tomllib`.)
4. Version management: own shims/PATH management, or integrate with `mise`/`asdf`?
5. `devforge apply devforge.toml`: on Python < 3.11 there is no stdlib TOML parser. Proposed assumption: use `tomllib` when present, fall back to a small subset parser, and also accept `.json`.
6. Should `AGENTS.md` / `AGENTS.fa.md` move to the repo root as section 4 shows, or stay in `.docs/`?
7. Resolved for 1.0.0: the public repo is `mohammadhejazirad/devforge`, the default branch is `main`, and the installer URL in the README points there.
8. Iranian mirror list: which operators to ship as initial community data? They will be marked unverified until the maintainer reviews them.
