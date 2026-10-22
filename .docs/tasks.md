# DevForge — Task Tracker

Source of truth: `.docs/AGENTS.md` (English). `.docs/AGENTS.fa.md` was read in full and matches it section by section; I found no differences.

Rules for this file: a task is checked only after it was actually run or tested. Each completed task gets a log entry (date, what, files, verification, problems/assumptions).

## Phase 0 — Spec review

- [x] Read `.docs/AGENTS.md` and `.docs/AGENTS.fa.md` completely; inspect repo state

## Phase 1 — Project skeleton

- [ ] `README.md`, `LICENSE` placeholder, `CONTRIBUTING.md`
- [ ] `pyproject.toml` (no runtime deps; dev extras: ruff, mypy, pytest)
- [ ] Package layout: `devforge/{__init__,__main__,cli}.py`, `core/`, `tools/`, `data/`, `tests/`, `docs/`
- [ ] Centralized English strings + output markers (`[ok]`/`[warn]`/`[err]`, `NO_COLOR`, non-TTY)
- [ ] `core/log.py`: log file under `~/.local/state/devforge/logs/`, secret redaction
- [ ] CI: GitHub Actions running ruff, mypy, pytest (Python 3.9 + latest), shellcheck + shfmt
- [ ] Verify: `python -m devforge --help` works; ruff/mypy/pytest pass locally

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
- Files: `tasks.md` (new).
- Repo state: no commits yet; only `.vscode/settings.json` (staged) and the untracked `.docs/`. No existing code to preserve.
- Problems: The prompt names the spec files `.docs/Agent.md` / `.docs/Agent.fa.md`, but the repo has `.docs/AGENTS.md` / `.docs/AGENTS.fa.md`. I used those.
- Verification: Compared the sections of the two files directly (§1–§11 match, including the §5 non-interactive and preset bullets).

---

## Decisions

1. **Spec location:** the spec files stay in `.docs/`. §4 shows `AGENTS.md` at the root, but they will not be moved or copied unless the maintainer asks.
2. **Logging module name:** `core/log.py` instead of `core/logging.py`, so it never shadows the stdlib `logging` module.
3. **Data format:** mirror and version data use JSON because `tomllib` only exists in Python 3.11+ and the runtime must stay stdlib-only on 3.9.
4. **Type syntax:** every module uses `from __future__ import annotations`, so `list[...]` and `X | None` hints work on 3.9.
5. **Packaging:** `pyproject.toml` with setuptools and zero runtime dependencies. Dev tools (ruff, mypy, pytest) go in an optional `dev` extra only.
6. **Side effects:** all system-touching code goes through injectable runners and root paths (e.g. `os_release_path`, a fake `CommandRunner`), so tests never touch the host.
7. **License placeholder:** `LICENSE` notes that the choice between MIT and Apache-2.0 is pending (see Open Questions).

## Open Questions (for maintainer)

1. Final project name (spec says "DevForge" is a working name).
2. License: MIT or Apache-2.0?
3. Minimum Python version: 3.9 as stated, or higher? (3.11 would allow stdlib `tomllib`.)
4. Version management: own shims/PATH management, or integrate with `mise`/`asdf`?
5. `devforge apply devforge.toml`: on Python < 3.11 there is no stdlib TOML parser. Options are a minimal built-in TOML-subset parser, accepting JSON as well, or requiring 3.11 for this one command. Proposed assumption: use `tomllib` when present, fall back to a small subset parser, and also accept `.json`.
6. Should `AGENTS.md`/`AGENTS.fa.md` move to the repo root as §4 shows, or stay in `.docs/`?
7. GitHub owner/repo for the `install.sh` URL and release pinning.
8. Iranian mirror list: which operators to ship as initial community data? They will be clearly marked as unverified until the maintainer reviews them.
