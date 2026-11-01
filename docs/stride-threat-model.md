# STRIDE Threat-Model Worksheet

Forge provides a dependency-free worksheet for documenting analyst-identified
threats using the six STRIDE categories: Spoofing, Tampering, Repudiation,
Information Disclosure, Denial of Service, and Elevation of Privilege.

## Author and render a model

```python
from app_forge.threat_model import (
    STRIDECategory, Threat, ThreatModel, render_threat_model,
    to_compliance_record,
)
from app_forge.compliance_artifacts import save_artifact

model = ThreatModel(
    system="Payments API",
    scope="Public API, worker, and payment database.",
    assets=("customer data", "payment credentials"),
    trust_boundaries=("Internet to API gateway", "API to database"),
    threats=(
        Threat(
            id="THR-001",
            category=STRIDECategory.SPOOFING,
            asset="payment credentials",
            description="Stolen credentials may impersonate a customer.",
            impact="Unauthorized payment activity.",
            mitigation="Require MFA and rotate compromised credentials.",
            residual_risk="Phishing remains possible.",
        ),
    ),
)
markdown = render_threat_model(model)
# Optional: persist the validated assessment through the CMP-08 workflow.
save_artifact("path/to/project", "CMP-08", to_compliance_record(model))
```

Every threat has a unique identifier, a STRIDE category, a declared asset,
description, impact, mitigation, and residual-risk statement. Models require a
system, scope, and at least one asset. Trust boundaries are recorded when known.
The renderer includes all six categories and review prompts. An empty category
is explicitly labelled as unassessed, not as proof that no threat exists.

The CMP-08 adapter produces the existing security-assessment record shape, so
the result can be stored and included in the project's compliance evidence
package using the established compliance workflow.

This is an authoring aid, not an automated threat-discovery engine, penetration
test, or security certification. A qualified reviewer must validate the system
boundaries, threats, mitigations, evidence, and residual-risk decisions.
