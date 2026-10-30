# ADR-009: Extension trust

**Status:** Accepted (baseline for release 0.1.0)

## Context
Process isolation is not yet implemented, so refusing to run is the safe default.

## Decision
Trusted in-process extensions only; untrusted extensions are never executed

## Alternatives considered
Run untrusted plugins in subprocesses.

## Consequences
Higher-risk extension support is deferred. Trust is recorded per extension and must be granted explicitly.

## Security implications
A separate process is not automatically a sandbox; this release does not claim isolation.

## Migration strategy if reversed
Add an IPC host behind ExtensionHost.activate.
