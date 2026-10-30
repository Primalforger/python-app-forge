# Writing a component

A component is a versioned folder you can add to the catalog. It can **add files** to a project and **patch existing files** at
safe, named places. Everything it does goes through the normal plan → approve → checkpoint → apply → verify → recover flow.

## Quick start (CLI only)

```bash
forge component new acme.widget --out ./my-components --archetype cli,service --summary "Adds a widget"
# edit ./my-components/acme.widget/1.0.0/component.toml and files/
forge component validate ./my-components/acme.widget/1.0.0     # schema, digest, python syntax, tests, patches
forge component seal     ./my-components/acme.widget/1.0.0     # re-seal after any edit
forge catalog add        ./my-components/acme.widget/1.0.0     # copy into your catalog ($FORGE_HOME/catalog)
forge component verify   acme.widget                           # builds a throwaway project and runs its tests
forge component pack     ./my-components/acme.widget/1.0.0 --out acme.widget-1.0.0.zip   # reproducible archive
forge catalog add acme.widget-1.0.0.zip                         # on another machine
```

## Layout

```
<id>/<version>/component.toml
<id>/<version>/files/...          # everything the component contributes
```
Versions are immutable: a released version is never edited, publish a new one.

## Contributing files

```toml
[[integration.files]]
src  = "files/src/widget.py"            # under files/
dest = "src/{{package}}/widget.py"      # {{package}} = the target project's Python package
```
Forge never overwrites an existing file that differs; that is a conflict you must resolve. Contributed files are text (UTF-8).
Declare tests so the component can prove itself: `[verification] tests = ["tests/test_widget.py"]` (they must also be contributed).

## Patching existing files

Add `[[integration.patches]]` entries. Forge records each patch in `.forge/components.toml`, wraps inserted text in marker comments
(`forge:begin <component>:<id>` … `forge:end …`), skips it if already present, replaces it on upgrade, and removes it on uninstall
(**only if nobody edited the block**).

| kind | what it does | notes |
|---|---|---|
| `insert` | adds `content` before/after a line containing `forge:anchor <name>` | keeps the anchor's indentation and the file's line endings; `comment` = `#` (default), `//`, `--`, `;`, `%` |
| `toml-table` | appends new `[tables]` to a TOML file | never edits an existing table; conflicts if a table exists with different values; result is re-parsed to prove it is valid |
| `json-merge` | adds missing keys (and missing list items) to a JSON file | the file is re-serialised; **removal is manual**; conflicting values are a conflict |

```toml
[[integration.patches]]
id       = "register-healthz"            # unique within the component
file     = "src/{{package}}/api.py"
kind     = "insert"
anchor   = "routers"                     # target has a line like:  # forge:anchor routers
position = "after"
content  = '''
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
'''
```
Anchors shipped in Forge's templates: web `routers` (api.py), cli `commands` (cli.py), service `jobs` (service.py),
desktop `widgets` (app.py). Third-party projects can add `forge:anchor <name>` comments themselves.

Plan-time failures you may see: `anchor-missing`, `anchor-ambiguous`, `patch-target-missing`, `patch-exists-different`,
`patch-modified`, `config-key-conflict`, `target-unparseable`, `patch-on-new-file`. All stop the plan; Forge never guesses.

## Dependencies

* Other components: `[dependencies.components] "forge.themes" = "^1.0"`.
* Python packages: `python_packages = ["attrs>=23"]`. Forge compares each with the project's existing requirements: absent → added
  (Forge projects) or advised (others); incompatible → conflict; looser than needed → flagged for review; never silently rewritten.
* Interfaces are versioned contracts, separate from component-to-component dependencies: `provides = ["ui.table@1.0"]` declares an exact interface version; `requires = ["ui.themes@^1.0"]` accepts any compatible provider version. A requirement without `@` accepts any version. Providers must declare a version; requirements may use the normal Forge constraints (`^`, `~`, comparisons, or `*`). Forge validates declarations when loading a catalog and checks requirements against providers selected for installation or already present in the project. Missing providers report `missing-interface`; providers with no matching version report `incompatible-interface`.

## Rules worth knowing

* The digest covers `files/` **and** `component.toml`: change anything → `forge component seal`.
* Declare every permission you need (`filesystem.project`, `network`, `process`, …). Presence in a catalog authorises nothing.
* `trust = "builtin"` is reserved for components shipped inside App Forge.
* Never put secrets in a component; `validate` warns if it spots one.
