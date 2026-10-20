"""Command line interface: ``eaedit``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click
import sqlalchemy as sa
import yaml

from eacore.backends.sql import ConcurrentModificationError, NotAnEaRepositoryError, RepositoryLockedError
from eacore.catalogue import AmbiguousStereotype, save_yaml_all
from eaedit.catalogue import load_catalogues
from eaedit.catalogue.merge import by_profile
from eaedit.changefile import replay
from eaedit.diagrams.svg import export_svg, import_svg
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


def _report(session: Session, out: str | None = None) -> None:
    preview = session.preview()
    click.echo(preview.report)
    if preview.outside_focus:
        click.echo(f"outside the focus: {', '.join(preview.outside_focus)}")
    for issue in preview.new_issues:
        click.echo(f"new issue: {issue.severity} {issue.rule} {issue.message}")
    for warning in preview.warnings:
        click.echo(f"warning: {warning}")
    if out and preview.diagrams:
        folder = Path(out)
        folder.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        for rendered in preview.diagrams.values():
            # A diagram name is free text: keep it a plain file name, and keep two diagrams of one name apart.
            stem = "".join("_" if c in '/\\:*?"<>|' else c for c in rendered.name).strip() or "diagram"
            name, count = stem, 1
            while name.lower() in used:
                count += 1
                name = f"{stem} ({count})"
            used.add(name.lower())
            (folder / f"{name}.svg").write_text(rendered.svg, encoding="utf-8")
            click.echo(f"diagram: {folder / f'{name}.svg'}")


def _replayed(model, changes, catalogues, focus, policy, author, out=None) -> Session:
    session = Session.open(model, focus=focus, policy=policy, catalogues=catalogues)
    replay(session, changes, author=author)
    _report(session, out)
    return session


@cli.command()
@click.option("--out", type=click.Path(file_okay=False), help="Folder for an SVG of each diagram the changes touch.")
@_session_options
def preview(model, changes, catalogues, focus, policy, author, out) -> None:
    """Replay CHANGES on a working copy of MODEL and print what would change; MODEL is not written."""
    with _errors():
        _replayed(model, changes, catalogues, focus, policy, author, out)


@cli.command()
@_session_options
def apply(model, changes, catalogues, focus, policy, author) -> None:
    """Replay CHANGES on MODEL and commit them; exit status 1 if the commit is refused."""
    with _errors():
        session = _replayed(model, changes, catalogues, focus, policy, author)
        committed = session.commit()
    total = len(committed.inserts) + len(committed.updates) + len(committed.deletes)
    click.echo(f"committed {total} change(s) to {model}")


@cli.group()
def diagram() -> None:
    """Export a diagram as eaedit SVG, or import an edited one."""


@diagram.command("export")
@click.argument("model", type=EXISTING)
@click.argument("diagram")
@click.option("-o", "--output", required=True, type=click.Path(dir_okay=False), help="SVG file to write.")
@click.option("-c", "--catalogue", "catalogues", multiple=True, type=EXISTING, help="YAML, MDG XML or .qea.")
def diagram_export(model, diagram, output, catalogues) -> None:
    """Write DIAGRAM (qualified name or GUID) as eaedit SVG."""
    with _errors():
        session = Session.open(model, policy="off", catalogues=catalogues)
        svg = export_svg(session, diagram)
        Path(output).write_text(svg, encoding="utf-8")
    click.echo(f"{diagram} -> {output}")


@diagram.command("import")
@click.argument("model", type=EXISTING)
@click.argument("svg", type=EXISTING)
@click.option("--owner", help="Package (qualified name or GUID) for a new diagram, when the file names none.")
@click.option("--apply", "apply_", is_flag=True, help="Commit the changes; without it they are only previewed.")
@click.option("--out", type=click.Path(file_okay=False), help="Folder for an SVG of each diagram the import changes.")
@click.option("--policy", type=click.Choice(POLICIES), default="connected", show_default=True, help="Scope policy.")
@click.option("--focus", "focus", multiple=True, help="Package (qualified name or GUID) to keep edits in.")
@click.option("-c", "--catalogue", "catalogues", multiple=True, type=EXISTING, help="YAML, MDG XML or .qea.")
@click.option("--author", help="Record this author.")
def diagram_import(model, svg, owner, apply_, out, policy, focus, catalogues, author) -> None:
    """Stage the difference between SVG (eaedit SVG) and its diagram; commit it with --apply."""
    with _errors():
        session = Session.open(model, focus=focus, policy=policy, catalogues=catalogues, author=author)
        import_svg(session, Path(svg).read_text(encoding="utf-8"), owner=owner)
        if session.changes().is_empty():
            click.echo("no changes")
        _report(session, out)
        if apply_ and not session.changes().is_empty():
            committed = session.commit()
            total = len(committed.inserts) + len(committed.updates) + len(committed.deletes)
            click.echo(f"committed {total} change(s) to {model}")
