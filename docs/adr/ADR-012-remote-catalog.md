# ADR-012: Remote catalog

**Status:** Accepted (baseline for release 0.1.0)

## Context
Offline operation is a core requirement.

## Decision
Optional future capability; no runtime dependency

## Alternatives considered
Mandatory remote registry.

## Consequences
Remote-known components appear as 'remote_unavailable'; nothing is downloaded silently. No online refresh is implemented in this release.

## Security implications
No hidden network activity.

## Migration strategy if reversed
Add a fetcher that writes verified artifacts into a catalog root.
