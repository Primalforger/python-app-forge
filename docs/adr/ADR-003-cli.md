# ADR-003: CLI

**Status:** Accepted (baseline for release 0.1.0)

## Context
The spec recommends Typer/Rich. The platform CLI was built and verified in an environment without network access, so a zero-dependency argparse CLI was chosen. Generated CLI projects still use Typer + Rich.

## Decision
Standard-library argparse for the platform CLI; Typer + Rich for generated CLI projects

## Alternatives considered
Typer + Rich for the platform CLI itself.

## Consequences
Deviation from the spec default; behaviour (JSON mode, exit codes, non-interactive mode) is unaffected.

## Security implications
No third-party code in the platform's own execution path.

## Migration strategy if reversed
cli/main.py is a thin layer over services; a Typer front end can be added beside it.
