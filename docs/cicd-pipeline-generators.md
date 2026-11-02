# CI/CD pipeline generators

The optional authoring API in `app_forge.cicd` renders starter pipelines for
GitHub Actions and GitLab CI. Both providers receive the same validated
`CICDConfig`, so Python-version matrices and command choices remain aligned.

```python
from app_forge.cicd import CICDConfig, render_cicd_files

files = render_cicd_files(CICDConfig(
    project_name="example-app",
    python_versions=("3.11", "3.12", "3.13"),
    security_audit=True,
))
```

The returned mapping contains `.github/workflows/ci.yml` and
`.gitlab-ci.yml`. Rendering is deterministic and does not write files,
contact providers, create credentials, or trigger deployments. Generated
pipelines run install, optional lint, tests, optional dependency audit and
optional distribution build steps. The GitHub workflow uses read-only
repository contents permissions, pull-request and push triggers, and
cancellation of superseded runs.

These are CI verification starters, not a complete release/deployment
automation system. Configure protected environments, release approvals,
artifact retention, trusted publishing, secret scopes, runner isolation and
deployment credentials in the provider itself. Never commit tokens or
credentials into generated workflow files. Review commands before committing
the generated files; configured command arguments are rendered as shell-safe
argument vectors.
