"""Typer entry point. Exit codes: 0 ok, 2 invalid input."""
from __future__ import annotations

import json

import typer
from rich.console import Console

from {{package}}.core import greet

app = typer.Typer(help="{{description}}", add_completion=False)
console = Console()


@app.callback()
def _root() -> None:
    """{{name}}"""


@app.command()
def hello(name: str, shout: bool = False, as_json: bool = typer.Option(False, "--json")) -> None:
    """Greet NAME."""
    try:
        message = greet(name, shout)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2)
    if as_json:
        typer.echo(json.dumps({"message": message}))
    else:
        console.print(message)


# forge:anchor commands


def main() -> int:
    app()
    return 0
