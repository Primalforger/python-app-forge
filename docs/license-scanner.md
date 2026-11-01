# Licence scanner

The offline licence scanner evaluates licence metadata already present in a supply-chain inventory. It does not download package metadata, infer licences from package names, or provide legal advice.

```python
from app_forge.license_scanner import scan_licenses

report = scan_licenses(
    inventory,
    denied_licenses=("GPL-3.0-only", "AGPL-3.0-only"),
)
if not report["ok"]:
    raise SystemExit(f"Denied licences: {report['findings']}")
```

## Policy semantics

- SPDX expressions are parsed with the `WITH`, `AND`, `OR`, and parenthesis grammar. Malformed expressions fail closed with `ValidationFailure`.
- Deny-list matching is case-insensitive and checks every licence identifier in a compound expression. Exception identifiers after `WITH` are not treated as licence identifiers.
- Missing, `NOASSERTION`, and unknown component licences are listed under `unknown`. Python dependencies without resolved package metadata are separately marked unresolved. Neither is silently approved.
- `ok` means only that no configured denied identifier was found. It does not mean every dependency has known metadata or that the project is legally compliant.

The scanner is dependency-free and performs no network or filesystem access.
