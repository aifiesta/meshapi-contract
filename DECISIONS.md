# Decisions

## Why this package exists
The public-contract differ was extracted from the API service so two consumers —
the service's own CI and the release orchestrator — share one definition of what
counts as a breaking change. A differ that lived in only one of them would let the
two disagree, which is the drift this package prevents.

## Pure, no service imports
Everything here is stdlib-only and imports nothing from the originating service.
The one function that needed the live app to build a spec stayed behind in the
service; this package operates on spec dicts that are passed in.

## Public repo
This package is consumed by public SDK CI, so the repo is public. It carries no
internal hostnames, no tracker IDs, and no internal service names in shipped
source. The OpenAPI extension key `x-internal` appears only because the
public-subset filter reads it; it is a published OpenAPI convention, not an
internal reference.
