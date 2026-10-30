# ADR-006: Python packaging

**Status:** Accepted (baseline for release 0.1.0)

## Context
Do not invent a replacement for Python package metadata.

## Decision
Standard pyproject.toml; extension discovery via entry points

## Alternatives considered
Custom project descriptor only.

## Consequences
Generated projects use PEP 621 metadata. Extensions use the `app_forge.plugins` entry-point group.

## Security implications
Discovery does not import or authorise extension code.

## Migration strategy if reversed
n/a
