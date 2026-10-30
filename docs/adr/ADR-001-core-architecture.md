# ADR-001: Core architecture

**Status:** Accepted (baseline for release 0.1.0)

## Context
A single cohesive application is easier to build, test and ship than microservices; modularity comes from enforced dependency rules, not process boundaries.

## Decision
Modular monolith with explicit contracts

## Alternatives considered
Microservices; plain script collection.

## Consequences
One deployable. Internal boundaries enforced by tests/test_cli_architecture.py (AST rules in app_forge/architecture.py).

## Security implications
Fewer network surfaces; no inter-service auth needed.

## Migration strategy if reversed
Modules already communicate through services.py and domain contracts, so a module can later be extracted behind the same interface.
