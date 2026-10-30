# ADR-010: Persistence abstraction

**Status:** Accepted (baseline for release 0.1.0)

## Context
Replaceable storage per the spec.

## Decision
SQLite behind the MetadataStore protocol

## Alternatives considered
Direct sqlite3 use across modules.

## Consequences
Only persistence.py imports sqlite3 (architecture-checked).

## Security implications
Parameterised SQL only.

## Migration strategy if reversed
Implement the protocol for another backend.
