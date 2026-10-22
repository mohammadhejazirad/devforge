# DevForge

**Version 1.0.0.** This is the first installable release. The command below
downloads the installer, which then downloads a pinned archive, checks its
SHA256, and installs the `devforge` command. This release prints help and
version. Language and service provisioning is not in 1.0.0 yet.

DevForge is a terminal-based provisioning and version-management tool for
developers on Linux, for both desktops and servers. After a fresh OS install,
you should be productive in minutes instead of hours.

## What it aims to do

- Install, update, switch, pin, and remove development tooling.
- Detect your distro, architecture, init system, and whether you are on a
  desktop or a server, without hardcoding any single distribution.
- Keep everything safe by default: plan first, show the commands, ask for
  confirmation, and support `--dry-run` for every mutating operation.
- Stay usable on slow, filtered, or sanctioned networks through opt-in,
  reversible mirror profiles and DNS switching.
- Never depend on a GUI, never require pip packages at install time, and never
  send telemetry.

## Requirements

- Linux (Debian/Ubuntu, Fedora/RHEL family, Arch/Manjaro, openSUSE, Alpine).
- Python 3.9 or newer, standard library only.

## Install

Linux and Python 3.9 or newer. Copy this command:

```bash
curl -fsSL https://raw.githubusercontent.com/mohammadhejazirad/devforge/main/install.sh | bash
```

The installer refuses anything except Linux. It downloads
`devforge-1.0.0.tar.gz` from the GitHub release, checks the SHA256 pinned in
`install.sh`, and installs into `~/.local` (or `/usr/local` when run as root).
It does not run any other remote script. If `~/.local/bin` is not on `PATH`,
the installer prints the export line to add.

To install from a checkout instead:

```bash
python3 -m devforge --help
```

## Usage

All output is English, and every mutating command will follow the same flow:
build a plan, show it, ask for confirmation (`-y` to skip), and support
`--dry-run`.

```bash
devforge --help
devforge --version
```

Useful global flags:

- `--dry-run`: show what would happen without changing the system.
- `-y`, `--yes`: skip confirmation prompts.
- `--json`: machine-readable output for scripting.
- `--no-color`: disable color; `NO_COLOR` is honored too.
- `-q`, `--quiet` and `-v`, `--verbose`: control the amount of output.

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
ruff check .
mypy
```

The runtime path uses only the Python standard library. Dev tools (ruff, mypy,
pytest) live in the optional `dev` extra and are never needed to run DevForge.

Layout:

```
devforge/
  cli.py            argument parsing and dispatch
  commands/         one module per subcommand
  core/             detection, package managers, state, plan, net, mirrors, dns
  tools/            one module per managed tool
  data/             community-editable mirror and version data
tests/
docs/
```

## Safety model

- Every mutating action is planned, displayed, and confirmed before it runs.
- Configuration files are backed up before they are edited.
- Deletions are refused unless the path is inside a DevForge-owned directory.
- Mirrors and DNS changes are opt-in and always reversible.
- Secrets are redacted from logs, which live in `~/.local/state/devforge/logs/`.

## Contributing

See `CONTRIBUTING.md`. The English specification in `.docs/AGENTS.md` is the
source of truth for behavior.

## License

MIT. See `LICENSE`.

