# Python App Forge: TODO

Legend: **P0** foundation, safety or trust · **P1** needed for a production release · **P2** ecosystem and polish
Size: **S** under a day · **M** a few days · **L** a week or more
`needs:` lists other items that must be finished first. Every item has a "done when" so it can be verified.

Done in the Part A pass: **G-01, G-02, G-03, G-04, G-05, G-07** (tests: `test_patching`, `test_hardening`, `test_pydeps`, `test_authoring`).
**G-06 results (Windows 11, Python 3.13, PySide6 6.12.0).**
Run 1: 7 of 9 real-Qt tests passed; found an unnamed widget, a stale search test and a platform bug (SQLite connections never closed).
Run 2 (after fixes): 9/9 real-Qt tests passed. A full-suite run against a stale editable install was meaningless, but exposed two real Windows bugs
(stale-lock detection, LF/CRLF false conflicts), both fixed.
Run 3 (current code, fresh `pip install -e .`): **full suite 175 tests OK on Windows, 4 skipped** (symlink and POSIX-shell tests), including the 9 real-Qt tests.
**Windows is done.** Still outstanding for G-06: macOS, Linux with real Qt, and the CI workflow (written, never run).

Already done (release 0.1.0 plus follow-ups): the 15 P0 spec items, component upgrade, all spec CLI groups, 12 GUI screens
(logic tested against a Qt stand-in), real-Qt test suite written, CI workflow written.

---

## Part A: Gaps in the platform

### P0: foundation, safety and trust

- [x] **G-01 Patch engine and extension points** (L)
  Components can currently only add new files. Add anchor-based, idempotent insertions (e.g. register a router, add a
  menu entry) plus TOML/JSON key merging, with `extension_points` and `registration` sections in the manifest.
  All changes must flow through the existing plan, approve, checkpoint, apply and recover path.
  *Done when:* a component can add a FastAPI router and a config key to a generated project, planning twice produces no
  duplicate insertion, and recovery restores the original text byte for byte.
  *Unblocks:* most of Part B.

- [x] **G-02 Digest must cover the manifest** (S)
  Today only `files/` is hashed, so an edited `component.toml` (paths, permissions) goes unnoticed.
  *Done when:* changing any manifest field after sealing quarantines the component; a regression test proves it.

- [x] **G-03 Safe, accurate verification environment** (M)
  Verification runs under Forge's own interpreter with the full environment (secrets included), and reports "failed" when a
  project dependency is simply not installed here.
  Use the project's own virtual environment when present, pass a scrubbed environment, and report a missing dependency as
  `blocked` with the reason, not as a test failure.
  *Done when:* a test shows a secret env var is invisible to project tests, and a project needing an uninstalled package
  yields `Blocked`.

- [x] **G-04 Python dependency resolution** (M)
  A component wanting `rich>=14` is silently skipped if the project already has `rich>=13`.
  Parse requirement specifiers, detect incompatibilities, and show them in the plan as conflicts or manual actions.
  *Done when:* fixtures for compatible, incompatible and unpinned cases produce the right plan entries.

- [x] **G-05 Project lock** (S)
  Two Forge processes can apply plans to the same project at once.
  *Done when:* a second apply on a locked project fails with a clear conflict error; stale locks are detected.

- [ ] **G-06 Run the unrun things** (S, in progress: first run done, re-run needed)
  `python scripts/verify_gui.py` and the CI workflow have never been executed.
  *Done when:* real-Qt tests pass (or their failures are fixed) and CI is green on 3 operating systems and Python 3.11/3.12.
  Closes requirements `UI-QT`, `NFR-005`, `NFR-009` once evidence exists.

- [x] **G-07 Component authoring CLI** (M)
  Sealing a component's digest is only possible from Python.
  Add `forge component new | validate | seal | pack`, plus a component-authoring guide.
  *Done when:* a new component can be scaffolded, sealed, validated and installed using only the CLI.

### P1: needed for a production release

- [ ] **G-08 Template update flow** (L, needs G-01)
  No way to pull a newer template version into an already generated project.
  *Done when:* `forge project update` produces a reviewed plan that respects user edits (three-way merge or conflict).

- [ ] **G-09 Multi-archetype projects** (L)
  The spec allows combinations (desktop + worker, web + scheduler); a project has exactly one archetype today.
  *Done when:* a project can be generated and verified with two archetypes sharing one core package.

