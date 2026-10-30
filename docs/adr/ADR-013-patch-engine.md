# ADR-013: Marker-based patch engine

**Status:** Accepted

## Context
Components could only add new files, so they could not register a route, add a command, or add configuration. The spec requires extension points and registration steps, and requires edits to remain reviewable and recoverable.

## Decision
Components declare patches. `insert` adds a marked block at a `forge:anchor` line; `toml-table` appends new tables; `json-merge` adds missing keys. Each applied patch is recorded (with the block's SHA-256) in `.forge/components.toml`. Patch logic is pure text-in/text-out (`patching.py`) so plans can show exact results and recovery restores bytes exactly.

## Alternatives considered
AST-based Python rewriting (language-specific, can reformat user code); free-form regex edits (ambiguous, unsafe); full three-way merges (heavy, still ambiguous).

## Consequences
Safe, idempotent, removable edits, but only at anchors (templates ship them; third-party projects must add them). TOML edits can only add new tables, JSON merges are not auto-removable. Edited blocks are never overwritten or deleted: they become conflicts.

## Security implications
Patch targets go through `safe_join`; content is rendered with `{{package}}` only; nothing is executed. A patch can still insert malicious code, so untrusted components must be reviewed in the plan like any other change.

## Migration strategy if reversed
Markers are plain comments; leaving them in place is harmless.
