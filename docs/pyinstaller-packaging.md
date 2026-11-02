# PyInstaller packaging

Forge reads a `[packaging.pyinstaller]` table from a TOML project or template
manifest and produces a deterministic, reviewable PyInstaller spec file. It
does not install PyInstaller or run a build unless the explicit build command
is requested.

```toml
[packaging.pyinstaller]
name = "ExampleDesktop"
entry_point = "src/example_app/main.py"
onefile = true
windowed = true
platforms = ["windows", "macos", "linux"]
hidden_imports = ["example_app.plugins"]
collect_submodules = ["example_app.plugins"]
excludes = ["tkinter"]
datas = [["assets/logo.png", "assets"]]
# icon = "assets/app.ico" # use .ico on Windows and .icns/.png on macOS
```

Generate the spec without overwriting an existing file:

```sh
forge package spec project.toml --project . --out packaging/forge.spec
```

Build the spec on the current native operating system:

```sh
forge package build project.toml --project . --spec packaging/forge.spec --distpath dist --workpath build/pyinstaller
```

Install the optional extra with `pip install "python-app-forge[packaging]"`.
PyInstaller builds are platform-specific: run the build on each target OS
(Windows, macOS and Linux) rather than treating a cross-platform spec as a
cross-compiler. The manifest's `platforms` list is an explicit support
declaration; CI and release automation should execute native builds for every
declared platform. A spec generated on one OS can be reviewed elsewhere, but
binary artifacts must be produced and tested on their target OS.

Entry points, icons, and data sources must be project-relative, existing
files; symlink escapes and path traversal are rejected. Data destinations
must be relative paths. Hidden imports, collected packages and exclusions
must be valid dotted Python module names. The generated spec uses literal
values only. Build execution uses the current interpreter, an argument vector,
a project-local spec and no shell. Build output is bounded in the CLI report.
