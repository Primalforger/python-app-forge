"""Guard: the tests must exercise THIS checkout, not another installed copy of app_forge.

A stale `pip install -e .` from an older folder silently runs old platform code against new tests and
produces dozens of misleading failures. Fail fast and say how to fix it.
"""
import pathlib

import app_forge

_root = pathlib.Path(__file__).resolve().parent.parent
_loaded = pathlib.Path(app_forge.__file__).resolve()
if _root not in _loaded.parents:
    raise ImportError(
        f"\nThese tests are in {_root}\nbut app_forge is being imported from {_loaded.parent}.\n"
        "Run `pip install -e .` inside this folder (or set PYTHONPATH=src), then try again.")
