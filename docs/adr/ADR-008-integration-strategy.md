# ADR-008: Integration strategy

**Status:** Accepted (baseline for release 0.1.0)

## Context
Existing projects are the highest-risk target.

## Decision
Read-only analysis, then reviewed, approved, checkpointed, verified change plans

## Alternatives considered
Direct modification; Git-commit-based rollback.

## Consequences
No mutation before approval; unknown conflicts stop the operation; recovery never overwrites later user edits.

## Security implications
Plans are hash-checked; drift and tampering are detected.

## Migration strategy if reversed
Plans are stored in the platform home as JSON.
