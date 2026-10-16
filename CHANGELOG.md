# Changelog

All notable changes to `meshapi-contract` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is semantic.

## [0.1.0] — 2026-10-16

### Added
- Pure public-contract differ: `classify_changes`, `public_subset`,
  `published_a_new_version`, `render`, `operations`, and the `Change` record.
- Public-subset projection (`/v1/*` minus `x-internal`) with unreachable-schema
  pruning, mirroring what the docs pipeline publishes.
- Test suite covering change classification and public-subset pruning.
- CI matrix across supported Python versions (3.10–3.13).
