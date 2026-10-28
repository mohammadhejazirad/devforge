# DevForge

DevForge installs, updates, switches, pins, and removes development tools on
Linux. It detects the machine, shows a plan, and changes the system only after
you confirm. The same commands work on a desktop and on a server.

The current release is **version 1.4.0**. Administration and backup details are in
[docs/administration.fa.md](docs/administration.fa.md). It manages languages, package tools,
infrastructure, databases, and everyday utilities. A Persian walkthrough is in
[docs/guide.fa.md](docs/guide.fa.md).

## Requirements

- Linux. Tested families: Debian/Ubuntu (including Mint and Pop!_OS),
  Fedora/RHEL (Rocky, Alma, CentOS Stream), Arch/Manjaro, openSUSE, and Alpine.
- Python 3.9 or newer. The full-screen interface uses Textual 8.x.
  Core commands and the numbered fallback still run without UI dependencies.
- A normal user with `sudo` for distro packages. Official archives install
  into your home directory and do not need root.

## Install

### From a checkout (version 1.4.0)

```bash
git clone https://github.com/mohammadhejazirad/devforge.git
cd devforge
python3 -m devforge --help
uv run devforge
```

You can also install the checkout as a command:

```bash
python3 -m pip install --user -e .
devforge --version
```

That prints `devforge 1.4.0` from this tree.

### Release installer (1.4.0)

Download and run the versioned installer:

```bash
curl -fsSLo install-devforge.sh https://github.com/mohammadhejazirad/devforge/releases/download/v1.4.0/install.sh
bash install-devforge.sh
```

Existing installations can run `devforge self-update`. The installer pins the
deterministic 1.4.0 archive and verifies its SHA256 before extraction.

The installer verifies SHA256 and uses an isolated Python launcher. Reinstalling
preserves `tools/`, `shims/`, and `env.sh`.

If you still have the old 1.0.0 command, run `install.sh` once more. That
release cannot update itself. From 1.1.0 on, use `devforge self-update`.

Release 1.4.0 adds the Textual interface, opt-in terminal personalization, database
backups, KVM management, and safer service administration. See [CHANGELOG.md](CHANGELOG.md).

## What you can manage

| Kind | Tools |
| --- | --- |
| Languages | PHP, Node.js, Go, Python, Rust, Java, Ruby, .NET, Bun, Deno |
| Package tools | NVM, npm, pnpm, Yarn, Composer, pipx, uv, pyenv |
| Infrastructure | Docker and Compose, Git, kubectl, Helm, Terraform |
| Services | MySQL, MariaDB, PostgreSQL, MongoDB, Redis, Nginx, Caddy |
| Virtualization | KVM/QEMU/libvirt, virt-manager (`kvm-gui`, desktop only) |
| Terminal | Zsh, Starship, selectable local-history suggestions and syntax highlighting |
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
  packages on Debian (`php8.4-cli`) and Alpine (`php84`). A family without versioned packages refuses an explicit version it cannot select.
  Packages must exist in the configured repositories; DevForge does not add PHP repositories.

DevForge does not replace `/usr/bin/python3`. A Python shim selects
`python3.13` and leaves the system `python3` alone. PHP and Java alternatives
are planned only on Debian, and only when the target binary exists. A missing
alternative, such as `php-fpm` when only `php-fpm8.5` is on disk, is registered
and then selected. An alternative that is already registered is selected
without being registered again.

NVM and pyenv are detected and left alone. DevForge will not run their remote
installers. npm is the npm that ships with Node: `devforge install npm` installs Node automatically when it is missing.
`devforge update npm` updates within the installed npm major release.
Composer installs PHP automatically when missing; Yarn installs Node. Rust is installed with the official `rustup-init`
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
`update php` installs it when missing. Otherwise it refreshes the package indexes
and upgrades the installed PHP line, including distro security revisions. It
checks candidates after refreshing and refuses a different release line. The
newest available package depends on the configured distro repositories; it may
lag the newest release on php.net. `update` with no name requires `--all`, and `--all` only touches
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

Run `devforge` with no arguments in a terminal to open the Textual interface.
Choose Tokyo Night, Catppuccin, Nord, Dracula or Light from the theme selector.
Choose a category, a tool, then an operation. Database backups and saved-backup
lists live under each database; service controls live under each service. Nginx
also has a configuration submenu. Installed-version selection uses detected
versions, rather than the download index. `devforge tui` opens the same menu.
The interface works over SSH. `devforge tui --plain` uses the numbered fallback,
which is also selected when Textual is unavailable or `TERM=dumb`. Colors respect
`NO_COLOR` and `--no-color`. Every change defaults to **No**, including end-of-input.

```bash
devforge backup mysql app
devforge backup mariadb
devforge backup postgresql app
devforge backup mongodb app --client-config ~/.config/mongodb/dump.yml
devforge backup redis
devforge service nginx status
devforge config nginx check
devforge --dry-run config nginx apply ./edited-nginx.conf
devforge --dry-run install kvm
devforge install kvm-gui
```

Backups use installed native clients and their authentication configuration.
They stream to private files in `~/.local/state/devforge/backups/<engine>/`;
failed or empty dumps are not published. PostgreSQL needs a database name and
Redis backs up the whole instance. Dumps are unencrypted and consistency depends
on the database's workload and deployment. See the
[administration guide](docs/administration.fa.md) for limitations and client setup.

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

`install node` selects the current LTS release. Online installs with no version
or a partial version, and online archive updates, refresh the upstream index
when one is configured. Dry runs use known data and do not refresh it.
`update node` selects the newest stable release in the installed major line.
For example, Node 22 stays on 22; `install node 24` explicitly changes the line.
PHP, Python, and Go retain major.minor; other indexed archive tools retain major.
A refresh failure blocks the operation instead of claiming the tool is up to date.
Indexes that expose only the latest release cannot discover older-line patches;
these updates stop when no matching release is known.
`status` separates `update_target` from `new_release_available` in JSON.
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
- Config edits keep the first `*.devforge.bak`; Nginx config replacement validates
  before and after writing, and restores preceding contents on validation failure.
- Package removal checks installed packages. On apt, a dependency simulation is
  shown and protected dependency removals are refused. Distro Python removal is blocked.
- Arch operations never run `pacman -Sy`; run a full `pacman -Syu` yourself first.
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

Review scope and remaining constraints: [docs/safety.md](docs/safety.md).

## Terminal studio

Zsh, history suggestions, syntax highlighting, native Zsh themes and Starship
are separate choices. No component is selected for installation by default.
Selecting a theme does not implicitly install its shell or prompt engine.
Open **Terminal studio** in the sidebar or use:

```bash
uv run devforge terminal install-zsh
uv run devforge terminal autosuggestions
uv run devforge terminal zsh-theme --theme midnight
uv run devforge terminal install-starship
uv run devforge terminal starship-theme --theme server
```

Existing `.zshrc` content is preserved outside a backed-up managed block;
changing the login shell is a separate, explicit action. Plugin archives have
pinned SHA256 checksums and Starship uses official verified musl builds.
See [the terminal guide](docs/terminal.fa.md) for choices, removal, distro support
and the review of the supplied setup-zsh.sh reference. The release installer
creates an isolated Textual runtime; set `DEVFORGE_INSTALL_TUI=0` for CLI-only
installation. A missing venv/PyPI connection produces actionable fallback output.
