# Python App Forge: TODO

Legend: **P0** foundation, safety or trust · **P1** needed for a production release · **P2** ecosystem and polish
Size: **S** under a day · **M** a few days · **L** a week or more
`needs:` lists other items that must be finished first. Every item has a "done when" so it can be verified.

Done in the Part A pass: **G 01, G-02, G-03, G-04, G-05, G-07** (tests: `test_patching`, `test_hardening`, `test_pydeps`, `test_authoring`).
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

- [x] **G-08 Template update flow** (L, needs G-01)
  No way to pull a newer template version into an already generated project.
  *Done when:* `forge project update` produces a reviewed plan that respects user edits (three-way merge or conflict).

- [x] **G-09 Multi-archetype projects** (L)
  Composite templates combine desktop + worker or web + scheduler in one package. Template manifests pin included templates; metadata and baselines retain the complete archetype set, component resolution accepts compatible members, and path collisions fail closed.
  *Done when:* composite projects generate and verify with two archetypes sharing one core package.

- [x] **G-10 Framework-aware adapters for Level 2 projects** (L, needs G-01)
  FastAPI, Flask and Django projects are all treated alike. Add per-framework adapters (entry points, config locations,
  registration anchors).
  *Done when:* adding a component to a third-party FastAPI project registers its router automatically.

- [x] **G-11 Compliance artifact records and evidence package** (M)
  CMP-05, CMP-08, CMP-09, CMP-10 and CMP-11 are authored through the compliance CLI, validated for required content,
  stored per project, and included in `package-evidence`. Validation rejects empty collections, malformed nested records,
  duplicate interface/exception identifiers and invalid exception dates; loaded records are revalidated.
  *Done when:* `tests/test_compliance_artifacts.py` passes and the full CI suite is green.

- [x] **G-12 SBOM and licence checks** (M)
  Emit CycloneDX 1.5 and SPDX 2.3 from validated project inventory. Preserve SPDX licence expressions, flag denied identifiers even inside expressions, and keep unresolved dependency licences explicit rather than treating them as approved.
  *Done when:* output validates against the official schemas and an incompatible-licence fixture is flagged.

- [x] **G-13 Binary assets and file modes** (S)
  Components are text-only. Support images, fonts and icons, and preserve executable bits.
  *Done when:* a component ships a PNG and an executable script and both survive apply and recover unchanged.

- [x] **G-14 Interface contract tests** (M)
  `component verify` only checks that files copy in and tests pass. Add real contract tests per declared interface
  (`provides` / `requires`) with version compatibility rules.
  *Done when:* a component that breaks its declared interface fails verification.

- [x] **G-15 GUI background work** (M)
  Long operations block the UI thread; no progress or cancel.
  *Done when:* apply and verify run in worker threads with progress and a working Cancel (tested under real Qt).

- [x] **G-16 Extension process isolation** (L)
  Untrusted extensions are only refused, never isolated.
  *Done when:* an extension runs in a separate process over a narrow IPC contract with filesystem and network restrictions,
  and a test proves it cannot read outside its allowed paths.

- [x] **G-17 Signatures and attestation** (M)
  Provenance is a SHA-256 digest only.
  *Done when:* signed component artifacts are verified before install and unsigned ones follow a configurable policy.

- [x] **G-18 Online catalog refresh** (L, needs G-17)
  Offline-only today. Add an explicit refresh that downloads, verifies and then accepts artifacts (never silently).
  *Done when:* refresh works against a test server, rejects tampered artifacts, and offline mode is unaffected.

- [x] **G-19 Windows and macOS hardening** (M): manifest path validation rejects Windows-incompatible separators, characters, reserved device names, trailing dots/spaces, oversized segments, and case/Unicode-normalization collisions; the pull-request CI matrix exercises Windows, macOS and Linux.
  Untested: case-insensitive filesystems, CRLF files, long paths, path separators in manifests.
  *Done when:* the CI matrix covers these cases with dedicated tests.

- [ ] **G-20 OWASP ASVS checks for the web template** (M)
  Referenced in the spec, not implemented.
  *Done when:* the web template has a mapped ASVS checklist with automated checks and documented gaps.

- [x] **G-21 Performance baselines** (M)
  An offline harness generates representative catalog and project workloads and records raw timings plus host metadata.
  The Ubuntu 24.04 / Python 3.11 report is checked in with seven raw samples per workload; ceilings are 150% of measured
  medians rounded up to the nearest millisecond, and CI enforces them only on the matching runner image (closes `NFR-003`).

