# Multi-archetype projects

Forge ships composite templates that combine more than one application archetype in a single generated Python package:

- Run forge init --template desktop-worker --name "Desktop Workbench" to combine the PySide6 desktop shell with a namespaced background scheduler.
- Run forge init --template web-scheduler --name "Web Scheduler" to combine the FastAPI application with a namespaced background scheduler.

Both templates keep one src/<package>/ root. The desktop or web application retains the project's primary entry point; the worker's scheduler and service runner live beside it as scheduler.py and service.py. The worker is available as application code and is not silently launched as a second process during application startup.

Composite template manifests pin their included template IDs and versions. The generated forge.toml records the primary archetype and the complete project.archetypes set. Component resolution accepts components compatible with any archetype in that set, including dependencies resolved transitively.

Composite templates are versioned as a single template identity. Their template baseline snapshots the complete rendered tree and records all archetypes, so forge project update continues to use the normal reviewed three-way update workflow. A change to the archetype set is rejected as a template identity change rather than silently reclassifying the project.

The renderer deduplicates identical shared files and rejects different-content path collisions. It does not merge two competing implementations of the same module; template authors must namespace those modules explicitly.