- [ ] **G-10 Framework-aware adapters for Level 2 projects** (L, needs G-01)
  FastAPI, Flask and Django projects are all treated alike. Add per-framework adapters (entry points, config locations,
  registration anchors).
  *Done when:* adding a component to a third-party FastAPI project registers its router automatically.

- [ ] **G-11 Missing compliance artifacts** (M)
  Generate CMP-05 interface control records, CMP-08 security assessment (threat model), CMP-09 change impact records,
  CMP-10 release evidence package, CMP-11 exceptions and waivers register.
  *Done when:* each is produced by a command, validated for completeness, and included in `package-evidence`.

- [ ] **G-12 SBOM and licence checks** (M)
  Inventory is custom JSON. Emit CycloneDX and SPDX, and check licence compatibility from manifests.
  *Done when:* output validates against the official schemas and an incompatible-licence fixture is flagged.

- [ ] **G-13 Binary assets and file modes** (S)
  Components are text-only. Support images, fonts and icons, and preserve executable bits.
  *Done when:* a component ships a PNG and an executable script and both survive apply and recover unchanged.

- [ ] **G-14 Interface contract tests** (M)
  `component verify` only checks that files copy in and tests pass. Add real contract tests per declared interface
  (`provides` / `requires`) with version compatibility rules.
  *Done when:* a component that breaks its declared interface fails verification.

- [ ] **G-15 GUI background work** (M)
  Long operations block the UI thread; no progress or cancel.
  *Done when:* apply and verify run in worker threads with progress and a working Cancel (tested under real Qt).

- [ ] **G-16 Extension process isolation** (L)
  Untrusted extensions are only refused, never isolated.
  *Done when:* an extension runs in a separate process over a narrow IPC contract with filesystem and network restrictions,
  and a test proves it cannot read outside its allowed paths.

- [ ] **G-17 Signatures and attestation** (M)
  Provenance is a SHA-256 digest only.
  *Done when:* signed component artifacts are verified before install and unsigned ones follow a configurable policy.

- [ ] **G-18 Online catalog refresh** (L, needs G-17)
  Offline-only today. Add an explicit refresh that downloads, verifies and then accepts artifacts (never silently).
  *Done when:* refresh works against a test server, rejects tampered artifacts, and offline mode is unaffected.

- [ ] **G-19 Windows and macOS hardening** (M, best done together with G-06)
  Untested: case-insensitive filesystems, CRLF files, long paths, path separators in manifests.
  *Done when:* the CI matrix covers these cases with dedicated tests.

- [ ] **G-20 OWASP ASVS checks for the web template** (M)
  Referenced in the spec, not implemented.
  *Done when:* the web template has a mapped ASVS checklist with automated checks and documented gaps.

- [ ] **G-21 Performance baselines** (M)
  Thresholds are intentionally undefined until measured.
  *Done when:* representative catalog and project datasets exist, baselines are recorded on named hardware, and thresholds
  are set (closes `NFR-003`).

- [ ] **G-27 Richer patch kinds** (M, new, found while building G-01)
  `toml-table` can only add new tables and `json-merge` is not auto-removable. Add in-table key insertion for TOML and tracked
  removal for JSON merges, plus a `yaml-merge` kind.
  *Done when:* adding and removing a key in an existing `[tool.x]` table is exact and recoverable.

### P2: ecosystem and polish

- [ ] **G-22 Housekeeping** (S): `forge gc` for old plans, checkpoints and evidence; retention settings.
- [ ] **G-23 Table Designer grid editor** (M): replace the JSON editor with a column grid.
- [ ] **G-24 Dedicated GUI screens** (M): separate Project Wizard, Generation Review, Configuration Center and Diagnostics bundle
  screens (currently merged).
- [ ] **G-25 More templates** (M): plain library, and a template for writing Forge extensions.
- [ ] **G-26 CLI polish** (S): shell completion, `--output yaml|table`, consistent progress output.

---

## Part B: Components to build

Components marked **(lib)** need no patch engine and can be built now. All others need **G-01**.
Each component needs: a manifest, contract tests, an entry in `requirements.toml`, and a passing `forge component verify`.

### Quick wins (no blockers)

