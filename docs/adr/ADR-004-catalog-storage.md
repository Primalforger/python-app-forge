# ADR-004: Catalog storage

**Status:** Accepted (baseline for release 0.1.0)

## Context
Authoritative data is manifests and artifacts on disk; the index can always be rebuilt (`forge catalog rebuild`).

## Decision
SQLite metadata plus filesystem artifacts; the index is a cache

## Alternatives considered
JSON-only catalog; embedded key-value store.

## Consequences
Index corruption cannot lose catalog truth.

## Security implications
Artifact digests are verified on every scan; mismatches are quarantined.

## Migration strategy if reversed
Replace persistence.SqliteStore via the MetadataStore protocol.
