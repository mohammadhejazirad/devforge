# DevForge

DevForge installs, updates, switches, pins, and removes development tools on
Linux. It detects the machine, shows a plan, and changes the system only after
you confirm. The same commands work on a desktop and on a server.

This tree is **version 1.1.0**. It manages languages, package tools,
infrastructure, databases, and everyday utilities. A Persian walkthrough is in
[docs/guide.fa.md](docs/guide.fa.md).

## Requirements

- Linux. Tested families: Debian/Ubuntu (including Mint and Pop!_OS),
  Fedora/RHEL (Rocky, Alma, CentOS Stream), Arch/Manjaro, openSUSE, and Alpine.
- Python 3.9 or newer. The program uses only the standard library.
- A normal user with `sudo` for distro packages. Official archives install
  into your home directory and do not need root.

## Install

### From a checkout (version 1.1.0)

```bash
git clone https://github.com/mohammadhejazirad/devforge.git
cd devforge
python3 -m devforge --help
```

You can also install the checkout as a command:

```bash
python3 -m pip install --user -e .
devforge --version
```

That prints `devforge 1.1.0` from this tree.

### Published installer (release 1.1.0)

```bash
curl -fsSL https://raw.githubusercontent.com/mohammadhejazirad/devforge/main/install.sh | bash
```

`install.sh` downloads `devforge-1.1.0.tar.gz` from the GitHub release, checks
the SHA256 pinned in the script, and installs into `~/.local` (or `/usr/local`
when run as root). It does not run any other remote script. Running it again
replaces the program and leaves `tools/`, `shims/`, and `env.sh` in place.

If you still have the old 1.0.0 command, run `install.sh` once more. That
release cannot update itself. From 1.1.0 on, use `devforge self-update`.

## What you can manage

| Kind | Tools |
| --- | --- |
| Languages | PHP, Node.js, Go, Python, Rust, Java, Ruby, .NET, Bun, Deno |
| Package tools | NVM, npm, pnpm, Yarn, Composer, pipx, uv, pyenv |
| Infrastructure | Docker and Compose, Git, kubectl, Helm, Terraform |
| Services | MySQL, MariaDB, PostgreSQL, Redis, Nginx, Caddy |
| Utilities | build tools, curl, jq, tmux, ripgrep, OpenSSH |

For every tool, DevForge can show what is installed, list known versions, and
say whether an update exists. Install, update, switch the default, pin a
project, uninstall, and doctor are available wherever that action is safe.

Two kinds of install:

- **Archives** (Node, Go, Bun, Deno, pnpm, Yarn, Composer, uv, kubectl, Helm,
  Terraform) live side by side under `~/.local/share/devforge/tools`. A shim
  directory is added to `PATH`. Installing Node 24 keeps Node 22.
- **Distro packages** (PHP, Python, Java, Ruby, databases, Nginx, Docker, and
  the utilities) use apt, dnf, yum, pacman, zypper, or apk. `install php`
  installs the distro default. `install php 8.4` asks for the versioned
  packages on Debian (`php8.4-cli`) and Alpine (`php83`). Other families get
  the single distro package and a note when the requested version may differ.

DevForge does not replace `/usr/bin/python3`. A Python shim selects
`python3.13` and leaves the system `python3` alone. PHP and Java alternatives
are planned only on Debian, and only when the target binary exists. A missing
alternative, such as `php-fpm` when only `php-fpm8.5` is on disk, is registered
and then selected. An alternative that is already registered is selected
without being registered again.

NVM and pyenv are detected and left alone. DevForge will not run their remote
installers. npm is the npm that ships with Node: `devforge update npm` runs
`npm install -g npm@latest`. Rust is installed with the official `rustup-init`
binary after a checksum check, into the DevForge data directory, unless you
already have rustup. .NET is installed from distro packages only. On Debian
and Alpine, where the SDK is not in the default repositories, the plan is
blocked instead of adding a third-party apt source.

## Everyday commands

Global flags come before the command. Every change supports `--dry-run` and
asks before it runs. `-y` skips the question. `--json` prints a JSON document
on stdout.

```bash
devforge info
devforge doctor --offline
devforge list
devforge status
devforge status php
devforge versions node
devforge versions node --refresh
devforge --dry-run install node
devforge install php 8.4
devforge use node 24.22.1
devforge pin python 3.13
devforge update php
devforge update --all
devforge uninstall node 22.23.4
devforge shell install
devforge shell remove
devforge
devforge self-update
```

`status php` prints the installed version, where it came from (`system` or
`devforge`), the newest version DevForge knows, and whether you can install,
update, switch, or uninstall it. A missing tool is reported as not installed.
`update php` installs it when it is missing, upgrades the distro package when
a newer candidate exists, and prints "already up to date" when nothing newer
is known. `update` with no name requires `--all`, and `--all` only touches
tools that are already installed.

`use` defaults to a user-wide default. `--project` and `pin` write the tool's
pin file (for example `.php-version`) and a `.tool-versions` line in the
current directory. `--shell` prints an `export` and writes nothing.

`doctor` warns about missing tools. It exits 1 when a selected DevForge
version is missing on disk. Network checks run only with `devforge doctor
--online`. asdf and mise are noted when their directories exist, and they are
not modified.

