# Forge extension starter

This project advertises its extension through the `app_forge.plugins` Python
entry-point group. Forge discovers entry-point metadata without importing the
extension module.

## Development

1. Install the package in the environment where Forge runs.
2. Inspect it with `forge plugin list` / `forge plugin inspect {{package}}`.
3. Review the source and explicitly trust and enable it before invocation.
4. Keep arguments and return values JSON-serializable.

## Security boundary

The Forge extension host requires explicit trust and enablement. On supported
Linux systems, invocation uses bubblewrap isolation and refuses an unsandboxed
fallback. This starter does not make arbitrary extension code safe: review code
before trusting it, and do not assume the process boundary alone protects
against malicious code on unsupported hosts.
