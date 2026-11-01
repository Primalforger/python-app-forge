# Coverage gate

The app_forge.coverage_gate module parses Cobertura XML and evaluates inclusive line and optional branch coverage thresholds using only the Python standard library.

```python
from app_forge.coverage_gate import check_coverage
result = check_coverage("coverage.xml", minimum_line=80, minimum_branch=65)
print(result.to_dict())
if not result.passed:
    raise SystemExit("\n".join(result.failures))
```

Reports are bounded to 10 MiB. Empty, malformed, inconsistent, DTD/entity-containing reports fail closed. A configured branch threshold fails if the report contains no branch data. Thresholds are caller-configured to avoid imposing an arbitrary baseline. This checks report totals; it does not generate coverage data or establish test quality.
