# Python App Forge

**A local-first toolkit for creating, extending, and verifying Python applications.**

Python App Forge helps developers move from a project idea or an existing codebase to a structured, maintainable Python application. It combines project templates, a reusable component catalog, change planning, verification, and evidence-based traceability in one platform.

Use the command-line interface for repeatable workflows and automation, or install the optional PySide6 desktop application for a visual workbench. Forge is designed to work locally and offline by default: catalog search, project generation, analysis, and verification do not require a hosted service or silently download project content.

> **Project status:** Active development. See [specification coverage](docs/spec-coverage.md) for implemented capabilities and known limitations. This project does not claim regulatory compliance or certification.

## Why Python App Forge?

Python projects often start with a template, copied snippets, or an existing codebase that needs careful changes. As a project grows, it becomes harder to keep architecture, dependencies, tests, requirements, and change history aligned.

Forge brings those activities into a consistent workflow:

- **Create** new projects from versioned templates for desktop, web/API, CLI, and background-service applications.
- **Extend** generated and supported existing projects with reusable components.
- **Review before writing.** Build a plan, inspect its preview, and explicitly approve it.
- **Apply with recovery in mind.** Forge checkpoints files before applying planned changes and verifies the result.
- **Verify and trace.** Run checks, retain evidence, and calculate requirement status from recorded evidence.
- **Work locally.** Keep project data, catalog state, plans, checkpoints, and evidence on your machine.

## Who is it for?

- **Python developers** who want a repeatable starting point for new applications.
- **Small engineering teams** that want consistent project structures and a reviewable way to share reusable components.
- **Existing-project maintainers** who need to analyze a codebase before making controlled changes.
- **Technical leads and architects** who want clearer links between requirements, implementation checks, and verification evidence.
- **Internal-tools developers** who need desktop, API, CLI, or service foundations without adopting a hosted platform.

## Use cases

### Bootstrap a new Python application
Choose an archetype, select components, preview the generation plan, and create a project with a consistent structure. Adapt the generated project to your product requirements.

### Add capabilities to an existing project
Analyze a repository without executing its code, identify a supported integration level, and create a component plan. Review proposed file changes before approving and applying them.

### Standardize engineering practices
Maintain reusable components and versioned templates for common concerns such as configuration, logging, quality tooling, tables, and application infrastructure. Teams can maintain their own component catalog locally.

### Verify changes and preserve evidence
Run syntax checks and project tests, inspect verification outcomes, compare recent runs, and package evidence. Checks that could not run are reported as incomplete or blocked rather than silently counted as successful.

### Explore architecture and project health
Use project analysis, architecture diagrams, dependency checks, compliance records, and diagnostics to understand a codebase and identify areas that need attention.

## Key capabilities

| Area | What Forge provides |
|---|---|
| Project generation | Versioned templates for desktop, web/API, CLI, and background-service projects |
| Component catalog | Local component search, dependency resolution, version management, and reusable component packs |
| Project analysis | Read-only analysis of existing repositories; project code is not executed during analysis |
| Safe integration | Plans, previews, explicit approval, checkpoints, apply, verification, and guarded recovery |
| Verification | Syntax and test execution, optional quality checks, evidence recording, and run comparison |
| Traceability | Requirement registers, evidence packages, compliance record validation, and status derived from evidence |
| Desktop experience | Optional PySide6 GUI with workbench, diagnostics, command palette, and recent-project/session continuity |
| Automation | JSON output, non-interactive CLI operation, and generated CI/CD pipeline starters |

See [specification coverage](docs/spec-coverage.md) for the detailed and maintained feature status. Not every optional adapter, generated artifact, or platform integration is enabled by default.

## Getting started

### Requirements
- Python **3.11 or newer**
- Linux, macOS, or Windows
- pip and venv for an isolated installation

The CLI and desktop application share the same application services. The desktop GUI is optional and requires PySide6.

### Install from source

~~~bash
git clone https://github.com/Primalforger/python-app-forge.git
cd python-app-forge

python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e .
~~~

Install optional extras when needed:

~~~bash
pip install -e ".[gui]"       # PySide6 desktop application
pip install -e ".[dev]"       # pytest, Ruff, mypy and development tooling
pip install -e ".[packaging]" # PyInstaller support
~~~

Other optional integrations are documented in pyproject.toml and the architecture guide.

### Run diagnostics

~~~bash
forge doctor
~~~

To run directly from a source checkout without installing the command entry point:

~~~bash
PYTHONPATH=src python -m app_forge doctor
~~~

### Launch the desktop application

After installing the GUI extra:

~~~bash
forge-gui
~~~

## A quick tour

### Create and verify a project

Preview the generation plan first. Remove the --dry-run option when you are ready to create the project.

~~~bash
forge init --archetype desktop --name "My App" --out ./my-app \
  --component forge.advanced-table --dry-run

forge init --archetype desktop --name "My App" --out ./my-app \
  --component forge.advanced-table

forge test run ./my-app
~~~

### Search the local component catalog

~~~bash
forge component search table
forge component outdated ./my-app
~~~

Catalog operations are local; Forge does not silently refresh or download components.

### Safely extend an existing project

Integration is staged. Planning and previewing do not modify the target project.

~~~bash
# Analyze an existing repository (read-only; does not run project code)
forge project analyze /path/to/repo

