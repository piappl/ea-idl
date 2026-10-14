"""Command line interface: ``eacore``."""

import json
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click
import sqlalchemy as sa

from eacore.backends.sql import NotAnEaRepositoryError, load_file
from eacore.diff import diff
from eacore.history import extract_version
from eacore.report import dump_text, render_text, to_json
from eacore.tablemap import EA_TABLEMAP

FORMAT = click.Choice(["text", "json"])


@contextmanager
def _errors(path) -> Iterator[None]:
    """Turn expected failures about ``path`` into a one-line ``click`` error instead of a traceback."""
    try:
        yield
    except NotAnEaRepositoryError:
        raise click.ClickException(f"{path}: not an Enterprise Architect repository (no t_object table)") from None
    except FileNotFoundError as exc:
        if exc.filename == "git":
            raise click.ClickException(f"{path}: git is not installed") from None
        raise click.ClickException(f"{path}: file not found") from None
    except sa.exc.DatabaseError as exc:
        reason = str(exc.orig) if exc.orig is not None else str(exc).splitlines()[0]
        raise click.ClickException(f"{path}: cannot read database: {reason}") from None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise click.ClickException(f"{path}: git failed: {detail[0] if detail else exc}") from None


def _load(path):
    with _errors(path):
        return load_file(path)


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
            with _errors(paths[0]):
                a = extract_version(revs[0], Path(paths[0]), Path(tmp) / "a.qea")
                b = extract_version(revs[1], Path(paths[0]), Path(tmp) / "b.qea")
                before, after = load_file(a), load_file(b)
        else:
            if len(paths) != 2:
                raise click.UsageError("give two repositories: A B")
            before, after = _load(paths[0]), _load(paths[1])
    changes = diff(before, after)
    if ignore_volatile:
        changes = changes.without_columns(EA_TABLEMAP.volatile)
    click.echo(render_text(changes, before, after) if fmt == "text" else to_json(changes))


@cli.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def textconv(path) -> None:
    """Print a stable text form of a repository (for git's diff.<driver>.textconv)."""
    click.echo(dump_text(_load(path)), nl=False)


@cli.command("check")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "fmt", type=FORMAT, default="text", show_default=True)
def check_command(path, fmt) -> None:
    """Check repository integrity; exit status 1 if any error is found."""
    from eacore.integrity import check
    from eacore.records import key_str

    issues = check(_load(path))
    if fmt == "json":
        click.echo(
            json.dumps(
                [
                    {
                        "severity": i.severity,
                        "rule": i.rule,
                        "ref": key_str(i.ref) if i.ref else None,
                        "message": i.message,
                    }
                    for i in issues
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for issue in issues:
            click.echo(f"{issue.severity:7} {issue.rule:20} {issue.message}")
        errors = sum(i.severity == "error" for i in issues)
        click.echo(f"{errors} error(s), {len(issues) - errors} warning(s)")
    if any(i.severity == "error" for i in issues):
        raise SystemExit(1)


@cli.command("history")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "out_dir", type=click.Path(file_okay=False), required=True, help="Output directory.")
@click.option(
    "--template", type=click.Path(exists=True, dir_okay=False), default=None, help="Empty .qea for round-trips."
)
def history_command(path, out_dir, template) -> None:
    """Diff and check every git version of PATH; write per-commit diffs and summary.md."""
    from eacore.history import run_history

    with _errors(path):
        summary = run_history(Path(path), Path(out_dir), Path(template) if template else None)
    click.echo(f"{len(summary['versions'])} versions, {len(summary['pairs'])} diffs -> {out_dir}/summary.md")
