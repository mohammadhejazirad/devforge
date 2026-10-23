# Mirror profiles

Community-maintained mirror definitions live here as JSON files, one file per
profile. `upstream.json` is the empty default. `iran.json` is an unverified
opt-in profile.

Rules:

- Data, not code. Applying a profile only rewrites URLs that the file lists.
- Mirrors are opt-in. The default is always the upstream source.
- Every rewrite records its ecosystem. A prefix rewrite needs both an upstream
  and a mirror, and both must be `https` URLs.
- Unverified profiles are shown with a warning.
- Checksum verification stays on even when a mirror is in use.
- Do not add an apt, dnf, npm, or PyPI URL until someone has checked that it
  serves the same bytes as the upstream.

`iran.json` only lists Docker registry prefixes. It does not change distro
package repositories. `devforge mirror set iran` can also merge those mirror
URLs into `/etc/docker/daemon.json` after a backup.

