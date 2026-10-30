# ADR-002: Desktop GUI

**Status:** Accepted (baseline for release 0.1.0)

## Context
Spec baseline. LGPL licensing and distribution implications must be reviewed before redistribution.

## Decision
PySide6 as the optional GUI toolkit

## Alternatives considered
Tkinter (stdlib, weaker widgets); PyQt (GPL/commercial).

## Consequences
GUI is an optional extra (`pip install .[gui]`); the core, CLI and tests have no Qt dependency. GUI code could not be executed in the build environment.

## Security implications
Qt is only loaded by the GUI entry point.

## Migration strategy if reversed
GUI calls only ForgeServices, so another toolkit can replace gui/ without touching the core.
