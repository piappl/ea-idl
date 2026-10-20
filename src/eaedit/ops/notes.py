"""Notes on diagrams: create, edit the text, link to an element or connector."""

from __future__ import annotations

from collections.abc import Sequence

from eacore.records import Record, Ref, TextRefs
from eaedit.defaults import timestamp
from eaedit.errors import InvalidOperationError
from eaedit.ops import operation
from eaedit.ops.connectors import connect
from eaedit.ops.diagrams import _diagram, _link_key, _link_row, _objects, place
from eaedit.ops.elements import create_element
from eaedit.resolve import guid_of


def _note(session, identifier: str) -> Record:
    record = session.working.resolve(session.find(identifier, kinds=("element",)))
    if record.values.get("attr_object_type") != "Note":
        raise InvalidOperationError(f"{record.values.get('attr_name') or identifier!r} is not a Note")
    return record


def _shown_on(session, element: Ref) -> list[Ref]:
    """The diagrams with an object showing ``element``."""
    found: list[Ref] = []
    for obj in session.working.records("t_diagramobjects"):
        if obj.values.get("attr_object_id") == element and obj.values.get("attr_diagram_id") not in found:
            found.append(obj.values["attr_diagram_id"])
    return found


@operation("add_note")
def add_note(session, diagram: str, text: str, rect: Sequence[int] | None = None, guid: str | None = None) -> str:
    record = _diagram(session, diagram)
    package = session.working.resolve(record.values["attr_package_id"])
    # Hand-made Notes in nafv4.qea have no Name; the text is in Note.
    note = create_element(session, package=guid_of(package), name="Note", type="Note", notes=text, guid=guid)
    stored = session.working.get("t_object", note)
    session.put(Record("t_object", stored.key, {**stored.values, "attr_name": None}, stored.rid))
    place(session, guid_of(record), note, rect=rect)
    return note


@operation("set_note_text")
def set_note_text(session, note: str, text: str) -> str:
    record = _note(session, note)
    values = {**record.values, "attr_note": text, "attr_modifieddate": timestamp(session.now())}
    session.put(Record("t_object", record.key, values, record.rid))
    return guid_of(record)


def _attach_to_connector(session, note: Record, connector: Record) -> None:
    """Note PDATA4 ``idref<N>=<connector id>;``, the only trace of a note on a message in nafv4.qea."""
    ref = Ref("t_connector", connector.key)
    current = note.values.get("attr_pdata4")
    refs = current.refs if isinstance(current, TextRefs) else ()
    template = current.template if isinstance(current, TextRefs) else ""
    template += f"idref{len(refs) + 1}={{{len(refs)}}};"
    value = TextRefs(template, (*refs, ref))
    # Note 77 is the only note on a connector in nafv4.qea and the only one with NType 1 (the others have 0).
    session.put(Record("t_object", note.key, {**note.values, "attr_pdata4": value, "attr_ntype": 1}, note.rid))
    session.warn("unverified-default", "NType 1 for a note on a connector is read from a single sample", guid_of(note))


@operation("link_note")
def link_note(session, note: str, target: str) -> str:
    record = _note(session, note)
    this = Ref("t_object", record.key)
    diagrams = _shown_on(session, this)
    if not diagrams:
        raise InvalidOperationError("the note is not on a diagram")
    found = session.working.resolve(session.find(target, kinds=("element", "connector")))
    if found.table == "t_connector":
        shown = [
            d
            for d in diagrams
            if found.values.get("attr_diagramid") == d or session.working.get("t_diagramlinks", _link_key(d, found))
        ]
        if not shown:
            raise InvalidOperationError("the connector is not shown on the note's diagram")
        current = record.values.get("attr_pdata4")
        if isinstance(current, TextRefs) and Ref("t_connector", found.key) in current.refs:
            session.warn("already-linked", "the note is already linked to the connector", guid_of(record))
            return guid_of(found)
        # Hand-made note 77 on message 54 in nafv4.qea has only PDATA4 idref1=54; no NoteLink, no link row.
        _attach_to_connector(session, record, found)
        if found.values.get("attr_connector_type") != "Sequence":
            session.warn(
                "unverified-default",
                "a note on a non-message connector is written as on a message (PDATA4 only)",
                guid_of(found),
            )
        return guid_of(found)
    end = Ref("t_object", found.key)
    common = [d for d in diagrams if any(o.values.get("attr_object_id") == end for o in _objects(session, d))]
    if not common:
        raise InvalidOperationError("the element is not on the note's diagram")
    for existing in session.working.records("t_connector"):
        ends = {existing.values.get("attr_start_object_id"), existing.values.get("attr_end_object_id")}
        if existing.values.get("attr_connector_type") == "NoteLink" and ends == {end, this}:
            session.warn("already-linked", "the note is already linked to the element", guid_of(record))
            return guid_of(existing)
    # All six hand-made NoteLinks in nafv4.qea run Start = the annotated element, End = the Note.
    guid = connect(session, guid_of(found), guid_of(record), type="NoteLink")
    connector = session.working.resolve(session.find(guid, kinds=("connector",)))
    for diagram in common:
        row = _link_row(session, diagram, connector)
        if row is not None:
            session.put(row)
    return guid
