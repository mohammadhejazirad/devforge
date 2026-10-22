# AGENTS.md — DevForge (working name)

Instructions for AI coding agents working on this repository. Read this fully before writing code. A Persian version is in `AGENTS.fa.md`; keep both files in sync (the English file is the source of truth if they diverge).

---

## 1. Project Vision

DevForge is a terminal-based, intelligent provisioning and version-management tool for developers on Linux (desktop and server). After a fresh OS install, a developer should be productive in minutes, not hours.

It installs, updates, switches, pins, and removes development tooling:

- Languages/runtimes: PHP, Node.js, Go, Python, Rust, Java, Ruby, .NET, Bun, Deno
- Version managers/package tools: NVM, NPM, pnpm, Yarn, Composer, pipx, uv, pyenv
- Infrastructure: Docker (+ Compose), Git, kubectl, Helm, Terraform
- Databases/services: MySQL/MariaDB, PostgreSQL, Redis, Nginx, Caddy
- Utilities: build-essential equivalents, curl, jq, tmux, ripgrep, SSH keys, shell setup, etc.

Think of it as the combined judgment of a **senior DevOps engineer, senior Linux admin, and senior software engineer**: safe by default, idempotent, explicit about what it will do, and resilient on bad networks.

Public distribution: users install with a single copy-paste command from GitHub, e.g.

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | bash
```

## 2. Non-Negotiable Requirements

1. **All user-facing text is English only** (menus, prompts, logs, errors, `--help`). Persian is poorly supported in terminals. No RTL text in code output. Docs may be bilingual; the program is not.
2. **Terminal-only** (CLI + interactive TUI/prompts). No GUI dependency, on desktop or server.
3. **Distro-agnostic.** Never hardcode "Ubuntu". Detect via `/etc/os-release` (`ID`, `ID_LIKE`, `VERSION_ID`) and architecture via `uname -m`. Must work at least on Debian/Ubuntu, Fedora/RHEL family (Rocky, Alma, CentOS Stream), Arch/Manjaro, openSUSE, and Alpine (best effort). Reference targets: Ubuntu Desktop 26.04 and Ubuntu Server 24.04.5.
4. **Desktop vs server must not change core behavior.** Detect it (see §6) only to hide GUI-only options and tune defaults.
5. **Iranian mirror support and DNS switching are first-class features**, optional and user-controlled (see §7).
6. **Version lifecycle for every tool:** install, list installed, list available, update, switch/set default, pin per-project, uninstall, doctor/verify.
7. **Public-repo quality:** safe to pipe to bash, no secrets, no telemetry by default, MIT/Apache-2.0 license, clear contribution guide.

## 3. Language and Tech Choices

- **Bootstrap installer: POSIX `sh`/Bash** (`install.sh`). Responsibilities only: detect OS, ensure `python3` (>= 3.9) exists (install via the system package manager if missing, with consent), download a pinned release, verify checksum, install to `~/.local/share/devforge`, symlink to `~/.local/bin/devforge` (or `/usr/local/bin` when root), and print next steps.
- **Core: Python 3.9+, standard library only** for the runtime path (no pip dependencies at install time). This avoids bootstrap failures on sanctioned/offline networks. Optional niceties (e.g. `rich`) must degrade gracefully if absent.
- Use `subprocess` with argument lists, never `shell=True` with interpolated input.
- Type hints everywhere; `ruff` + `mypy` + `pytest` in CI; `shellcheck` + `shfmt` for shell.

## 4. Suggested Layout

```
install.sh                  # curl|bash bootstrap
devforge/
  __main__.py               # entry point
  cli.py                    # argparse, subcommands
  tui.py                    # interactive menus (stdlib fallback)
  core/
    system.py               # distro, arch, init system, desktop/server, root/sudo
    pkgmgr.py               # apt/dnf/yum/pacman/zypper/apk abstraction
    net.py                  # downloads, retries, resume, checksum, proxy
    mirrors.py              # mirror profiles and application
    dns.py                  # DNS inspect/set/restore
    state.py                # installed-state DB (JSON) + backups
    logging.py              # log file + console, secret redaction
    plan.py                 # dry-run plan/apply engine
  tools/
    base.py                 # Tool interface (below)
    node.py php.py go.py python.py docker.py ...
  data/
    mirrors/*.toml|json     # mirror definitions (community-editable)
    versions/*.json         # cached upstream version indexes
tests/
docs/
AGENTS.md  AGENTS.fa.md  README.md  CONTRIBUTING.md  LICENSE
```

Every tool implements one interface so adding a tool is a single file:

```python
class Tool(Protocol):
    name: str
    def detect(self) -> InstalledInfo: ...
    def available_versions(self) -> list[Version]: ...
    def install(self, version: str, *, make_default: bool) -> Plan: ...
    def update(self, version: str | None) -> Plan: ...
    def use(self, version: str, *, scope: Scope) -> Plan: ...   # global | project | shell
    def uninstall(self, version: str, *, purge: bool) -> Plan: ...
    def doctor(self) -> list[Check]: ...
```

## 5. Behavior Principles

- **Plan, then apply.** Every mutating command builds a plan, shows it, asks for confirmation (`-y/--yes` skips), and supports `--dry-run`.
- **Idempotent.** Running twice must be safe and fast.
- **Least privilege.** Prefer user-space installs (`~/.local`, per-user version dirs) over system-wide. Use `sudo` only when needed, and say why before asking.
- **Never destroy silently.** Back up config files before editing (`*.devforge.bak`); uninstall asks about purging data; no `rm -rf` on computed paths without a guard that the path is inside a DevForge-owned directory.
- **Prefer official sources**, verified: official tarballs/repos, GPG keys, SHA256 checksums. Never run unverified remote scripts without showing the source and checksum policy.
- **Version switching semantics** (example, Node.js 24 → 26): install 26 side by side, keep 24, set default to 26, per-project pin via `.nvmrc`/`.node-version`/`.tool-versions`, shims or PATH management that works in bash/zsh/fish, clean removal of 24 on request. Same model for PHP (CLI + FPM + `update-alternatives` where relevant), Go, Python.
- **Respect existing setups.** Detect nvm/pyenv/asdf/mise/distro packages already present; adopt or coexist instead of clobbering.
- **Shell integration** is explicit and reversible: managed block in rc files with begin/end markers.
- **Non-interactive mode** for CI/servers: every prompt has a flag; exit codes are meaningful; `--json` output for scripting.
- **Profiles/presets** (e.g. `web-php`, `node-fullstack`, `go-backend`, `devops`) and an exportable/importable config file so a user can rebuild a whole machine with one command: `devforge apply devforge.toml`.

## 6. Environment Detection ("Smart")

Detect and expose via `devforge doctor` / `devforge info`:

- Distro family, version, codename, arch (amd64/arm64), libc (glibc/musl)
- Package manager and init system (systemd/OpenRC/other), container/WSL/VM detection
- Desktop vs server: no `DISPLAY`/`WAYLAND_DISPLAY`, `systemctl get-default`, `XDG_CURRENT_DESKTOP`, installed DE packages. Treat as a hint, never a hard gate.
- Root/sudo availability, disk space, RAM, existing proxies, reachability of key upstreams (with timing)
- Unsupported/too-new distro versions: degrade with a clear message and fallback (e.g. official tarball instead of a missing third-party repo for brand-new releases like Ubuntu 26.04). Never fail with a stack trace.

## 7. Network Resilience: Mirrors and DNS

Goal: remain usable during sanctions, filtering, and unstable international connectivity.

- **Mirror profiles** in `data/mirrors/`, selectable: `devforge mirror list|set|test|reset`. Cover OS package repos (apt/dnf/pacman/etc.), npm registry, PyPI, Composer/Packagist, Go proxy (`GOPROXY`), Docker registry mirrors, GitHub release/download proxies, Maven, RubyGems, crates.
- Mirror lists are community-maintained data, not code. Do not hardcode vendor URLs in logic. Include a health-check (`mirror test`) that measures latency/throughput and can auto-pick the best, with user override. Mirrors are **opt-in**; default is upstream.
- Validate that mirrors serve correct content: keep checksum/GPG verification on even for mirrors.
- **DNS helper:** `devforge dns show|set|test|restore`. Presets are user-chosen (never silently changed). Detect the resolver in use (systemd-resolved, NetworkManager, resolvconf, static `/etc/resolv.conf`) and apply through the right mechanism; always back up and offer one-command restore.
- Downloads: retries with backoff, resume, multiple-source fallback, honor `HTTP(S)_PROXY`/`NO_PROXY`, offline cache directory.
- Do not bake in anything that depends on a single mirror operator staying online.

## 8. Docs, UX and Output

- English-only strings, centralized in one place for consistency. Use plain ASCII markers (`[ok]`, `[warn]`, `[err]`) with optional color; respect `NO_COLOR` and non-TTY output.
- Concise, actionable errors: what failed, why, what to try next.
- `devforge --help` and per-command help are complete and have examples.
- Log file at `~/.local/state/devforge/logs/`; secrets redacted.

## 9. Testing

- Unit tests for detection logic using fixture `os-release` files for many distros.
- Integration tests in containers across a matrix (Debian 12/13, Ubuntu 22.04/24.04/26.04, Fedora, Rocky/Alma, Arch, openSUSE, Alpine) via GitHub Actions.
- Test `install.sh` with `shellcheck` and in a clean container with and without `python3`.
- All mutating logic must be testable in `--dry-run` without root.
- Never run destructive tests on the host; use containers/VMs.

## 10. Security

- Installer served over HTTPS, pinned to release tags, with published SHA256 (and ideally signatures).
- No `eval` on remote content; no unquoted variables in shell; validate all version strings against strict regexes.
- Don't store credentials. No telemetry unless explicitly opt-in and documented.

## 11. Working Rules for Agents

1. Inspect the repo state before changing anything; don't overwrite existing work.
2. Build incrementally in this order: `core/system.py` (detection) → `pkgmgr` → `state`/`plan` → `net`/`mirrors`/`dns` → first tools (Node, Python, Go, Docker, PHP) → TUI → presets → packaging.
3. Each change ships with tests and updated docs. Keep both `AGENTS` files in sync.
4. Match existing style; keep functions small and typed; no new runtime dependencies without discussion.
5. Never run mutating system commands (package installs, DNS changes) on the developer's machine while developing; use dry-run, fixtures, or containers.
6. When requirements are ambiguous, state the assumption in the PR/commit description rather than guessing silently.
7. Open questions to confirm with the maintainer: final project name, license, minimum Python version, whether to manage versions via own shims or integrate with `mise`/`asdf`.
