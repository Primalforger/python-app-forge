# Template baseline storage

Newly generated projects store their template baseline at
`.forge/template-baseline.json`. The document records the template ID,
version, archetype, and exact UTF-8 text of each rendered template-owned file.
Component contributions and Forge's own project metadata are intentionally
excluded; they have separate ownership and update lifecycles.

Each file record has a SHA-256 digest, and the canonical metadata envelope has
its own SHA-256 digest. `app_forge.templates.baseline.load_baseline` validates
the schema, document shape, safe relative paths, content hashes, and envelope
hash before returning data. Unsupported schema versions fail closed.

This baseline is a merge input, not an authenticity signature: a user who can
edit the project can also recompute its checksums. It protects against
accidental corruption and malformed paths, but does not prove publisher
identity. The snapshot is written as part of the same staged project creation
transaction as the generated files.

Adopted projects do not receive a fabricated baseline. Their original
template-owned content is unknown, so they must be explicitly re-baselined
before a future template upgrade can safely use three-way merging.
