"""Diagram operations: create, update and delete a diagram with its objects and links."""

from __future__ import annotations

from eacore.records import Record, Ref
from eaedit.defaults import apply_fields, new_record, timestamp
from eaedit.diagrams.views import resolve_view
from eaedit.errors import InvalidOperationError
from eaedit.ops import operation
from eaedit.ops.common import primary_guid
from eaedit.ops.elements import cascade_delete
from eaedit.resolve import guid_of


def _diagram(session, identifier: str) -> Record:
    return session.working.resolve(session.find(identifier, kinds=("diagram",)))


@operation("create_diagram")
def create_diagram(session, owner: str, name: str, type: str = "Class", guid: str | None = None) -> str:
    if not name:
        raise InvalidOperationError("a diagram needs a name")
    view = resolve_view(session.catalogues, type)
    ref = session.find(owner, kinds=("package", "element"))
    parent = None
    if ref.table == "t_object":
        # A diagram of an element sits in the element's package (ParentID names the element), as EA stores it.
        parent = ref
        ref = session.working.resolve(ref).values["attr_package_id"]
    guid = primary_guid(session, guid)
    now = timestamp(session.now())
    values = {
        "attr_ea_guid": guid,
        "attr_name": name,
        "attr_diagram_type": view.diagram_type,
        "attr_package_id": ref,
        "attr_author": session.author,
        "attr_createddate": now,
        "attr_modifieddate": now,
    }
    if parent is not None:
        values["attr_parentid"] = parent
    record = new_record(session, "t_diagram", values, view.diagram_type)
    if view.mdg_name:
        # Hand-made view rows carry MDGDgm just before STBLDgm (the P2 row in nafv4.qea).
        styleex = record.values["attr_styleex"]
        record.values["attr_styleex"] = styleex.replace("STBLDgm=", f"MDGDgm={view.mdg_name};STBLDgm=", 1)
        if not view.verified:
            session.warn("unverified-default", f"view {type!r} has no EA-made sample; written from the MDG alone", guid)
    session.put(record)
    return guid


@operation("update_diagram")
def update_diagram(session, diagram: str, **fields) -> str:
    record = _diagram(session, diagram)
    if fields.get("orientation", "P") not in ("P", "L"):
        raise InvalidOperationError(
            f"orientation must be 'P' (portrait) or 'L' (landscape), not {fields['orientation']!r}"
        )
    values = apply_fields("t_diagram", record.values, fields)
    values["attr_modifieddate"] = timestamp(session.now())
    session.put(Record("t_diagram", record.key, values, record.rid))
    return guid_of(record)


@operation("delete_diagram")
def delete_diagram(session, diagram: str) -> str:
    record = _diagram(session, diagram)
    this = Ref("t_diagram", record.key)
    placed: dict = {}
    for row in session.working.records("t_diagramobjects"):
        placed.setdefault(row.values.get("attr_object_id"), set()).add(row.values.get("attr_diagram_id"))
    # A Note placed only on this diagram has no other home; EA deletes it with the diagram's content.
    notes = []
    for ref, diagrams in placed.items():
        element = session.working.resolve(ref) if isinstance(ref, Ref) else None
        if element is not None and element.values.get("attr_object_type") == "Note" and diagrams == {this}:
            notes.append(element.key)
    cascade_delete(session, notes, [record.key])
    return guid_of(record)
