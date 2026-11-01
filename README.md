# Python App Forge

A local-first, componentized Python application engineering platform, built from the
*Python App Forge Implementation Specification v1.0*.

* **Create** desktop (PySide6), web/API (FastAPI), CLI (Typer + Rich) and background-service projects from versioned templates.
* **Extend** generated *or existing* projects with reusable components through a reviewed, approved, checkpointed and recoverable change plan.
* **Verify** and **trace**: run checks, store evidence, and compute requirement status (Verified / Failed / Blocked / ...) strictly from evidence.
* **Offline by default**: catalog, generation, verification need no network. Nothing is downloaded silently.

The core platform and CLI use **only the Python standard library** (Python 3.11+). The GUI is optional.

## Install

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .                 # CLI + core
pip install -e ".[gui]"          # adds PySide6 for the desktop GUI
pip install -e ".[dev]"          # pytest, ruff, mypy (optional)
```
No install needed to try it from a checkout: `PYTHONPATH=src python -m app_forge doctor`.

## Quick tour

```bash
forge doctor                                          # environment diagnostics
forge gc                                               # preview expired plans, checkpoints and evidence
forge gc --apply                                       # delete expired data using configured retention
forge component search table                          # local catalog (no network)
forge init --archetype desktop --name "My App" --out ./my-app \
      --component forge.advanced-table --dry-run      # preview the generation plan
forge init --archetype desktop --name "My App" --out ./my-app --component forge.advanced-table
forge test run ./my-app                               # syntax + tests, evidence recorded

# Extend a project safely
forge integrate plan ./my-app --component forge.forms-validation   # nothing is modified
forge integrate preview <plan-id>
forge integrate approve <plan-id> --by alice
forge integrate apply <plan-id>                       # checkpoint -> apply -> verify
forge integrate recover <plan-id>                     # undo (never overwrites your later edits)

forge component outdated ./my-app                     # newer usable versions
forge component upgrade ./my-app forge.themes         # plan; add --apply --by alice --yes to apply
forge test compare ./my-app                           # last two verification runs: regressions / fixed
forge architecture diagram --format mermaid           # module dependency graph
forge table design table.json --import-path my_app.table_model --python-only
forge component new acme.widget --out ./components     # author your own (see docs/component-authoring.md)
forge template export cli --out ./my-template         # then edit and: forge template import ./my-template

# Existing third-party project: analysis is read-only and never runs project code
forge project analyze /path/to/repo

# Adopt an existing package: preview first, then explicitly write forge.toml
forge project adopt /path/to/repo --package my_package --archetype cli
forge project adopt /path/to/repo --package my_package --archetype cli --yes
```
`forge --json ...` gives machine-readable output (`{"ok": ..., "result"|"error": ...}`). Add `--non-interactive` in automation.

GUI: `forge-gui` (after `pip install -e ".[gui]"`). To check the GUI on your machine under real Qt, headless:

```bash
pip install -e ".[gui]" && python scripts/verify_gui.py     # exit 0 = passed, 2 = PySide6 missing, 1 = failures
python -m unittest discover -s tests -t .                 # the full suite (also worth running on Windows/macOS)
# If you unzip a newer copy, run `pip install -e .` again in the new folder: an editable install keeps pointing at the old one.
# (The tests detect this and stop with an explanation.)
```

### Exit codes
0 ok · 2 validation · 3 conflict · 4 security block · 5 internal · 6 verification failed · 7 unavailable offline or verification incomplete (a check could not run)

### Where data lives
`$FORGE_HOME` (default `~/.app_forge`): `forge.db` (history, evidence, trust), `plans/`, `checkpoints/`, `catalog/` (your components),
`settings.toml`, `revocations.json`. Project-side metadata: `forge.toml`, `.forge/components.toml`.

## Develop / test

```bash
PYTHONPATH=src python -m unittest discover -s tests -t .      # or: pytest
PYTHONPATH=src python -m app_forge test run .                 # Forge verifying itself
PYTHONPATH=src python -m app_forge test run . --check pip-audit # audit this project's declared dependencies
PYTHONPATH=src python -m app_forge compliance check --project .
```
The test suite covers the manifest schema, catalog integrity, resolver, templates, analyzer, integration/recovery (including fault injection),
security boundaries, compliance statuses and CLI exit codes.

## Continuous integration

GitHub Actions runs on pushes to `main`, pull requests targeting `main`, a nightly schedule, and manual dispatches. To keep pull-request feedback quick, PRs run a four-job test matrix: Python 3.11 on Ubuntu, Windows, and macOS, plus Python 3.14 on Ubuntu. A separate mandatory real-Qt job installs `.[gui,dev]` and runs `python scripts/verify_gui.py` headlessly under PySide6; it fails if PySide6 is missing or every GUI test is skipped. Pushes to `main`, nightly runs, and manual dispatches run the full 12-job matrix (Python 3.11–3.14 on all three operating systems). Every trigger also runs Ruff linting, mypy type checks, a `pip-audit` dependency scan, and a source/wheel build on Ubuntu. A failed job is reported on the pull request; configure branch protection in GitHub repository settings if these checks should be required before merging.

## What is and is not done

See **docs/spec-coverage.md**. Highlights of the gaps: extension **process isolation** is not an OS sandbox, signature verification is not implemented, only 6 of the spec's component families exist, and performance/portability requirements remain unverified. Real-Qt GUI tests now run as a required CI job.
Nothing in this project is a compliance or certification claim.

Docs: `docs/component-authoring.md`, `docs/compliance-artifacts.md` (compliance records and SBOM), `docs/TODO.md` (open gaps and planned components), `docs/architecture.md`, `docs/adr/` (ADR-001..012), `docs/standards-applicability.md`.


## Local data retention

`forge gc` is a dry run by default. Review the candidate counts and paths before running
`forge gc --apply`. Pending or approved plans are never collected. Completed plans,
old checkpoints, evidence rows and completed operation history use configurable retention
periods in `$FORGE_HOME/settings.toml`:

```toml
[retention]
plan_retention_days = 30
checkpoint_retention_days = 30
evidence_retention_days = 365
operation_retention_days = 365
```

Each value must be an integer from 1 to 36500. Evidence and completed operation history
are pruned independently. Checkpoints for pending plans are retained; old orphan checkpoints
may be collected after the checkpoint retention period. The command reports malformed plan
records and filesystem errors instead of silently deleting them.
