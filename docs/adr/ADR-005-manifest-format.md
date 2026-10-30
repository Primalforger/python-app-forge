# ADR-005: Manifest format

**Status:** Accepted (baseline for release 0.1.0)

## Context
Human-maintained, readable with stdlib tomllib.

## Decision
Versioned, schema-validated TOML (schema_version = 1)

## Alternatives considered
JSON/YAML manifests.

## Consequences
Validation lives in domain/models.parse_manifest and rejects missing or unsafe values; nothing is inferred from component code.

## Security implications
Destination paths with '..' or absolute paths are rejected at manifest validation and again at plan time.

## Migration strategy if reversed
Bump schema_version and add a parser alongside the old one.
