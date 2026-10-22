# Mirror profiles

Community-maintained mirror definitions live here as JSON files, one file per
profile group (for example `iran.json`, `global.json`).

Rules:

- Data, not code. Vendors and URLs must not be hardcoded in Python logic.
- Mirrors are opt-in. The default is always the upstream source.
- Every entry must record which ecosystem it covers (OS packages, npm, PyPI,
  Composer, Go, Docker registry, GitHub releases, Maven, RubyGems, crates).
- Entries should say whether they are verified. Unverified entries are shown
  with a warning until a maintainer reviews them.
- Checksum and GPG verification stays on even when a mirror is in use.

No profiles are shipped yet; they are added in the mirrors phase.

