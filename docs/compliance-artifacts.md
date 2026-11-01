# Compliance artifacts and software bill of materials

App Forge can retain five structured project compliance records. These are authored inputs, not claims inferred by Forge:

| ID | Record | Required content |
|---|---|---|
| CMP-05 | Interface control | Interface name, provider, version and contract |
| CMP-08 | Security assessment | Scope, assets, threats, mitigations and residual risks |
| CMP-09 | Change impact | Change, impacted requirements and impact assessment |
| CMP-10 | Release evidence | Release, verification run, artifacts and approvals |
| CMP-11 | Exceptions register | Exception ID, requirement, approver, rationale and expiry |

Create a JSON file containing the record fields, then validate and store it:

```bash
forge compliance artifact CMP-08 --project ./my-app --input security-assessment.json
forge compliance artifact CMP-09 --project ./my-app --input change-impact.json
forge compliance artifact CMP-11 --project ./my-app --input exceptions.json
```

Records are stored under `.forge/compliance/`. Re-running a record type replaces that type's prior record. Forge validates required fields, non-empty collections, nested record fields, unique interface/exception identifiers and ISO-formatted exception expiry dates. Records are revalidated when loaded, and symlinked metadata targets are refused. The input remains under human control: Forge does not invent threat assessments, approvals, exceptions or verification results.

## SBOM and licence policy

Generate offline CycloneDX 1.5 and SPDX 2.3 JSON:

```bash
forge compliance sbom --project ./my-app --out ./evidence/sbom
```

The SBOM includes installed Forge components and declared Python dependencies. Declared dependencies without resolved versions are represented as `UNKNOWN`; Forge does not pretend a requirement specifier is an installed package version.

Check declared Forge-component licence identifiers against an explicit deny list:

```bash
forge compliance licenses --project ./my-app --deny-license GPL-3.0-only --deny-license AGPL-3.0-only
```

A denied identifier produces a non-zero validation exit code. Missing licence metadata, and Python dependencies whose licence cannot be established from the local project metadata, appear in `unknown` and are never silently treated as approved. This is a conservative metadata check, not a legal opinion or a complete transitive dependency licence audit.

## Evidence package

`forge compliance package-evidence` includes the compliance report, retained verification evidence, project inventory, all validated compliance records, CycloneDX and SPDX SBOMs, and the licence-policy report. Every file is listed in `MANIFEST.sha256.json` with its SHA-256 digest.

The package is an integrity-checked collection of source records and generated inventories. A hash manifest detects accidental changes; it is not a digital signature, authenticity proof, or certification.
