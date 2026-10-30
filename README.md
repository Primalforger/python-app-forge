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

GitHub Actions runs automatically on pushes to `main`, pull requests targeting `main`, and manual dispatches. The workflow tests Python 3.11–3.14 on Ubuntu, Windows, and macOS, then runs Ruff linting, mypy type checks, a `pip-audit` dependency scan, and a source/wheel build on Ubuntu. A failed job is reported on the pull request; configure branch protection in GitHub repository settings if these checks should be required before merging.

## What is and is not done

See **docs/spec-coverage.md**. Highlights of the gaps: the **GUI has never run under real PySide6** (its logic is exercised against a stub, and a real-Qt test suite exists but has not been executed; PySide6 was unavailable
where this was built), extension **process isolation** and **signature verification** are not
implemented, only 6 of the spec's component families exist, and performance/portability/CI-matrix requirements are unverified.
Nothing in this project is a compliance or certification claim.

Docs: `docs/component-authoring.md`, `docs/TODO.md` (open gaps and planned components), `docs/architecture.md`, `docs/adr/` (ADR-001..012), `docs/standards-applicability.md`.