# Build and inspect an integration plan
forge integrate plan ./my-app --component forge.forms-validation
forge integrate preview <plan-id>

# Explicitly approve and apply the plan
forge integrate approve <plan-id> --by "Your Name"
forge integrate apply <plan-id>

# Recover an applied plan when appropriate
forge integrate recover <plan-id>
~~~

Recovery is guarded: Forge restores a file only when it still matches the content Forge applied. Later user edits are not blindly overwritten.

### Explore verification and architecture

~~~bash
forge test compare ./my-app
forge architecture diagram --format mermaid
forge compliance check --project ./my-app
~~~

### Use Forge in scripts

~~~bash
forge --json doctor
forge --non-interactive --json test run ./my-app
~~~

The CLI supports machine-readable output and documented exit codes for success, validation errors, conflicts, security blocks, verification failures, and unavailable or incomplete checks.

## Safety and operating model

Forge is designed to make project changes explicit and reviewable.

- **Read-only analysis:** analyzing an existing project does not execute that project's code.
- **Plan before apply:** integration changes can be inspected before they are written.
- **Explicit approval:** applying a plan requires an approval step.
- **Checkpoints and guarded recovery:** changes are checkpointed; recovery avoids overwriting files that have changed since Forge applied them.
- **Fail-closed verification:** checks that cannot run are not represented as successful verification.
- **Local state:** plans, checkpoints, catalog data, evidence, and settings are stored under the Forge home directory.
- **No silent network activity:** core catalog, generation, analysis, and verification workflows are local-first.

These safeguards reduce risk but do not replace code review, backups, security testing, or operational controls. Review generated code and configuration before production use.

## Data locations and retention

Forge stores application data in the FORGE_HOME directory. If the variable is not set, the default location is ~/.app_forge.

Common contents include:

- forge.db — local history, evidence, and trust-related records
- plans/ — integration plans
- checkpoints/ — pre-apply checkpoints
- catalog/ — locally managed components
- settings.toml — application settings and retention configuration
- revocations.json — local revocation data

Project-specific metadata is stored in forge.toml and .forge/components.toml.

### Retention and cleanup

The forge gc command is a dry run by default. Review candidate counts and paths before applying cleanup:

~~~bash
forge gc
forge gc --apply
~~~

Retention periods can be configured in FORGE_HOME/settings.toml:

~~~toml
[retention]
plan_retention_days = 30
checkpoint_retention_days = 30
evidence_retention_days = 365
operation_retention_days = 365
~~~

Values must be integers from 1 to 36500. Pending or approved plans are protected from collection. Evidence and completed operation history are pruned independently.

## Development

Install development dependencies:

~~~bash
pip install -e ".[dev]"
~~~

Run the test suite:

~~~bash
PYTHONPATH=src python -m unittest discover -s tests -t .
# Or:
pytest
~~~

Run Forge's own verification and compliance checks:

~~~bash
PYTHONPATH=src python -m app_forge test run .
PYTHONPATH=src python -m app_forge test run . --check pip-audit
PYTHONPATH=src python -m app_forge compliance check --project .
~~~

Run the real-PySide6 GUI test suite in a headless environment:

~~~bash
pip install -e ".[gui,dev]"
python scripts/verify_gui.py
~~~

The GUI verification script returns exit code 0 on success, 2 when PySide6 is unavailable, and 1 when tests fail.

## Continuous integration

GitHub Actions validates pull requests with the full test suite on Python 3.11 and 3.12 across Ubuntu, Windows, and macOS, alongside a mandatory real-Qt GUI matrix on all three operating systems. CI also runs linting, type checks, dependency auditing, and source/wheel build checks. Broader scheduled and main-branch runs cover additional Python versions.

See the repository's [Actions](https://github.com/Primalforger/python-app-forge/actions) page for current workflow status. Configure branch protection in repository settings if successful checks must be required before merging.

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | Platform layers, integration transaction, extension and infrastructure design |
| [Specification coverage](docs/spec-coverage.md) | Implemented areas, verification status, deviations, and known limitations |
| [Component authoring](docs/component-authoring.md) | Creating, validating, and sealing reusable components |
| [Compliance artifacts](docs/compliance-artifacts.md) | Structured compliance records and evidence packaging |
| [Desktop session](docs/desktop-session.md) | Desktop session restoration and recent-project behavior |
| [Standards applicability](docs/standards-applicability.md) | Standards mapping and applicability notes |
| [Architecture decisions](docs/adr/) | Architecture Decision Records |
| [TODO / roadmap](docs/TODO.md) | Open work and planned improvements |

## Current limitations

Python App Forge is under active development. Some capabilities are intentionally partial or platform-dependent. Examples include:

- Extension isolation currently uses scoped Linux bubblewrap isolation where supported; it is not a virtual machine. Unsupported environments fail closed.
- Component packs cover a subset of the component families described in the implementation specification.
- Component artifact provenance uses SHA-256 digests; cryptographic signature verification is not implemented.
- Some generated deployment, CI/CD, and infrastructure artifacts are starter outputs and require environment-specific review and configuration.
- Standards mappings and compliance records are engineering aids, not independent audits, regulatory approvals, or certification.

See [specification coverage](docs/spec-coverage.md) for the authoritative, maintained list of gaps and implementation status.

## License

Python App Forge is distributed under the [MIT License](LICENSE).
