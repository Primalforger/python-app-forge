# Architecture

```
Presentation      cli/main.py (argparse)        gui/app.py (PySide6, optional)
                          \                        /
Application       services.py  (ForgeServices: every operation, operation IDs, history)
                          |
Domain/contracts  domain/{errors,versioning,models}.py     (no I/O, no frameworks)
Engines           catalog/registry  resolver  templates/engine  analyzer
                  integration  verification  compliance  extensions
Infrastructure    persistence (SQLite)  security  observability  settings  projectmeta  tomlw
Data              data/components/<id>/<ver>/{component.toml,files/}    data/templates/<id>/
```

Rules (enforced by `forge architecture check-rules` and a unit test):
* Domain imports nothing but itself and pure-stdlib modules (no os/pathlib/sqlite3/network).
* CLI and GUI never import each other and only reach `services`, `domain`, `settings`, `observability`.
* Only `persistence` imports `sqlite3`.
* `compliance` consumes evidence as data; it never imports verification/integration.

## Integration transaction
discover/analyze -> plan (stored in `$FORGE_HOME/plans`, project untouched) -> approve (hash-checked) ->
checkpoint (`$FORGE_HOME/checkpoints/<plan>`) -> apply (temp file + atomic replace) -> verify -> finalize.
Recovery restores a file only if it still matches what Forge wrote; otherwise it is left alone and reported.

## Integration levels
1 Forge-generated (full) | 2 known structure (new files; dependency edits are advisory) |
3 conventional third-party (same) | 4 unknown (read-only).

## Patches, locks and the verification sandbox
* `patching.py` is pure text-in/text-out; integration stages edits per file so several patches and a dependency edit can
  share one reviewed change. Registered in `.forge/components.toml` (`[[patches]]`).
* `locks.py`: one mutating operation per project (lock files live in `$FORGE_HOME/locks`); stale locks from dead local
  processes are recovered.
* Verification runs project code with a scrubbed environment (`security.safe_environ`) and the project's own `.venv`
  interpreter when present. Missing third-party packages make a check `not_run` (Blocked), and a run where any check did not
  run is `incomplete`, never `passed`.

## Component artifacts
The artifact digest covers `files/` (relative paths + bytes, ignoring `__pycache__`/`.pyc`) **and** `component.toml`. `forge catalog` scans
verify the digest; mismatches are quarantined. Release tooling: `forge component seal`. See `docs/component-authoring.md`.

## Writing a component
Create `<catalog root>/<id>/<version>/component.toml` and `files/`, then seal it. Put the directory in
`$FORGE_HOME/catalog/` (or list it under `catalog_roots` in `$FORGE_HOME/settings.toml`). Use any built-in
manifest as a template; contributed files may use `{{package}}`.


## Database migrations (C-29)
Database migrations are deliberately outside Forge's file-patch recovery transaction.
Install the optional `migrations` extra to use `app_forge.migrations.MigrationRunner`.
Planning reads the current Alembic revision and available heads without changing the
database. Upgrades require explicit `confirm_irreversible=True`, take an exclusive
migration lock, and write an atomic, owner-private JSON operation journal that omits
the database URL. Forge never runs Alembic downgrade as failure recovery. A failed
operation or a journal left in `running` state after a crash requires an operator to
inspect the live database revision and reconcile it before another attempt. Configure
a durable journal directory and protect the Alembic configuration and credentials.
