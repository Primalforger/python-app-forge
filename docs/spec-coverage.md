# Specification coverage (release 0.1.0)

Honest status against *Python App Forge: Implementation Specification v1.0*. "Verified" means covered by
automated tests in this repository (run `forge test run .` then `forge compliance check`).

| Area | Status | Notes |
|---|---|---|
| FR-001/002 project creation, 4 archetypes | Implemented, verified | Generated projects pass their own smoke tests (tests/test_templates_components.py). |
| FR-003 GUI/CLI parity | Implemented; GUI logic exercised via a stand-in | Both call `ForgeServices`. GUI code runs in tests against a Qt *stub* (screens build, handlers call real services). **It has still never run under real PySide6.** A real-Qt headless suite (`tests/test_gui_qt.py`, 9 tests: all screens render, keyboard navigation, theme/focus styling, accessibility audit, workbench end-to-end) is written and skips when Qt is absent. Run `python scripts/verify_gui.py` on a machine with PySide6 to get the real answer. |
| FR-004/005 catalog + component management | Implemented, verified | Search/filter, add, remove, **upgrade**, enable/disable, contract verify. Upgrade never overwrites user-edited files, pulls in new transitive dependencies, and is recoverable. |
| FR-006/007/012 analysis, plans, recovery | Implemented, verified | Levels 1-4, checkpoints, drift detection, partial-recovery reporting, fault injection. |
| FR-008 dependency resolution | Implemented, verified | Missing, incompatible, conflicting, cyclic, missing-interface. |
| FR-009 verification | Implemented, verified | Syntax + tests (pytest, or unittest fallback). ruff/mypy/pip-audit run only if installed, else `not_run`. |
| FR-010/013 traceability, export | Implemented, verified | Requirements register, 8 statuses, evidence package with SHA-256 manifest. |
| FR-011 offline | Implemented, verified | Test blocks sockets while exercising the catalog. No online refresh exists (ADR-012). |
| FR-014 extensions | Partially implemented | Discovery, trust, enable, versioned JSON IPC in a child worker with timeout/crash handling. **No OS sandbox**; child retains the user's filesystem and network permissions, and untrusted extensions remain refused. |
| Patch engine / extension points | Implemented, verified | `insert`, `toml-table`, `json-merge` patches with markers (ADR-013); templates ship anchors. Limits: TOML adds tables only, JSON merges not auto-removed. |
| Component packs | 9 components in 5 of the spec's 10 families, small | themes, advanced table (model only, no Qt view), forms, logging, config, quality, health endpoint, CLI version command, Ruff config. No SQLAlchemy/PostgreSQL, auth/RBAC, CI/CD, workflow packs. |
| GUI screens | 12 of the spec's 21 screen IDs are covered as 12 screens | Dashboard, Template Studio, Catalog, **Component Manager, Design System, Table Designer (JSON editor, not a column grid), Architecture Explorer, Extension Manager**, Integration Workbench, Quality and Compliance, Settings, Diagnostics. Several spec screens are merged (e.g. Wizard/Config/Review live in Template Studio). |
| CLI groups | Implemented | All 16 groups in spec 6, now including `architecture diagram`, `test compare/runs`, `history compare`, `template import/export`, `component upgrade/outdated`, plus `table design`. |
| NFR-003 performance, NFR-005 portability, NFR-009 CI matrix | Not verified | `.github/workflows/ci.yml` (3 OSes x Python 3.11/3.12, headless Qt, self-verification) is written but **has never been run**. Performance needs baselines first. See `requirements.toml` gaps (statuses show *Planned*). |
| Windows | Verified | Full suite (175 tests, 4 skipped: symlinks/POSIX shell) and the real-Qt GUI suite (9/9) pass on Windows 11 / Python 3.13 / PySide6 6.12. Platform fixes found by those runs: closed SQLite handles, stale-lock detection, line-ending-tolerant edit detection. macOS and Linux-with-Qt are untested. |
| Accessibility | Partly verified | Every input widget has an accessible name (audited in tests); theme contrast is unit tested. Real keyboard/focus behaviour is covered only by the unrun real-Qt tests. |
| Signatures/attestation | Not implemented | Provenance is a SHA-256 digest only; there is no signature verification. |
| IEEE/MOSA | Mechanisms only | Nothing here is a certification claim. |

## Deviations from the spec
* Platform CLI uses argparse rather than Typer/Rich (ADR-003).
* Generated CLI projects do use Typer + Rich.
