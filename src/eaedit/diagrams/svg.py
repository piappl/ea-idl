"""eaedit SVG: a rendered diagram with ``data-ea-*`` markup, and importing such a file as staged diagram operations.

Only the ``data-ea-*`` attributes are read back; everything else in the file (shapes, text, colours) is presentation.
The rules are documented in ``EAEDIT.md``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from xml.sax.saxutils import escape

from eacore.embedded import duid
from eacore.records import Record, Ref, TextRefs
from eaedit.diagrams.geometry import Rect, check_rect, from_ea
from eaedit.diagrams.render import Ids, render_working
from eaedit.errors import EditWarning, InvalidOperationError, NotFoundError
from eaedit.ops.diagrams import _link_key, _objects
from eaedit.resolve import guid_of
from eaedit.session import OpResult

OBJECT_KINDS = ("element", "note", "readonly")
LINE_KINDS = ("notelink", "message")

#: Objects eaedit has no operation for, carried through unchanged: interaction fragments (p6 in nafv4.qea) and
#: the diagram-only Boundary and Text objects, whose object styles no hand-made row in nafv4.qea shows.
READONLY_TYPES = frozenset({"InteractionFragment", "Boundary", "Text"})

_TAG = re.compile(r'<g\b[^>]*?\bdata-(object|connector)-id="(\d+)"[^>]*?(/?)>')
_OFFSET = re.compile(r"(?<![A-Za-z$])SY=(-?\d+)")
_MDG = re.compile(r"(?:^|;)MDGDgm=([^;]*)")


def _attr(value: object) -> str:
    # Newlines and tabs as character references: an XML parser turns literal ones in attributes into spaces.
    return escape(str(value), {'"': "&quot;", "\n": "&#10;", "\r": "&#13;", "\t": "&#9;"})


def _attrs(values: dict[str, object]) -> str:
    return "".join(f' {name}="{_attr(value)}"' for name, value in values.items())


def diagram_type(record: Record) -> str:
    """What ``create_diagram`` takes: the MDG view (``MDGDgm`` in StyleEx) when there is one, else Diagram_Type."""
    found = _MDG.search(record.values.get("attr_styleex") or "")
    return found.group(1) if found else record.values.get("attr_diagram_type") or ""


def _offset(pdata5: str | None) -> str:
    found = _OFFSET.search(pdata5 or "")
    return found.group(1) if found else ""


def _kind(element: Record) -> str:
    kind = element.values.get("attr_object_type")
    if kind == "Note":
        return "note"
    return "readonly" if kind in READONLY_TYPES else "element"


def _markup(session, diagram: Record) -> tuple[list[tuple[str, dict]], list[tuple[str | None, dict]]]:
    """``(element GUID, attributes)`` per diagram object and ``(connector GUID, attributes)`` per shown connector."""
    this = Ref("t_diagram", diagram.key)
    working = session.working
    objects: list[tuple[str, dict]] = []
    shown: set[Ref] = set()
    for row in sorted(_objects(session, this), key=lambda r: (r.values.get("attr_sequence") or 0, str(r.key))):
        element = working.resolve(row.values.get("attr_object_id"))
        if element is None:
            continue  # a dangling row: nothing eaedit can name; left as it is
        shown.add(Ref("t_object", element.key))
        values = {"data-ea-guid": guid_of(element)}
        if duid(row.values.get("attr_objectstyle")):
            values["data-ea-duid"] = duid(row.values.get("attr_objectstyle"))
        values["data-ea-rect"] = ",".join(str(v) for v in from_ea(row.values))
        values["data-ea-z"] = row.values.get("attr_sequence") or 0
        values["data-ea-kind"] = _kind(element)
        if values["data-ea-kind"] == "note":
            values["data-ea-text"] = element.values.get("attr_note") or ""
        objects.append((guid_of(element), values))
    lines: list[tuple[str | None, dict]] = []
    for link in working.records("t_diagramlinks"):
        if link.values.get("attr_diagramid") != this:
            continue
        connector = working.resolve(link.values.get("attr_connectorid"))
        if connector is None:
            continue
        ends = [connector.values.get(c) for c in ("attr_start_object_id", "attr_end_object_id")]
        # A link row whose ends are not both shown is not something the SVG can state; import leaves it alone.
        if not all(end in shown for end in ends):
            continue
        values = {"data-ea-guid": guid_of(connector), "data-ea-hidden": "1" if link.values.get("attr_hidden") else "0"}
        if connector.values.get("attr_connector_type") == "NoteLink":
            values["data-ea-kind"] = "notelink"
            values["data-ea-from"] = guid_of(working.resolve(ends[0]))
            values["data-ea-to"] = guid_of(working.resolve(ends[1]))
        lines.append((guid_of(connector), values))
    messages = [
        m
        for m in working.records("t_connector")
        if m.values.get("attr_connector_type") == "Sequence" and m.values.get("attr_diagramid") == this
    ]
    for message in sorted(messages, key=lambda m: (m.values.get("attr_seqno") or 0, str(m.key))):
        values = {
            "data-ea-guid": guid_of(message),
            "data-ea-hidden": "0",
            "data-ea-kind": "message",
            "data-ea-seq": message.values.get("attr_seqno") or 0,
            "data-ea-offset": _offset(message.values.get("attr_pdata5")),
        }
        lines.append((guid_of(message), values))
    listed = {Ref("t_connector", working.resolve(session.find(g, kinds=("connector",))).key) for g, _ in lines}
    for row in _objects(session, this):
        note = working.resolve(row.values.get("attr_object_id"))
        if note is None or note.values.get("attr_object_type") != "Note":
            continue
        pdata4 = note.values.get("attr_pdata4")
        # A note on a connector: Note PDATA4 ``idref<N>=<connector>;`` and no NoteLink (note 77 in nafv4.qea).
        for ref in pdata4.refs if isinstance(pdata4, TextRefs) else ():
            if ref in listed:
                target = guid_of(working.resolve(ref))
                lines.append((None, {"data-ea-kind": "notelink", "data-ea-from": target, "data-ea-to": guid_of(note)}))
    return objects, lines


def export_svg(session, diagram: str) -> str:
    """The diagram as the working copy will render it, with the ``data-ea-*`` markup on its shapes."""
    guid = session.find(diagram, kinds=("diagram",)).key
    return render_working(session, [guid])[guid].svg


def annotate(session, record: Record, rendered: str, ids: Ids) -> str:
    """``rendered`` (the diagram ``record`` from the working copy) with the eaedit SVG markup added."""
    objects, lines = _markup(session, record)
    by_element: dict[str, list[dict]] = {}
    for guid, values in objects:
        by_element.setdefault(guid, []).append(values)
    by_connector = {guid: values for guid, values in lines if guid is not None}
    done: set[int] = set()

    def mark(match: re.Match) -> str:
        number = int(match.group(2))
        if match.group(1) == "object":
            # An element shown twice has two shapes with one object id: those go to the data group instead.
            found = by_element.get(ids.objects.get(number), [])
            values = found[0] if len(found) == 1 else None
        else:
            values = by_connector.get(ids.connectors.get(number))
        if values is None or id(values) in done:
            return match.group(0)
        done.add(id(values))
        tag = match.group(0)
        end = len(tag) - (2 if match.group(3) else 1)
        return tag[:end] + _attrs(values) + tag[end:]

    svg = _TAG.sub(mark, rendered)
    rest = [values for _, values in objects + lines if id(values) not in done]
    if rest:
        # Objects and connectors the renderer draws without a group of their own (or not at all).
        data = '<g id="ea-data" display="none">' + "".join(f"<g{_attrs(v)}/>" for v in rest) + "</g>\n"
        at = svg.rindex("</svg>")
        svg = svg[:at] + data + svg[at:]
    root = {"data-ea-diagram": record.key, "data-ea-name": record.values.get("attr_name") or ""}
    root["data-ea-type"] = diagram_type(record)
    return re.sub(r"<svg\b", lambda _: "<svg" + _attrs(root), svg, count=1)


# --- import ---


@dataclass
class _Shape:
    label: str
    guid: str | None
    local: str | None
    duid: str | None
    rect: Rect
    z: int | None
    text: str | None
    element: Record | None = None


@dataclass
class _Line:
    label: str
    guid: str | None
    kind: str | None
    hidden: bool | None
    seq: int | None
    offset: int | None
    start: str | None
    end: str | None
    connector: Record | None = None


def _int(group: ET.Element, name: str, label: str) -> int | None:
    value = group.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        raise InvalidOperationError(f"{label}: {name} must be an integer, not {value!r}") from None


def _read(svg_text: str) -> tuple[dict[str, str], list[_Shape], list[_Line]]:
    try:
        root = ET.fromstring(svg_text.encode("utf-8"))
    except ET.ParseError as exc:
        raise InvalidOperationError(f"not an XML file: {exc}") from None
    if root.tag.rpartition("}")[2] != "svg":
        raise InvalidOperationError("the file's root element is not <svg>")
    header = {k: v for k, v in root.attrib.items() if k.startswith("data-ea-")}
    shapes: list[_Shape] = []
    lines: list[_Line] = []
    for group in root.iter():
        if group is root:
            continue
        kind, guid, local = group.get("data-ea-kind"), group.get("data-ea-guid"), group.get("data-ea-id")
        if kind is None and guid is None and local is None:
            continue
        label = f"group {guid}" if guid else f"group data-ea-id={local!r}" if local else f"a {kind!r} group"
        if kind in OBJECT_KINDS:
            if group.get("data-ea-rect") is None:
                raise InvalidOperationError(f"{label}: an object needs data-ea-rect")
            if guid is None and not (kind == "note" and local):
                raise InvalidOperationError(f"{label}: an object needs data-ea-guid (a new note: data-ea-id)")
            try:
                rect = check_rect(group.get("data-ea-rect").split(","))
            except InvalidOperationError as exc:
                raise InvalidOperationError(f"{label}: {exc}") from None
            z = _int(group, "data-ea-z", label)
            shapes.append(_Shape(label, guid, local, group.get("data-ea-duid"), rect, z, group.get("data-ea-text")))
        elif kind in LINE_KINDS or (kind is None and guid is not None):
            if guid is None and kind != "notelink":
                raise InvalidOperationError(f"{label}: a connector needs data-ea-guid")
            if guid is None and not (group.get("data-ea-from") and group.get("data-ea-to")):
                raise InvalidOperationError(f"{label}: a new note link needs data-ea-from and data-ea-to")
            hidden = group.get("data-ea-hidden")
            if hidden not in (None, "0", "1"):
                raise InvalidOperationError(f"{label}: data-ea-hidden must be 0 or 1, not {hidden!r}")
            lines.append(
                _Line(
                    label,
                    guid,
                    kind,
                    None if hidden is None else hidden == "1",
                    _int(group, "data-ea-seq", label),
                    _int(group, "data-ea-offset", label),
                    group.get("data-ea-from"),
                    group.get("data-ea-to"),
                )
            )
        else:
            raise InvalidOperationError(f"{label}: unknown data-ea-kind {kind!r}")
    return header, shapes, lines


def _resolve(session, guid: str, kinds: tuple[str, ...], label: str) -> Record:
    try:
        if not (guid.startswith("{") and guid.endswith("}")):
            raise NotFoundError(guid)
        return session.working.resolve(session.find(guid, kinds=kinds))
    except NotFoundError:
        raise InvalidOperationError(f"{label}: unknown GUID {guid}") from None


def _is_element(session, guid: str) -> bool:
    try:
        session.find(guid, kinds=("element",))
    except NotFoundError:
        return False
    return True


def _inside(rect: Rect, outer: Rect) -> bool:
    return rect[0] >= outer[0] and rect[1] >= outer[1] and rect[2] <= outer[2] and rect[3] <= outer[3]


def _validate(session, shapes: list[_Shape], lines: list[_Line]) -> None:
    """Every refusal rule, before anything is staged."""
    locals_: dict[str, _Shape] = {}
    duids: set[str] = set()
    for shape in shapes:
        if shape.guid is not None:
            shape.element = _resolve(session, shape.guid, ("element",), shape.label)
        elif shape.local in locals_:
            raise InvalidOperationError(f"{shape.label}: data-ea-id used twice")
        else:
            locals_[shape.local] = shape
        if shape.duid:
            if shape.duid.upper() in duids:
                raise InvalidOperationError(f"{shape.label}: data-ea-duid {shape.duid} used twice")
            duids.add(shape.duid.upper())
    present = {Ref("t_object", s.element.key) for s in shapes if s.element is not None}
    for line in lines:
        if line.guid is not None:
            if line.kind is None and _is_element(session, line.guid):
                raise InvalidOperationError(f"{line.label}: an object needs data-ea-kind and data-ea-rect")
            line.connector = _resolve(session, line.guid, ("connector",), line.label)
            ends = [line.connector.values.get(c) for c in ("attr_start_object_id", "attr_end_object_id")]
            if not all(end in present for end in ends):
                raise InvalidOperationError(f"{line.label}: both ends of the connector must be on the diagram")
    connectors = {guid_of(line.connector).upper() for line in lines if line.connector is not None}
    for line in lines:
        if line.guid is not None:
            continue
        notes = 0
        for end in (line.start, line.end):
            if end in locals_:
                notes += 1
                continue
            if end.upper() in connectors:
                continue
            element = _resolve(session, end, ("element", "connector"), line.label)
            if element.table == "t_connector" or Ref("t_object", element.key) not in present:
                raise InvalidOperationError(f"{line.label}: both ends of the note link must be on the diagram")
            notes += element.values.get("attr_object_type") == "Note"
        if not notes:
            raise InvalidOperationError(f"{line.label}: a note link needs a note at one end")
    for shape in shapes:
        element = shape.element
        if element is None or element.values.get("attr_object_type") != "Part":
            continue
        owners = [
            s
            for s in shapes
            if s.element is not None and Ref("t_object", s.element.key) == element.values.get("attr_parentid")
        ]
        if owners and not any(_inside(shape.rect, owner.rect) for owner in owners):
            raise InvalidOperationError(f"{shape.label}: a Part must lie inside its owner's rectangle")


class _Importer:
    """Turns the file's difference against the diagram into operations, run one by one in the session."""

    def __init__(self, session) -> None:
        self.session = session
        self.diagram = ""
        self.results: list[OpResult] = []
        self.warnings: list[EditWarning] = []
        #: Local note id -> GUID of the note made for it.
        self.notes: dict[str, str] = {}

    def run(self, op: str, /, **kwargs) -> str | None:
        result = self.session.run(op, **kwargs)
        self.results.append(result)
        return result.guid

    def warn(self, code: str, message: str, target: str | None) -> None:
        self.warnings.append(EditWarning(code, message, target))

    @property
    def this(self) -> Ref:
        return Ref("t_diagram", self.diagram)

    def header(self, header: dict[str, str], owner: str | None) -> None:
        guid, name, type = (header.get(f"data-ea-{k}") for k in ("diagram", "name", "type"))
        if guid is None:
            if not (name and type and owner):
                raise InvalidOperationError(
                    "a new diagram (no data-ea-diagram) needs data-ea-name, data-ea-type and an owner package"
                )
            self.diagram = self.run("create_diagram", owner=owner, name=name, type=type)
            return
        record = _resolve(self.session, guid, ("diagram",), "<svg>")
        self.diagram = record.key
        if name is not None and name != (record.values.get("attr_name") or ""):
            self.run("update_diagram", diagram=self.diagram, name=name)
        if type is not None and type != diagram_type(record):
            self.warn("type-kept", f"the diagram type stays {diagram_type(record)!r}; eaedit cannot change it", guid)

    def objects(self, shapes: list[_Shape]) -> None:
        working = self.session.working
        rows = sorted(_objects(self.session, self.this), key=lambda r: str(r.key))
        by_duid = {duid(r.values.get("attr_objectstyle")): r for r in rows if duid(r.values.get("attr_objectstyle"))}
        matched: dict[int, Record] = {}
        used: set = set()
        for shape in shapes:
            if shape.element is None:
                continue
            ref = Ref("t_object", shape.element.key)
            row = by_duid.get((shape.duid or "").upper())
            if row is None or row.values.get("attr_object_id") != ref or row.key in used:
                # Without a matching DUID, the first object still free that shows the element.
                row = next((r for r in rows if r.values.get("attr_object_id") == ref and r.key not in used), None)
            if row is not None:
                matched[id(shape)] = row
                used.add(row.key)
        # Removals first, so the places and moves below see the diagram as the file has it.
        for row in rows:
            if row.key in used:
                continue
            element = working.resolve(row.values.get("attr_object_id"))
            if element is None:
                continue
            label = duid(row.values.get("attr_objectstyle")) or guid_of(element)
            if _kind(element) == "readonly":
                self.warn("readonly-kept", f"read-only object {label} is not in the file; kept", guid_of(element))
            elif _kind(element) == "note" and self._only_here(element, used):
                # A note shown nowhere else goes with its last diagram object, as delete_diagram treats notes.
                self.run("delete_element", el=guid_of(element))
            else:
                self.run("remove_from_diagram", diagram=self.diagram, element=label)
        # Owners before their Parts, so each Part is checked against its owner's new rectangle.
        for parts in (False, True):
            for shape in shapes:
                if (shape.element is not None and shape.element.values.get("attr_object_type") == "Part") == parts:
                    self._object(shape, matched.get(id(shape)))

    def _only_here(self, note: Record, used: set) -> bool:
        ref = Ref("t_object", note.key)
        rows = [r for r in self.session.working.records("t_diagramobjects") if r.values.get("attr_object_id") == ref]
        return all(r.values.get("attr_diagram_id") == self.this and r.key not in used for r in rows)

    def _object(self, shape: _Shape, row: Record | None) -> None:
        if shape.element is None:
            self.notes[shape.local] = self.run(
                "add_note", diagram=self.diagram, text=shape.text or "", rect=list(shape.rect)
            )
            return
        guid = guid_of(shape.element)
        if _kind(shape.element) == "readonly":
            if row is None:
                self.warn("readonly-kept", f"{shape.label}: read-only objects cannot be placed; skipped", guid)
            elif from_ea(row.values) != shape.rect:
                self.warn("readonly-kept", f"{shape.label}: read-only object kept where it is", guid)
            return
        if row is None:
            self.run("place", diagram=self.diagram, element=guid, rect=list(shape.rect))
        elif from_ea(row.values) != shape.rect:
            target = duid(row.values.get("attr_objectstyle")) or guid
            self.run("set_bounds", diagram=self.diagram, element=target, rect=list(shape.rect))
        if row is not None and shape.z is not None and shape.z != (row.values.get("attr_sequence") or 0):
            # No operation sets Sequence yet; place still stacks new objects as on the hand-made rows.
            self.warn("z-kept", f"{shape.label}: stacking order is not imported yet; kept", guid)
        if _kind(shape.element) == "note" and shape.text is not None:
            current = self.session.working.get("t_object", shape.element.key)
            if (current.values.get("attr_note") or "") != shape.text:
                self.run("set_note_text", note=guid, text=shape.text)

    def lines(self, lines: list[_Line]) -> None:
        working = self.session.working
        for line in lines:
            if line.connector is None:
                continue
            guid = guid_of(line.connector)
            connector = working.get("t_connector", line.connector.key)
            if connector.values.get("attr_connector_type") == "Sequence":
                on_here = connector.values.get("attr_diagramid") == self.this
                seq = connector.values.get("attr_seqno") or 0
                offset = _offset(connector.values.get("attr_pdata5"))
                changed = (line.seq is not None and line.seq != seq) or (
                    line.offset is not None and str(line.offset) != offset
                )
                if not on_here or changed:
                    self.run("show_message", diagram=self.diagram, connector=guid, order=line.seq, offset=line.offset)
                continue
            link = working.get("t_diagramlinks", _link_key(self.this, connector))
            if link is None:
                self.run("show_connector", diagram=self.diagram, connector=guid)
                if line.hidden:
                    self.run("hide_connector", diagram=self.diagram, connector=guid)
            elif line.hidden is not None and bool(link.values.get("attr_hidden")) != line.hidden:
                self.run("hide_connector" if line.hidden else "show_connector", diagram=self.diagram, connector=guid)
        for line in lines:
            if line.connector is None:
                self._note_link(line)

    def _guid(self, end: str) -> str:
        return self.notes.get(end, end)

    def _note_link(self, line: _Line) -> None:
        working = self.session.working
        start, end = self._guid(line.start), self._guid(line.end)
        records = [working.resolve(self.session.find(g, kinds=("element", "connector"))) for g in (start, end)]
        # The note is the end of a NoteLink (Start = the annotated element on all hand-made ones), else the start.
        if records[1].table == "t_object" and records[1].values.get("attr_object_type") == "Note":
            note, target = records[1], records[0]
        else:
            note, target = records[0], records[1]
        if target.table == "t_connector":
            pdata4 = note.values.get("attr_pdata4")
            if isinstance(pdata4, TextRefs) and Ref("t_connector", target.key) in pdata4.refs:
                return
        else:
            ends = {Ref("t_object", note.key), Ref("t_object", target.key)}
            for connector in working.records("t_connector"):
                values = connector.values
                if (
                    values.get("attr_connector_type") == "NoteLink"
                    and {
                        values.get("attr_start_object_id"),
                        values.get("attr_end_object_id"),
                    }
                    == ends
                ):
                    return
        self.run("link_note", note=guid_of(note), target=guid_of(target))


def import_svg(session, svg_text: str, owner: str | None = None) -> list[OpResult]:
    """Stage the difference between an eaedit SVG and its diagram (a new diagram in ``owner`` without
    ``data-ea-diagram``). A file that breaks the rules is refused before anything is staged; an operation failing
    part way undoes the ones before it.
    """
    header, shapes, lines = _read(svg_text)
    _validate(session, shapes, lines)
    importer = _Importer(session)
    start = len(session.log)
    try:
        importer.header(header, owner)
        importer.objects(shapes)
        importer.lines(lines)
    except BaseException:
        while len(session.log) > start:
            session.undo()
        raise
    if importer.warnings:
        importer.results.append(OpResult(None, importer.warnings))
    return importer.results
