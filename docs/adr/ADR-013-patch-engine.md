# ADR-013: Marker-based patch engine

**Status:** Accepted

## Context
Components could only add new files, so they could not register a route, add a command, or add configuration. The spec requires extension points and registration steps, and requires edits to remain reviewable and recoverable.

## Decision
Components declare patches. `insert` adds a marked block at a `forge:anchor` line; `toml-table` adds marker-managed tables; structured TOML, JSON, and YAML merge operations record ownership of Forge-added values. Applied patch metadata is stored in `.forge/components.toml`. Planning remains side-effect free, and apply/recovery use the existing reviewed transaction path.

## Alternatives considered
AST-based Python rewriting (language-specific, can reformat user code); free-form regex edits (ambiguous, unsafe); full three-way merges (heavy, still ambiguous).

## Consequences
Safe, idempotent edits remain constrained to declared anchors and supported structured merge operations. Uninstall removes only unchanged Forge-owned values; user-modified values are preserved and reported for reconciliation. Structured TOML/JSON/YAML serialization can normalize formatting and comments. Edited inserted blocks are never overwritten or deleted: they become conflicts.

## Security implications
Patch targets go through `safe_join`; content is rendered with `{{package}}` only; nothing is executed. A patch can still insert malicious code, so untrusted components must be reviewed in the plan like any other change.

## Migration strategy if reversed
Markers are plain comments; leaving them in place is harmless.