- [x] **G-27 Richer patch kinds** (M, new, found while building G-01)
  In-table TOML key insertion is marker-managed and reversible. JSON/YAML merges persist per-value ownership metadata; uninstall
  removes only unchanged Forge-added keys/list items and preserves unrelated user values. Legacy merge records without ownership
  fail safely and require manual reconciliation. Structured serialization may normalize formatting/comments.
  *Done when:* existing-table TOML changes are exact on removal, and JSON/YAML merge removal is ownership-checked.

### P2: ecosystem and polish

- [x] **G-22 Housekeeping** (S): `forge gc` previews or removes expired terminal plans, old checkpoints, evidence and completed operation history. Retention periods are configurable; dry-run is the default, pending/approved plans are protected, and malformed records are reported rather than silently removed.
  *Done when:* `tests/test_housekeeping.py` proves dry-run safety, retention pruning and preservation of pending plans.
- [x] **G-23 Table Designer grid editor** (M): replace the raw JSON editor with an accessible editable column grid. Users can add/remove columns, edit keys and select validated data types; existing sort/filter/page/export defaults are preserved when generating code.
  *Done when:* the real-Qt suite verifies grid editing, add/remove behavior and successful code generation.
- [x] **G-24 Dedicated GUI screens** (M): separate Project Wizard, Generation Review, Configuration Center and Diagnostics screens. Project inputs live in the wizard; a dedicated dry-run review screen previews the generated plan without creating files; configuration and diagnostics have distinct navigation entries.
  *Done when:* navigation exposes all four screens, generation review is read-only, and stub plus real-Qt tests cover the wizard-to-review flow.
- [x] **G-25 More templates** (M): add a dependency-free plain Python library template and a Forge extension starter with entry-point metadata, JSON-safe example methods, tests and trust-first security guidance.
  *Done when:* both templates generate reproducible projects, expose their intended packaging metadata, and pass generated-project verification.
- [x] **G-26 CLI polish** (S): Bash/Zsh/Fish completion scripts, `--output text|json|yaml|table` (`--json` remains compatible), and consistent opt-in/TTY-aware progress messages on stderr.

---

## Part B: Components to build

Components marked **(lib)** need no patch engine and can be built now. All others need **G-01**.
Each component needs: a manifest, contract tests, an entry in `requirements.toml`, and a passing `forge component verify`.

### Quick wins (no blockers)

