"""Command line interface: ``eaedit``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import click
import sqlalchemy as sa
import yaml

from eacore.backends.sql import ConcurrentModificationError, NotAnEaRepositoryError, RepositoryLockedError
from eacore.catalogue import AmbiguousStereotype, save_yaml_all
from eaedit.catalogue import load_catalogues
from eaedit.catalogue.merge import by_profile
from eaedit.changefile import replay
from eaedit.errors import CommitRefusedError, EaeditError
from eaedit.scope import POLICIES
from eaedit.session import Session

EXISTING = click.Path(exists=True, dir_okay=False)


def _line(exc: BaseException) -> str:
    text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return text + "".join(f" ({note})" for note in getattr(exc, "__notes__", []))


@contextmanager
def _errors() -> Iterator[None]:
    """Turn expected failures into a one-line ``click`` error instead of a traceback."""
    try:
        yield
    except CommitRefusedError as exc:
        for issue in exc.issues:
            click.echo(f"{issue.severity:7} {issue.rule:20} {issue.message}", err=True)
        raise click.ClickException(_line(exc)) from None
    except (EaeditError, AmbiguousStereotype, RepositoryLockedError, ConcurrentModificationError) as exc:
        raise click.ClickException(_line(exc)) from None
    except NotAnEaRepositoryError as exc:
        raise click.ClickException(f"{exc}: not an Enterprise Architect repository (no t_object table)") from None
    except sa.exc.DatabaseError as exc:
        reason = str(exc.orig) if exc.orig is not None else str(exc).splitlines()[0]
        raise click.ClickException(f"cannot read database: {reason}") from None
    # A wrongly typed argument in a change file fails inside the operation; still one line, not a traceback.
    except (yaml.YAMLError, ValueError, TypeError, KeyError, OSError) as exc:
        raise click.ClickException(_line(exc)) from None


@click.group()
def cli() -> None:
    """Edit Enterprise Architect repositories through change files and stereotype catalogues."""


@cli.group()
def catalogue() -> None:
    """Build and inspect stereotype catalogues."""


@catalogue.command("build")
@click.argument("sources", nargs=-1, required=True, type=EXISTING)
@click.option("-o", "--output", required=True, type=click.Path(dir_okay=False), help="YAML file to write.")
def catalogue_build(sources, output) -> None:
    """Merge MDG XML, .qea (inferred) and YAML SOURCES into one catalogue per profile."""
    with _errors():
        merged = by_profile(load_catalogues(sources))
        save_yaml_all(merged, output)
    click.echo(f"{len(merged)} profile(s), {sum(len(c.stereotypes) for c in merged)} stereotype(s) -> {output}")


@catalogue.command("show")
@click.argument("source", type=EXISTING)
@click.argument("stereotype", required=False)
def catalogue_show(source, stereotype) -> None:
    """List a catalogue's stereotypes, or show one with its inherited tags and constraints."""
    with _errors():
        catalogues = load_catalogues([source])
        if stereotype is None:
            for fq in catalogues.fqnames():
                definition = catalogues.stereotype(fq)
                applies = ", ".join(catalogues.resolved(fq).applies_to)
                click.echo(
                    f"{fq}" + (" (abstract)" if definition.abstract else "") + (f"  [{applies}]" if applies else "")
                )
            return
        resolved = catalogues.resolved(stereotype)
        if resolved is None:
            raise click.ClickException(f"no stereotype {stereotype!r} in {source}")
    definition = resolved.definition
    click.echo(resolved.fqname + (" (abstract)" if definition.abstract else ""))
    click.echo(f"  source: {resolved.source.kind} {resolved.source.file}".rstrip())
    click.echo(f"  applies to: {', '.join(resolved.applies_to) or '-'}")
    if definition.generalizes:
        click.echo(f"  generalizes: {', '.join(definition.generalizes)}")
    for tag in resolved.tags:
        details = [f"type={tag.type}" if tag.type else "", f"default={tag.default!r}" if tag.default else ""]
        details.append(f"values={','.join(tag.values)}" if tag.values else "")
        click.echo(f"  tag {tag.name} {' '.join(d for d in details if d)}".rstrip())
    for constraint in resolved.constraints:
        click.echo(f"  constraint {constraint.role}: {constraint.target}")


def _session_options(fn):
    fn = click.option(
        "--policy", type=click.Choice(POLICIES), default="connected", show_default=True, help="Scope policy."
    )(fn)
    fn = click.option("--author", help="Record this author instead of the change file's.")(fn)
    fn = click.option("--focus", "focus", multiple=True, help="Package (qualified name or GUID) to keep edits in.")(fn)
    fn = click.option("-c", "--catalogue", "catalogues", multiple=True, type=EXISTING, help="YAML, MDG XML or .qea.")(
        fn
    )
    fn = click.argument("changes", type=EXISTING)(fn)
    return click.argument("model", type=EXISTING)(fn)


def _replayed(model, changes, catalogues, focus, policy, author) -> Session:
    session = Session.open(model, focus=focus, policy=policy, catalogues=catalogues)
    replay(session, changes, author=author)
    preview = session.preview()
    click.echo(preview.report)
    if preview.outside_focus:
        click.echo(f"outside the focus: {', '.join(preview.outside_focus)}")
    for issue in preview.new_issues:
        click.echo(f"new issue: {issue.severity} {issue.rule} {issue.message}")
    for warning in preview.warnings:
        click.echo(f"warning: {warning}")
    return session


@cli.command()
@_session_options
def preview(model, changes, catalogues, focus, policy, author) -> None:
    """Replay CHANGES on a working copy of MODEL and print what would change; MODEL is not written."""
    with _errors():
        _replayed(model, changes, catalogues, focus, policy, author)


@cli.command()
@_session_options
def apply(model, changes, catalogues, focus, policy, author) -> None:
    """Replay CHANGES on MODEL and commit them; exit status 1 if the commit is refused."""
    with _errors():
        session = _replayed(model, changes, catalogues, focus, policy, author)
        committed = session.commit()
    total = len(committed.inserts) + len(committed.updates) + len(committed.deletes)
    click.echo(f"committed {total} change(s) to {model}")
