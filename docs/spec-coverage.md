# Specification coverage (release 0.1.0)

Honest status against *Python App Forge: Implementation Specification v1.0*. "Verified" means covered by
automated tests in this repository (run `forge test run .` then `forge compliance check`).

| Area | Status | Notes |
|---|---|---|
| FR-001/002 project creation, 4 archetypes | Implemented, verified | Generated projects pass their own smoke tests (tests/test_templates_components.py). |
| FR-003 GUI/CLI parity | Implemented; logic and real-Qt UI suites | Both call `ForgeServices`. GUI logic tests use a Qt stand-in; a separate mandatory CI job installs PySide6 and runs the real-Qt headless suite. |
| FR-004/005 catalog + component management | Implemented, verified | Search/filter, add, remove, **upgrade**, enable/disable, contract verify. Upgrade never overwrites user-edited files, pulls in new transitive dependencies, and is recoverable. |
| FR-006/007/012 analysis, plans, recovery | Implemented, verified | Levels 1-4, checkpoints, drift detection, partial-recovery reporting, fault injection. |
| FR-008 dependency resolution | Implemented, verified | Missing, incompatible, conflicting, cyclic, missing-interface. |
| FR-009 verification | Implemented, verified | Syntax + tests (pytest, or unittest fallback). ruff/mypy/pip-audit run only if installed, else `not_run`. |
| FR-010/013 traceability, export | Implemented, verified | Requirements register, 8 statuses, evidence package with SHA-256 manifest. |
| FR-011 local-first operation | Implemented, verified | Ordinary catalog scans, search, generation and verification remain offline. Explicit `forge catalog refresh` is available for configured HTTPS sources and preflights archive hashes, component digests and trusted Ed25519 attestations; there is no background polling. See `docs/online-catalogs.md`. |
| CMP-05/08/09/10/11 compliance artifacts | Implemented; validation and package tests | Five project-local structured records are accepted through the compliance CLI, validated on write and read, and included in the SHA-256-manifested evidence package. Human-authored assessments and approvals are never inferred. See `docs/compliance-artifacts.md`. |
| FR-014 extensions | Implemented with scoped Linux isolation | Discovery, trust, enable and versioned JSON IPC run in a child worker with timeout/crash handling. Linux invocation requires bubblewrap namespaces, isolates networking, omits the host home mount and exposes only explicit writable directories. Unsupported platforms or missing sandbox support fail closed. This is not a complete VM; trust approval remains required. |
| Patch engine / extension points | Implemented, verified | `insert`, `toml-table`, and structured TOML/JSON/YAML merge patches are planned and applied through the reviewed integration transaction. Marker-managed TOML additions and ownership metadata for JSON/YAML merges allow safe removal of unchanged Forge-added values; user-modified values are preserved or reported as conflicts. Structured serialization may normalize formatting/comments. See `docs/adr/ADR-013-patch-engine.md`. |
| Component packs | 9 components in 5 of the spec's 10 families, small | themes, advanced table (model only, no Qt view), forms, logging, config, quality, health endpoint, CLI version command, Ruff config. No SQLAlchemy/PostgreSQL, auth/RBAC, CI/CD, workflow packs. |
| GUI screens | 12 of the spec's 21 screen IDs are covered as 12 screens | Dashboard, Template Studio, Catalog, Component Manager, Design System, Table Designer, Architecture Explorer, Extension Manager, Integration Workbench, Quality and Compliance, Settings, and Diagnostics. The Table Designer uses an editable column grid with validated types; several specification screens are consolidated (for example, Wizard/Config/Review workflows live in Template Studio). |
| CLI groups | Implemented | All 16 groups in spec 6, now including `architecture diagram`, `test compare/runs`, `history compare`, `template import/export`, `component upgrade/outdated`, plus `table design`. |
| NFR-003 performance | Implemented, verified on reference runner | The Ubuntu 24.04 / Python 3.11 baseline report contains seven raw samples per workload; CI enforces ceilings derived from measured medians only on the matching runner image. See `requirements.toml`. |
| NFR-005 portability, NFR-009 compatibility | Implemented; CI matrix verified | Pull requests run the complete suite on Python 3.11 and 3.12 across Ubuntu, Windows and macOS, and run the mandatory real-Qt suite on all three operating systems with both Python versions (six real-Qt combinations). The broader 12-job Python 3.11–3.14 matrix runs on pushes to `main`, nightly and manual dispatch. See `requirements.toml`.
| Windows | CI matrix verified | Pull-request CI runs the full test suite and mandatory real-Qt GUI suite on Windows alongside Ubuntu and macOS. A documented local Windows 11 / Python 3.13 / PySide6 6.12 run also passed 175 tests with 4 platform-specific skips; see the G-06 evidence in `docs/TODO.md`. |
| Accessibility | Automated real-Qt coverage added | The mandatory `real-qt` CI job exercises keyboard navigation, visible focus styling, accessible names, control focusability and theme switching under PySide6. Treat the area as verified only when that job is green. |
| Component signatures/attestation | Implemented, verified | Ed25519 detached attestations bind component identity, version and sealed SHA-256 digest. Catalog verification checks signatures against locally pinned public keys; unsigned artifacts follow configurable `allow`/`warn`/`deny` policy, while invalid or untrusted signatures are quarantined. This is not a certificate authority or transparency log. See `docs/component-signing.md` and `tests/test_component_attestation.py`. |
| Online catalog refresh | Implemented, verified | Explicit refresh downloads signed artifacts from configured HTTPS indexes, validates archive hashes and attestations before import, and is disabled in offline mode. No background polling. See `docs/online-catalogs.md` and `tests/test_online_catalog_refresh.py`. |
| Desktop crash reporting | Implemented, verified | Unexpected desktop exceptions are recorded in bounded local JSON reports with secret redaction, restrictive file permissions where supported, retention pruning and no network activity. See `tests/test_crash_reporter.py`. |
| Packaging | Implemented; native release evidence remains required | Forge generates deterministic PyInstaller specs and supports explicit native builds. Build artifacts must be built and launch-tested on each declared target OS; a cross-platform spec is not a cross-compiler. See `docs/pyinstaller-packaging.md` and `tests/test_packaging.py`. |
| Desktop session and durable workflows | Implemented, verified | Session continuity restores validated screen/theme/window state and recent projects; durable workflow dispatch uses queue leases, bounded retries and at-least-once delivery. See `docs/desktop-session.md` and `docs/durable-workflows.md`. |
| IEEE/MOSA | Mechanisms only | Nothing here is a certification claim. |

## Deviations and scope boundaries
* Platform CLI uses argparse rather than Typer/Rich (ADR-003); generated CLI projects use Typer + Rich.
* Component packs intentionally cover only a subset of the specification's component families. The broader platform libraries and adapters are not all exposed as installable catalog packs.
* Extension isolation is a scoped Linux bubblewrap boundary, not a virtual machine; unsupported environments fail closed.
* Local signing keys are pinned by operators. There is no public certificate authority or online transparency service.
* Generated deployment and infrastructure artifacts remain starters and require environment-specific review and validation.
* Compliance records and standards mappings support engineering traceability; they do not constitute independent audits or certification.

## Evidence and maintenance

A status of **verified** means the behavior has focused automated coverage in this repository. Pull-request CI provides the cross-platform evidence; historical local-run counts are identified as such rather than treated as current suite totals. Reconcile this document with `docs/TODO.md`, the linked feature guides, and the tests whenever a capability changes.
