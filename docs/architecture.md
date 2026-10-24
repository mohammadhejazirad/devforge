# Architecture notes

This document records decisions that are not obvious from the code.

## Layering

```
cli.py            parses arguments, builds a Printer and a Context, dispatches
commands/         thin adapters: parse options, call core, return an exit code
tui.py            numbered menu; opened by a bare `devforge` on a terminal
core/             detection, package managers, state, plan, net, mirrors, dns
tools/            catalog, the shared engine, and one thin module per tool
data/             catalog, version indexes, mirror profiles, DNS presets, presets
```

Nothing in `core/` or `tools/` writes to the terminal directly. They return
plans and data; `commands/` and the TUI render them. This keeps every mutating
path testable in `--dry-run` without root.

## Tool strategies

`data/catalog.json` is the list of tools. `tools/engine.py` turns a catalog
record into a plan. Strategies:

- `archive`: official tarball or file, checksum, side-by-side directory, shim.
- `package`: distro package. An explicit version uses `versioned_packages`
  when that family has them.
- `external`: detect nvm or pyenv and refuse to install or remove them.
- `npm`: delegate to the Node install; update uses an npm selector restricted to the current major release.
- `rustup`: checksummed `rustup-init` under the data directory, or the
  rustup already on `PATH` when it is not one of our shims.

A file format such as kubectl is copied after the checksum check. It is not
passed to tar. Alpine gets a musl build when the catalog has one, and a note
when the only build is glibc.

## Side effects are injectable

Detection reads `/etc/os-release` and runs commands. Both are injectable:

- the os-release path is a parameter, so tests read fixtures;
- system commands go through a runner object, so tests record commands instead
  of executing them.

## State directories

All DevForge paths follow the XDG base directory spec, with fallbacks:

- data: `$XDG_DATA_HOME/devforge` or `~/.local/share/devforge`
- state and logs: `$XDG_STATE_HOME/devforge` or `~/.local/state/devforge`
- config: `$XDG_CONFIG_HOME/devforge` or `~/.config/devforge`
- cache: `$XDG_CACHE_HOME/devforge` or `~/.cache/devforge`

`core/paths.py` owns these paths and provides the deletion guard used before any
`rm -rf`, so destructive operations can only touch DevForge-owned directories.

## Terminal output

Text is centralized in `devforge/strings.py`. Markers are plain ASCII
(`[ok]`, `[warn]`, `[err]`, `[info]`) and color is added only when the stream is
a TTY, `NO_COLOR` is unset, `TERM` is not `dumb`, and `--no-color` was not
passed. Non-TTY output never contains escape codes.

## Logging module name

The logging helper is `core/log.py`, not `core/logging.py`, so it can never
shadow the standard library `logging` module.

## Release-line policy

`update` preserves major.minor for PHP, Python, and Go, and major for other
indexed tools. `install <tool> <version>` explicitly changes the line; partial
archive versions resolve to a complete published version. `use` selects an
installed version, while project and shell pins may retain a prefix. Rust
updates an active stable channel; explicitly pinned toolchains stay pinned.

Online archive updates refresh their index before selecting a release. Dry runs
use local indexes. Missing older-line discovery is reported as blocked rather
than silently moving to the latest major. Package updates refresh repositories
first, validate runtime candidate lines at apply time, then invoke the native
upgrade. Package epochs and revisions are retained for status comparisons.

Archive extraction stages into a fresh directory and permits only internal
symlinks, created after regular files and checked again as a complete graph.
A completed-install marker is written after the executable layout is verified.
Interrupted or incomplete directories are excluded from version selection.

The bootstrap installer pins the published release, not the current working
tree. Release preparation builds a new versioned archive, updates its pin, and verifies
the exact digest in tests. Existing published release hashes are never rewritten.
