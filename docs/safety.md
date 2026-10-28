# Administration safety review — 2026-10-28

This review accompanies the 1.4.0 implementation. It is a source review and a
regression-test pass, not certification that every package/version combination
on every Linux distribution has been exercised. Actual installs, removals,
network changes and database restores were not run on the user's host.

## Changes addressing concrete failure modes

- Confirmation used to accept EOF through its default. EOF now declines and
  the normal default is No. `--yes` remains an explicit automation override.
- State, download, configuration and release metadata writes used predictable
  temporary paths or direct truncation. Replacements now use exclusive temporary
  files and atomic rename where the current user owns the destination.
- Log appends could follow symlinks. Files now open with `O_NOFOLLOW`, validate
  regular-file type and set permissions through the open descriptor.
- Install/update launchers inherited `PYTHONPATH` and the working-directory
  import context. Generated launchers now start isolated Python with a quoted,
  explicitly inserted installation directory. Installer launcher replacement is atomic.
- Package removal assumed every catalog package was installed. Installed-package
  queries filter absent packages; distro Python removal is blocked. apt removals
  show a native simulation and block protected dependency removals before approval.
  Removal of versioned packages defaults to the detected installed release line.
- apt installs/upgrades use `--no-remove` to refuse dependency resolution that
  would remove packages, including database engine swaps.
- `pacman -Sy` followed by selected-package installation could create partial
  upgrades. DevForge now checks the package database without refreshing it;
  operators perform `pacman -Syu` first, explicitly, with the native tool.
- Direct system configuration writes failed for normal users despite command
  steps using sudo. Allowlisted system writes/backups/restores now use privileged
  native operations. Symlinked system configuration writes are refused.
- NetworkManager DNS restoration previously restored resolv.conf without undoing
  persistent connection settings. DNS and ignore-auto-dns are now snapshotted and
  restored. systemd-resolved per-link DNS servers are also saved and restored
  without resetting unrelated link properties. Connection activation can interrupt
  a network session; use local access or a maintenance window on remote hosts.
- Database backups now stream binary output to private files, refuse symlink
  backup directories and existing destinations, discard failed/empty dumps, and
  redact failure diagnostics. Redis uses the native RDB download operation.
- MySQL version matching no longer mistakes a compatibility client protocol
  number for the server/client release. MariaDB matching selects its MariaDB release.
  Redis and MySQL service names account for Debian and RHEL differences.
- Database package installation no longer adds a follow-up automatic start step
  for servers that may need initialization. Native package installation scripts
  can still start services according to distro policy. Existing data is not initialized.
- Nginx configuration changes validate the candidate and the installed config,
  and restore the preceding contents on validation failure. Reload is explicit.
- Administrative executables are detected in standard sbin locations even when
  a desktop user's PATH omits them. Native query output uses the C locale.

## Verification scope

Regression coverage includes dry runs, binary streaming, failed/empty dump
cleanup, restrictive permissions, exclusive publication, unsafe database names,
MongoDB config privacy, symlink attacks against temporary/log paths, EOF,
Nginx candidate rejection and rollback, versioned-package removal, protected apt
dependencies, desktop/server KVM behavior and DNS restoration. Existing archive,
version-selection, path-containment and installer tests remain enabled.

The actual host was inspected read-only: Ubuntu 26.04 desktop, Nginx 1.28.3,
libvirt 12.0.0 and virt-manager 5.1.0 were detected. apt removal simulation for
Nginx selected only `nginx`; no removal was applied. Database client availability
was checked through dry runs; `pg_dump` was absent.

## Boundaries that operators must retain

- Distro support is a mapping of package names and injected command tests. Live
  installation matrices across releases, architectures, systemd/OpenRC variants
  and configured repositories remain necessary before a production rollout.
- Native package managers own dependency resolution and transaction locks.
  DevForge never deletes locks or force-repairs a package database. A dry-run
  simulation can become stale if another administrator changes packages later.
  Dependency previews/protection are currently implemented for apt only.
- Database backup consistency depends on engine, storage type and concurrent
  writes. PostgreSQL dumps exclude cluster roles; MongoDB dumps do not enable
  oplog capture. Redis snapshots cover the full instance. These are logical/RDB
  backup workflows, not PITR or cluster-wide disaster-recovery guarantees.
- Backups are unencrypted, local and not automatically expired or copied
  off-host. There is no restore, scheduler or retention menu in this version.
  Successful dump creation is not proof of successful restoration: run isolated
  restore drills with matching native clients and documented procedures.
- General configuration editing is not implemented. The validated replacement
  workflow handles Nginx's main file only, not transactions across its includes.
  Validation runs trusted configuration with elevated privileges, as Nginx
  requires. Unexpected shutdown between write and validation is not transactional.
- KVM management covers package lifecycle and a legacy libvirtd service control,
  not VM disk/network/snapshot lifecycle. Modular libvirt installations require
  native socket management. Hardware virtualization and permissions remain host
  prerequisites; the doctor checks `/dev/kvm` availability/access.
- MongoDB installation requires an already configured vendor repository on
  Debian/RHEL. Unsupported repository/family combinations are blocked rather
  than silently adding third-party repositories or remote installation scripts.
- Whole multi-step plans are not filesystem/package transactions. A later failed
  step does not roll back already completed package installations. Inspect the
  failed step and native package/service state before retrying.
- SHA256 verifies downloaded artifact integrity. Checksums fetched from the same
  publisher are not an independent signature/trust mechanism. Release publication
  and external supply-chain review are separate from this local change.
