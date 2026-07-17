"""Command-line interface — the first adapter onto the core.

Kept intentionally thin: it parses arguments, calls into the (not-yet-built)
orchestration engine, and renders output with Rich. Registered as the
``assistant`` console script in ``pyproject.toml``.
"""

from __future__ import annotations

import typer
from rich.console import Console

from ai_assistant import __version__

app = typer.Typer(
    name="assistant",
    help="A model-agnostic AI operating system — deeply personalized assistant.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback()
def main() -> None:
    """Root command group. Keeps subcommands addressable by name."""


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"ai-assistant [bold cyan]{__version__}[/]")


if __name__ == "__main__":
    app()
