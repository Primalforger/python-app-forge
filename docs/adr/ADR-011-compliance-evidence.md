# ADR-011: Compliance evidence

**Status:** Accepted (baseline for release 0.1.0)

## Context
A file existing is never proof of verification.

## Decision
Requirements register in TOML; status computed only from retained evidence

## Alternatives considered
Single compliance percentage.

## Consequences
Eight explicit statuses; reports state that they are not certifications.

## Security implications
Evidence is stored with run IDs; export includes a SHA-256 manifest.

## Migration strategy if reversed
Evidence rows are append-only in SQLite.
