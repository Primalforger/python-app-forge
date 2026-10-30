# ADR-007: Template system

**Status:** Accepted (baseline for release 0.1.0)

## Context
No template code execution; reproducible output.

## Decision
Versioned templates with validated inputs and {{variable}} substitution only

## Alternatives considered
Jinja2 or cookiecutter (code-capable templates, extra dependency).

## Consequences
Output is deterministic (tested). Inputs are validated against injection into TOML/Python.

## Security implications
No code execution during rendering.

## Migration strategy if reversed
Templates are plain files; a richer engine can be introduced behind TemplateEngine.
