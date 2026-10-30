# Standards applicability register (CMP-01, proposed baseline)

Applicable editions, licensing and scope must be confirmed before formal adoption. Nothing here claims compliance.

| Reference | Used for | Evidence in this repo |
|---|---|---|
| ISO/IEC/IEEE 29148 | Requirement IDs, acceptance criteria, traceability | `requirements.toml`, `forge trace`, `forge compliance` |
| ISO/IEC/IEEE 12207 | Lifecycle activities | `docs/adr/`, release gates in `docs/spec-coverage.md` |
| IEEE 1016 (where applicable) | Design description | `docs/architecture.md` |
| MOSA principles | Modularity, open interfaces, conformance tests | manifest schema, architecture rules test, `forge component verify` |
| PyPA specifications | Packaging, entry points | `pyproject.toml`, `app_forge.plugins` group |
| OWASP ASVS (web targets) | Security verification of web projects | **Not yet implemented** in the web template |