- [ ] **C-01 Table: saved views and presets** (S, lib): named filter, sort and column presets (spec 5.3 "state persistence").
- [ ] **C-02 Table: column resize and persistence** (S, lib)
- [ ] **C-03 Table: group-by and aggregates** (M, lib)
- [ ] **C-04 Table: server-side mode** (M, lib): the same interface backed by a query callback.
- [ ] **C-05 Table: XLSX and PDF export adapters** (M, lib): optional dependencies.
- [ ] **C-06 Qt table view adapter** (M, lib): `QAbstractTableModel` over `TableModel`; needs real Qt to verify (G-06).
- [ ] **C-07 Schema-driven settings dialog** (M, lib, desktop): builds a Qt form from a field schema.
- [ ] **C-08 Undo/redo stack** (S, lib, desktop)
- [ ] **C-09 Recent files and session state** (S, lib, desktop)
- [ ] **C-10 CLI output formatters** (S, lib): table, JSON, YAML, with colour control.
- [ ] **C-11 CLI progress and prompts** (S, lib)
- [ ] **C-12 Retry and circuit-breaker library** (S, lib)
- [ ] **C-13 Feature flags** (S, lib)
- [ ] **C-14 SQLite job queue** (M, lib, service): persistent jobs with retries and dead-letter handling.
- [ ] **C-15 Secret providers** (M, lib): environment, OS keyring, file; never logged.
- [ ] **C-16 Hash-chained audit log** (M, lib): tamper-evident events; verification command.
- [ ] **C-17 File store abstraction** (S, lib): local filesystem with safe-path guarantees.
- [ ] **C-18 Retrying HTTP client** (M, lib): timeouts, backoff, redaction in logs.
- [ ] **C-19 File watcher and notifier set** (M, lib, automation)
- [ ] **C-20 Webhook signature verification** (S, lib): HMAC with replay protection.

### Governance and quality (close compliance gaps; no blockers)

- [ ] **C-21 ADR generator** (S, lib)
- [ ] **C-22 STRIDE threat-model template** (S, lib): feeds G-11.
- [ ] **C-23 Change-impact record generator** (M, lib): feeds G-11.
- [ ] **C-24 Coverage gate** (S, lib)
- [ ] **C-25 Licence scanner** (M, lib): pairs with G-12.
- [ ] **C-26 SBOM generator** (M, lib): pairs with G-12.
- [ ] **C-27 Documentation scaffold** (S, lib)
- [ ] **C-28 Changelog and release notes tooling** (S, lib)

### Need the patch engine (G-01)

- [ ] **C-29 SQLAlchemy + Alembic migrations** (L): migrations are irreversible side effects, so recovery needs special handling.
- [ ] **C-30 SQLite repository layer** (M)
- [ ] **C-31 PostgreSQL adapter** (M, needs C-29)
- [ ] **C-32 JWT authentication using an established library** (M, web)
- [ ] **C-33 RBAC** (M, web; needs C-32)
- [ ] **C-34 CORS, rate limiting and security headers** (M, web)
- [ ] **C-35 Problem-details error format** (S, web)
- [ ] **C-36 Health and readiness endpoints** (S, web and service)
- [ ] **C-37 Prometheus metrics** (M)
- [ ] **C-38 Command palette** (M, desktop)
- [ ] **C-39 Crash reporter** (M, desktop): local only, with redaction and no hidden network activity.
- [ ] **C-40 Dockerfile, systemd and Windows-service generators** (M)
- [ ] **C-41 CI/CD pipeline generator** (M)
- [ ] **C-42 Pre-commit and import-linter config from manifests** (M)
- [ ] **C-43 PyInstaller packaging** (L, desktop): per-OS verification needs G-06/G-19.
- [ ] **C-44 Small workflow engine** (L, automation)

---

## Suggested order

1. **G-02, G-03, G-05**: small and close real trust and safety holes.
2. **G-06** (on a machine with PySide6), then G-19: turns "unrun" into evidence.
3. **G-01**: the patch engine; then **G-07** (authoring CLI) so others can contribute.
4. **G-04**, then the no-blocker component batches: **C-01 to C-20**, then **C-21 to C-28** with G-11 and G-12.
5. **C-29 to C-44** and G-08, G-09, G-10 once G-01 is proven.
6. G-15 to G-18, G-20, G-21 for production hardening; P2 items last.

Track progress by turning each item into a `[[requirement]]` in `requirements.toml` with `verified_by` tests, so status comes from
evidence, not from ticking this list.
