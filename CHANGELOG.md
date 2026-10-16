# Changelog

All notable changes to `meshapi-contract` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is semantic.

## [0.2.1] — 2026-10-16

### Added
- `--baseline PATH` allowlist for the gate (`{"allow": [<row>, ...]}`): listed missing
  rows are suppressed, new ones still fail, stale entries are reported on stderr.

### Fixed
- Package version metadata (`pyproject.toml`) now matches the release.

## [0.2.0] — 2026-10-16

### Added
- Typed-surface engine: `Surface`, `expected_surface`, `actual_surface_from_json`,
  `diff_surface`, `load_actual` — projects a public spec to a `{(model, field)} ∪ {param}`
  set and reports members an SDK is missing. Follows nested `$ref`s (properties,
  array items, `additionalProperties`, composition) with a cycle guard.
- Drift-gate entrypoint `python -m meshapi_contract.gate` with distinct exit codes
  (0 clean, 1 drift, 3 version mismatch, 4 operational error).

## [0.1.0] — 2026-10-16

### Added
- Pure public-contract differ: `classify_changes`, `public_subset`,
  `published_a_new_version`, `render`, `operations`, and the `Change` record.
- Public-subset projection (`/v1/*` minus `x-internal`) with unreachable-schema
  pruning, mirroring what the docs pipeline publishes.
- Test suite covering change classification and public-subset pruning.
- CI matrix across supported Python versions (3.10–3.13).