- [x] **C-01 Table: saved views and presets** (S, lib): persistent named presets for column order/visibility, filters, sort, search and page size; validated JSON state, atomic file replacement, and explicit apply/delete operations. Verified by `tests/test_table_views.py`.
- [x] **C-02 Table: column resize and persistence** (S, lib): validated logical-pixel widths per known column, bounded to 24–2000 px, persisted as schema-versioned JSON with atomic replacement; missing files default cleanly and corrupt or stale column metadata fails closed. Verified by `tests/test_table_layout.py`.
- [x] **C-03 Table: group-by and aggregates** (M, lib): stable first-seen groups over filtered/searched/sorted rows, with count/sum/average/min/max aggregates, null handling and explicit validation. Pagination is not applied to group contents. Verified by the generated advanced-table component regression tests.
- [x] **C-04 Table: server-side mode** (M, lib): the same interface backed by a query callback.
- [x] **C-05 Table: XLSX and PDF export adapters** (M, lib): optional `openpyxl` and `reportlab` extras; visible columns and filtered/sorted rows are exported, with stable selected-row export and formula-safe spreadsheet strings.
- [x] **C-06 Qt table view adapter** (M, lib): optional PySide6 `QAbstractTableModel` adapter exposes visible columns, delegates sorting, supports opt-in editing and synchronizes view selection to stable source row IDs; verified by real-Qt tests.
- [x] **C-07 Schema-driven settings dialog** (M, lib, desktop): optional PySide6 dialog builds accessible text, integer, float, boolean and choice controls from validated field mappings; required fields and numeric bounds are enforced before acceptance. Verified by real-Qt tests.
- [x] **C-08 Undo/redo stack** (S, lib, desktop): framework-independent command history with execute/undo/redo, redo-branch invalidation, bounded history and failure-safe stack transitions. Verified by `tests/test_undo.py`.
- [x] **C-09 Recent files and session state** (S, lib, desktop): bounded newest-first recent-file tracking with deduplication/removal and optional existence filtering; atomic JSON session-state persistence with finite-JSON validation and a configurable size limit. Verified by `tests/test_session.py`.
- [ ] **C-10 CLI output formatters** (S, lib): table, JSON, YAML, with colour control.
- [ ] **C-11 CLI progress and prompts** (S, lib)
- [x] **C-12 Retry and circuit-breaker library** (S, lib): bounded exponential backoff with jitter and retry predicates; thread-safe closed/open/half-open breaker with a single recovery probe and manual reset. Verified by `tests/test_retry.py`.
- [x] **C-13 Feature flags** (S, lib): thread-safe in-process boolean registry with validated names, immutable registered defaults, explicit runtime overrides, override clearing and defensive snapshots; unknown flags fail closed. Verified by `tests/test_feature_flags.py`.
- [x] **C-14 SQLite job queue** (M, lib, service): persistent JSON-only jobs with atomic multi-worker claims, expiring leases, bounded attempts, retry scheduling, dead-letter inspection and explicit redrive. Verified by `tests/test_job_queue.py`.
- [x] **C-15 Secret providers** (M, lib): environment (read-only), optional OS keyring adapter, and owner-permission-only JSON file store; secret wrappers redact string/repr output and backend errors are sanitized. File storage is plaintext at rest and documented accordingly.
- [x] **C-16 Hash-chained audit log** (M, lib): append-only canonical JSONL events with sequence numbers, UTC timestamps, actor/event metadata, previous-hash links and SHA-256 record hashes; cross-process append locking; `forge audit append` and `forge audit verify` report tampering and malformed records without repairing them. The chain is tamper-evident, not tamper-proof.
- [x] **C-17 File store abstraction** (S, lib): root-confined local filesystem with traversal and symlink rejection, bounded reads/writes, atomic replacement, deterministic listing and explicit file deletion. Verified by `tests/test_file_store.py`.
- [x] **C-18 Retrying HTTP client** (M, lib): dependency-free HTTP client with bounded timeouts and response bodies, conservative retries for idempotent methods, Retry-After support, redacted retry diagnostics and explicit opt-in for unsafe-method retries. Verified by `tests/test_http_client.py`.
- [x] **C-19 File watcher and notifier set** (M, lib, automation): bounded cross-platform polling watcher with recursive/non-recursive scans, symlink avoidance, create/modify/delete events, clean thread shutdown, callback/queue/composite notifiers, and explicit queue backpressure. Verified by `tests/test_file_watcher.py`.
- [x] **C-20 Webhook signature verification** (S, lib): timestamped HMAC-SHA256/SHA-512 over raw request bodies, constant-time comparison, bounded freshness window, and explicit guidance for durable event-ID deduplication. Verified by `tests/test_webhook_signatures.py`.

### Governance and quality (close compliance gaps; no blockers)

- [x] **C-21 ADR generator** (S, lib): dependency-free ADR Markdown rendering and exclusive numbered file creation, with validated status/date/participants, bounded sections, no-overwrite behavior and documentation. Verified by `tests/test_adr.py`.
- [x] **C-22 STRIDE threat-model template** (S, lib): dependency-free STRIDE worksheet with validated assets, trust boundaries, unique threat IDs, six category prompts, impact, mitigation and residual-risk capture; renders Markdown and adapts to the existing CMP-08 compliance record. Verified by `tests/test_threat_model.py`.
- [x] **C-23 Change-impact record generator** (M, lib): validated change metadata, affected systems, requirement traceability, impact dimensions, rollback and verification plans; Markdown review report and CMP-09 adapter. Empty traceability is explicitly incomplete. Verified by `tests/test_change_impact.py`.
- [x] **C-24 Coverage gate** (S, lib): dependency-free Cobertura parser, inclusive line/optional branch thresholds, bounded XML input, fail-closed validation, structured result and tests. Verified by `tests/test_coverage_gate.py`.
- [x] **C-25 Licence scanner** (M, lib): dependency-free SPDX expression parser and deny-list scanner; detects denied identifiers inside compound expressions, excludes `WITH` exception identifiers, rejects malformed expressions, and reports unknown component/dependency metadata without treating it as approved. Verified by `tests/test_license_scanner.py`.
- [x] **C-26 SBOM generator** (M, lib): reusable `generate_sboms` API builds CycloneDX 1.5 and SPDX 2.3 in caller-selected order; `serialize_sbom` emits deterministic canonical JSON and rejects invalid values. Existing CLI behavior remains compatible. Verified by `tests/test_supply_chain.py`.
- [x] **C-27 Documentation scaffold** (S, lib): dependency-free `DocumentationProject` metadata model, deterministic MkDocs-ready navigation and starter pages, safe metadata validation/quoting, and exclusive file creation that refuses overwrites and symlink directories. Verified by `tests/test_documentation_scaffold.py`.
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
