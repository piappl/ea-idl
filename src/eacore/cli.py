"""Command line interface: ``eacore``."""

import tempfile
from pathlib import Path

import click

from eacore.backends.sql import load_file
from eacore.diff import diff
from eacore.history import extract_version
from eacore.report import dump_text, render_text, to_json
from eacore.tablemap import EA_TABLEMAP

FORMAT = click.Choice(["text", "json"])


@click.group()
def cli() -> None:
    """Inspect, compare and check Enterprise Architect repositories."""


@cli.command("diff")
@click.argument("paths", nargs=-1, required=True, type=click.Path(dir_okay=False))
@click.option(
    "--git", "revs", nargs=2, default=None, metavar="REV1 REV2", help="Compare PATH between two git revisions."
)
@click.option("--format", "fmt", type=FORMAT, default="text", show_default=True)
@click.option("--ignore-volatile", is_flag=True, help="Hide columns EA rewrites on every save.")
def diff_command(paths, revs, fmt, ignore_volatile) -> None:
    """Show what changed between two repositories (A B), or one repository between git revisions."""
    with tempfile.TemporaryDirectory() as tmp:
        if revs:
            if len(paths) != 1:
                raise click.UsageError("--git takes exactly one PATH")
            a = extract_version(revs[0], Path(paths[0]), Path(tmp) / "a.qea")
            b = extract_version(revs[1], Path(paths[0]), Path(tmp) / "b.qea")
        else:
            if len(paths) != 2:
                raise click.UsageError("give two repositories: A B")
            a, b = Path(paths[0]), Path(paths[1])
        before, after = load_file(a), load_file(b)
    changes = diff(before, after)
    if ignore_volatile:
        changes = changes.without_columns(EA_TABLEMAP.volatile)
    click.echo(render_text(changes, before, after) if fmt == "text" else to_json(changes))


@cli.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def textconv(path) -> None:
    """Print a stable text form of a repository (for git's diff.<driver>.textconv)."""
    click.echo(dump_text(load_file(path)), nl=False)
