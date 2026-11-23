"""The `gitwarden` command. Task 11 adds scan, install, uninstall, allow and rules."""

from typing import Annotated

import typer

from gitwarden import __version__

app = typer.Typer(
    help="GitWarden blocks secrets before they leave your machine.",
    no_args_is_help=True,
    add_completion=False,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"gitwarden {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """GitWarden blocks secrets before they leave your machine."""
