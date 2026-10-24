# Changelog

## 1.3.0 — 2026-10-24

Updates now preserve the active release line. PHP, Python, and Go retain
major.minor; Node and other indexed archive tools retain major. Use
`install <tool> <version>` to change release lines explicitly, and `use` to
select a version that is already installed.

- Refresh upstream indexes automatically for online archive updates and
  installs with an omitted or partial version. Dry runs use local indexes.
- Refresh distro package indexes before updating and check runtime candidates
  before upgrading. Retain package revisions so backported security fixes are
  visible. Report current-line update targets separately from newer lines.
- Fix Node archive root detection and support safe internal symlinks for npm
  and npx. Stage extraction and verify the executable layout before marking
  an install complete. Exclude incomplete installs from version selection.
- Resolve partial archive versions and project pins to matching full versions.
- Install Node automatically for missing npm and Yarn, and PHP for Composer.
  Keep npm updates within the installed major version.
- Preserve managed Rust homes in shims and update an active stable channel
  without changing explicitly pinned toolchains.
- Let the bootstrap installer download, hash, and extract using Python when
  download/checksum/archive utilities are absent. Keep its launcher bound to
  the resolved bootstrap interpreter.
- Report unknown update status accurately and return failure from
  `update --all` when some installed tools cannot be updated.

PHP remains installed from the configured distro repositories; their newest
package may lag php.net. Some upstream indexes expose only the latest release,
and some tools require pinned checksums for new downloads. Unsupported updates
stop rather than silently switching to another release line.

Existing users can run `devforge self-update`. Reinstalling also preserves
managed tools, shims, and shell configuration.
