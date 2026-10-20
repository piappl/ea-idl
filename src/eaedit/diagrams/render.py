"""Render a session's diagrams as they will look after commit, from a temporary copy of the model file."""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from eacore.backends.sql import SqlBackend
from eacore.catalogue import CatalogueSet
from eaidl.config import NativeDiagramStyleConfig
from eaidl.native_diagram_extractor import NativeDiagramExtractor
from eaidl.native_diagram_svg import render_svg


@dataclass
class RenderedDiagram:
    guid: str
    name: str
    svg: str
    png: bytes | None


@dataclass
class Ids:
    """GUIDs behind the integer IDs the renderer writes (``data-object-id``, ``data-connector-id``) in the copy."""

    objects: dict[int, str] = field(default_factory=dict)
    connectors: dict[int, str] = field(default_factory=dict)


def colorref_css(value: int | str | None) -> str | None:
    """An EA COLORREF (``0x00BBGGRR``) as CSS ``#rrggbb``; None for unset (-1) or unreadable values."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return f"#{value & 0xFF:02x}{(value >> 8) & 0xFF:02x}{(value >> 16) & 0xFF:02x}"


def stereotype_colors(catalogues: CatalogueSet) -> dict[str, str]:
    """Fill colour by bare stereotype name, from the catalogues' MDG ``bgcolor``; earlier catalogues win."""
    colors: dict[str, str] = {}
    for catalogue in catalogues.catalogues:
        for definition in catalogue.stereotypes:
            css = colorref_css(definition.style.get("bgcolor"))
            if css is not None:
                colors.setdefault(definition.name, css)
    return colors


def _png(svg: str) -> bytes | None:
    """A PNG when a rasterizer happens to be installed; eaedit adds no dependency for it."""
    try:
        import cairosvg  # type: ignore[import-not-found]
    except ImportError:
        return None
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"))


def _ids(path: Path) -> tuple[dict[str, int], Ids]:
    # closing(): sqlite3's own context manager only ends the transaction, it leaves the file open.
    with contextlib.closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        diagrams = {guid: id for id, guid in conn.execute("SELECT Diagram_ID, ea_guid FROM t_diagram")}
        ids = Ids(
            dict(conn.execute("SELECT Object_ID, ea_guid FROM t_object")),
            dict(conn.execute("SELECT Connector_ID, ea_guid FROM t_connector")),
        )
    return diagrams, ids


def render_working(session, diagrams: Iterable[str] | None = None, png: bool = False) -> dict[str, RenderedDiagram]:
    """``diagrams`` (GUIDs or qualified names; all of the working copy's when None) rendered with staged changes.

    The staged changes go to a temporary copy of the model file; the model itself is not touched. Each SVG carries
    the eaedit SVG markup, so a preview can be edited and imported back.
    """
    from eaedit.diagrams.svg import annotate  # svg.py imports this module

    if diagrams is None:
        guids = [r.key for r in session.working.records("t_diagram")]
    else:
        guids = [session.find(d, kinds=("diagram",)).key for d in diagrams]
    style = NativeDiagramStyleConfig(ea_detail_nodes=True, stereotype_bg_colors=stereotype_colors(session.catalogues))
    result: dict[str, RenderedDiagram] = {}
    with tempfile.TemporaryDirectory(prefix="eaedit-render-") as tmp:
        copy = Path(tmp) / session.path.name
        shutil.copyfile(session.path, copy)
        # A model EA has open may be in WAL mode: its latest pages are in the -wal file, not yet in the model.
        for suffix in ("-wal", "-shm"):
            side = session.path.with_name(session.path.name + suffix)
            if side.exists():
                shutil.copyfile(side, copy.with_name(copy.name + suffix))
        changes = session.changes()
        if not changes.is_empty():
            backend = SqlBackend.for_file(copy)
            try:
                backend.load()
                backend.apply(changes)
            finally:
                backend.close()
        numbers, ids = _ids(copy)
        extractor = None
        try:
            extractor = NativeDiagramExtractor.from_url(f"sqlite:///{copy.as_posix()}")
            for guid in guids:
                diagram = extractor.extract_by_id(numbers[guid])
                record = session.working.get("t_diagram", guid)
                svg = annotate(session, record, render_svg(diagram, style), ids)
                result[guid] = RenderedDiagram(guid, diagram.name, svg, _png(svg) if png else None)
        finally:
            if extractor is not None:
                extractor.close()
    return result
