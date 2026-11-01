# Change-impact records

Use `app_forge.change_impact` to create an analyst-authored assessment before a change is approved or implemented.

```python
from app_forge.change_impact import (
    ChangeImpact, render_change_impact, to_compliance_record,
    validate_change_impact,
)
from app_forge.compliance_artifacts import validate_artifact

assessment = ChangeImpact(
    change_id="CHG-104",
    title="Replace session token storage",
    description="Move tokens from local storage to secure cookies.",
    change_type="security",
    affected_systems=("web client", "authentication API"),
    impacted_requirements=("SEC-01", "AUTH-04"),
    impact_level="high",
    impact_assessment="Authentication behavior and browser integration change.",
    compatibility="Coordinate rollout with existing clients.",
    security_privacy="Review cookie flags and cross-site request protections.",
    operational="Monitor authentication failures.",
    data_migration="Invalidate or safely migrate existing sessions.",
    rollback_plan="Restore the previous token flow and revoke new sessions.",
    verification_plan="Run integration tests and inspect browser cookie flags.",
    owner="Identity team",
)
validated = validate_change_impact(assessment)
markdown = render_change_impact(validated)
cmp09 = to_compliance_record(validated)
validate_artifact("CMP-09", cmp09)
```

The CMP-09 adapter retains the established required fields (`change`,
`impacted_requirements`, and `impact_assessment`) and adds structured optional
metadata for affected systems, type, impact level, date, status, and owner.
Pass the resulting record to the existing compliance artifact storage workflow.

An empty impacted-requirements list is represented explicitly as an incomplete
traceability review, rather than as evidence that no requirements are affected.
The generator does not discover dependencies, assign impact on its own, or
approve a change. Owners must validate the assessment and record approvals
through the project's change-control process.
