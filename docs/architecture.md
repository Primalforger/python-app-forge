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

## SQLite repository layer (C-30)

Install the optional `sqlite` extra to use `app_forge.sqlite_repository`.
`SqliteDatabase` owns the SQLAlchemy engine, configures SQLite foreign-key
enforcement, a bounded busy timeout and WAL for file-backed databases, and
provides short-lived sessions plus explicit transaction scopes. Schema creation
is opt-in through `create_schema`; it is never an implicit side effect.

`SqliteRepository` supplies typed-model CRUD, required lookup, validated
filtering, deterministic ordering, bounded pagination and counts. Repository
methods commit atomically and close sessions on both success and failure.
In-memory databases use a shared connection so independent sessions see the
same database. The existing standard-library `SqliteStore` and job queue remain
unchanged; this adapter is an additional SQLAlchemy-backed option.


## PostgreSQL repository layer (C-31)

Install the optional postgres extra to use app_forge.postgres_repository.
PostgresDatabase accepts PostgreSQL SQLAlchemy URLs only, enables connection
pool pre-ping, validates bounded pool settings, and exposes explicit schema
creation, short-lived sessions and atomic transaction scopes. Credentials are
not included in adapter-generated error messages. PostgresRepository provides
typed-model CRUD, required lookup, validated filtering and ordering, bounded
pagination and counts. No connection or schema mutation occurs at import time.


## Web application security baseline (C-32–C-36)

The generated FastAPI template uses PyJWT for short-lived HS256 bearer tokens with fixed algorithm allowlisting, issuer/audience and required time claims. It intentionally does not implement passwords or act as an identity provider: token issuance must follow authentication by an application's trusted identity system. Role dependencies deny by default.

CORS is disabled unless exact origins are configured. The optional rate limiter is process-local and suitable only as a single-process baseline; multi-worker deployments need a shared gateway or store. Browser headers are applied centrally, with HSTS only on HTTPS requests. API errors use RFC 9457 problem details and suppress unexpected exception details. Liveness is independent of dependencies; readiness checks are explicitly registered and fail closed.
