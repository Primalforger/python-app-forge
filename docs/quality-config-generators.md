# Manifest-driven quality configuration

The app_forge.quality module turns an optional TOML [quality] table into
reviewable pre-commit and import-linter configuration files. It does not install
tools, edit a project, run hooks, or access the network.

A template or project manifest can declare:

```toml
[quality]
pre_commit = true
import_linter = true

[[quality.contracts]]
name = "domain stays isolated"
source_modules = ["example_app.domain"]
forbidden_modules = ["example_app.gui", "example_app.infrastructure"]
```

Load the TOML with tomllib and render it using the generated package name:

```python
import tomllib
from pathlib import Path

from app_forge.quality import render_quality_files

manifest = tomllib.loads(Path("template.toml").read_text(encoding="utf-8"))
files = render_quality_files(manifest, package="example_app")
for relative_path, contents in files.items():
    print(relative_path, contents)
```

The renderer returns .pre-commit-config.yaml with pinned whitespace,
end-of-file, YAML and TOML checks plus a local Ruff hook. The local hook expects
Ruff to be installed in the environment that runs pre-commit. Install
pre-commit, ruff and, when import boundaries are enabled, import-linter in the
project's development environment.

.importlinter is native TOML. Each declared contract becomes an import-linter
forbidden contract; module names must be valid dotted identifiers under the
configured root package. Import-linter must be installed and run explicitly
(for example, lint-imports). The tool configuration is a guardrail, not
a substitute for reviewing architecture decisions.

Both outputs are deterministic. Invalid or ambiguous manifest values fail
closed, and generation returns text only; callers decide whether and how to
write the files. The default manifest behavior enables pre-commit hygiene hooks
and leaves import-linter disabled until at least one explicit contract exists.
