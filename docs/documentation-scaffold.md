# Documentation scaffold library

The dependency-free library renders a starter documentation tree for a Python project. It does not install MkDocs or any site-generation dependency.

```python
from app_forge.documentation_scaffold import (
    DocumentationProject,
    create_documentation_scaffold,
    render_documentation,
)

project = DocumentationProject(
    name="Example",
    description="An example Python package.",
    package_name="example",
    python_requires=">=3.11",
    license="MIT",
    repository_url="https://github.com/example/example",
)

files = render_documentation(project)  # relative path -> UTF-8 Markdown/YAML
created = create_documentation_scaffold("./my-project", project)
```

The scaffold contains `mkdocs.yml` plus overview, getting-started, configuration, CLI, architecture, security, API and contributing pages. Rendering is deterministic for identical metadata. Project names and descriptions are quoted safely in YAML; package names must be dotted Python identifiers; repository links must be HTTPS URLs without embedded credentials.

Creation is intentionally non-destructive: if any target file already exists, it raises `FileExistsError` and does not replace content. Symlinked documentation roots and subdirectories are refused. Generated pages are prompts for maintainers to complete and review, not verified project documentation; in particular, the security page is not a threat assessment or certification.