`export` prints a JSON manifest of what is installed. `apply` installs from
that file. A small TOML subset also works:

```json
{
  "tools": {
    "node": {"version": "24.22.1", "default": true},
    "git": {}
  }
}
```

```toml
[tool.node]
version = "24.22.1"
default = true

[tool.git]
```

Presets install a known set in one plan. If any tool in the preset is blocked,
the whole preset is blocked.

```bash
devforge preset list
devforge --dry-run preset apply web-php
```

| Preset | Tools |
| --- | --- |
| `web-php` | php, composer, node, nginx, git, curl |
| `node-fullstack` | node, pnpm, git, curl |
| `go-backend` | go, git, docker |
| `devops` | docker, kubectl, helm, terraform, git, jq |

Run `devforge` with no arguments in a terminal to open the menu. It lists every
tool, what is installed, and the actions below. Pick a number to install,
update, switch, pin, or remove that tool. Pick a letter for this computer,
doctor, presets, mirrors, DNS, shell setup, or a DevForge update.

```text
DevForge 1.1.0
  Ubuntu 24.04 (debian) | apt

Tools  (enter a number)
  Languages
     1  php          8.3.6  (newer 8.5)
     2  node         not installed
Actions  (enter a letter)
   g  Update DevForge
   0  Exit
Choice:
```

Open PHP in that menu and choose **Install PHP extensions**. The list is grouped
(databases, images, cache, and the rest) and every package uses the PHP line
that is already installed: PHP 8.5.12 installs `php8.5-*`, not another line.
Press Enter to install all of them. Enter inside a category installs that
category. Packages the distro does not publish for that exact line are left out.

When a newer GitHub release exists, the menu says so on that first screen.
`devforge self-update` downloads it, checks `SHA256SUMS`, and replaces only the
program files. A git checkout is not overwritten; update that copy with
`git pull`. Flags without a command, and `devforge` with no terminal, still
print help and exit 2. `devforge tui` opens the same menu.

## Versions DevForge already knows

Indexes in `devforge/data/versions/` are refreshed with `versions <tool>
--refresh` when the tool publishes an index. Pinned checksums cover the
builds that were current on 2026-10-23, including Node 26.12.1, 24.22.1,
22.23.4, and 20.20.2; Go 1.27.3 and 1.26.10; PHP 8.5, 8.4, 8.3, and 8.2;
Python 3.14, 3.13, 3.12, and 3.11; Java 25, 21, and 17.

`install node` selects the LTS line (24.22.1). `update node` moves to the
newest known version when that version is newer than the one you have.
`install node 26.12.1` selects that version and keeps the others. A download without a pinned checksum fetches
the publisher's checksum file at apply time. Dry-run shows that. DevForge will
not install an archive it cannot hash.

Go's download URL is `https://go.dev/dl/...`, which redirects to the Go CDN.
In some regions that CDN returns 404. DevForge reports the download error and
points at `devforge mirror list`. It does not treat the 404 as "this version
does not exist," and it does not invent a mirror.

## Mirrors and DNS

Both are off until you ask. The default is the upstream URL, and checksums
stay on.

```bash
devforge mirror list
devforge mirror set iran
devforge mirror test
devforge mirror reset
devforge dns show
devforge dns set cloudflare
devforge dns test
devforge dns restore
```

`iran` is an unverified community profile. It can add Docker registry mirrors
(`docker.arvancloud.ir`, `docker.iranserver.com`) to `/etc/docker/daemon.json`
after a backup. It does not rewrite apt, dnf, npm, or PyPI. `mirror reset`
clears the choice and restores `daemon.json` from `daemon.json.devforge.bak`
when that backup exists.

DNS presets: Cloudflare and Google are marked verified. Shecan, Electro,
Begzar, and 403 are unverified community presets. A `10.x` address only works
on networks that route to it. DevForge detects systemd-resolved,
NetworkManager, resolvconf, or a static `resolv.conf`, backs up the file, and
`dns restore` puts the backup back. If a link or connection name cannot be
detected, the plan stops and tells you what to do by hand.

## Safety

- Plans show the exact command. Root steps are prefixed with `sudo --` and a
  reason when you are not root.
- Config edits keep the first `*.devforge.bak`.
- Deletes are refused unless the path is inside a DevForge data, state,
  config, or cache directory.
- Version strings are checked before they are used in a path or a command.
- Commands are argument lists. The program does not use a shell.
- There is no telemetry.
- Shell integration is a marked block in `.bashrc`, `.zshrc`, or fish
  `config.fish`. `devforge shell remove` deletes that block and leaves the
  rest of the file.

Exit codes: `0` success, `1` a blocked plan, a failed step, or a declined
confirmation, `2` incorrect usage.

## Paths

| Purpose | Location |
| --- | --- |
| Tools and shims | `~/.local/share/devforge` |
| Logs | `~/.local/state/devforge/logs/devforge.log` |
| Config | `~/.config/devforge/config.json` |
| Cache | `~/.cache/devforge` |

`XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CONFIG_HOME`, and `XDG_CACHE_HOME`
override those defaults. Logs redact passwords, tokens, and URL credentials.

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
ruff check .
mypy
```

The dev tools are never required to run DevForge. See `CONTRIBUTING.md` and
`docs/architecture.md`.
