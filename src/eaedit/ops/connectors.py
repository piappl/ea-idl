"""Connector operations and the catalogue's connector-end (metaconstraint) checks."""

from __future__ import annotations

import re

from eacore.catalogue import AmbiguousStereotype
from eacore.embedded import duid
from eacore.records import Key, Record, Ref
from eaedit.defaults import apply_fields, kind_for, new_record
from eaedit.errors import InvalidOperationError
from eaedit.ops import operation
from eaedit.ops.common import apply_stereotype, package_twin, primary_guid, stereotype_names
from eaedit.ops.elements import clear_references, connector_details
from eaedit.resolve import guid_of

#: Metaconstraint roles naming the stereotype required at each end; other roles are not checked.
SOURCE_ROLES = frozenset({"client", "source", "informationSource"})
TARGET_ROLES = frozenset({"supplier", "target", "informationTarget"})


def _connector(session, identifier: str) -> Record:
    return session.working.resolve(session.find(identifier, kinds=("connector",)))


def _end(session, identifier: str) -> Record:
    """The ``t_object`` row a connector end names; a package's end is its twin, as in EA."""
    record = session.working.resolve(session.find(identifier, kinds=("element", "package")))
    return package_twin(session, record) if record.table == "t_package" else record


def _resolved(session, name: str):
    try:
        return session.catalogues.resolved(name)
    except AmbiguousStereotype:
        return None  # apply_stereotype warns


def _metaclass(session, stereotype: str | None) -> str:
    """The stereotype's single relationship metaclass, else ``Association``."""
    resolved = _resolved(session, stereotype) if stereotype else None
    if resolved is None:
        return "Association"
    relationships = [m for m in resolved.applies_to if kind_for(m)[0].table == "t_connector"]
    if len(relationships) > 1:
        allowed = ", ".join(relationships)
        raise InvalidOperationError(f"{resolved.fqname} applies to {allowed}: pass type= to choose one")
    return relationships[0] if relationships else "Association"


def _lookup(session, name: str) -> str | None:
    try:
        return session.catalogues.lookup(name)
    except AmbiguousStereotype:
        return None


def _qualify(session, name: str, profile: str) -> str | None:
    """Catalogue name of ``name``; a bare name means ``profile`` first, as ``CatalogueSet.resolved`` reads it."""
    found = _lookup(session, f"{profile}::{name}") if "::" not in name else None
    return found or _lookup(session, name)


def _stereotype_closure(session, element: Record) -> set[str]:
    """Names of the element's stereotypes and every stereotype they specialise (``generalizes``)."""
    names = [fqname or name for name, fqname in stereotype_names(session, element)]
    found: set[str] = set(names)
    todo = [fq for fq in (_lookup(session, n) for n in names) if fq is not None]
    seen: set[str] = set()
    while todo:
        fq = todo.pop()
        if fq in seen:
            continue
        seen.add(fq)
        found.add(fq)
        profile = fq.rpartition("::")[0]
        for parent in session.catalogues.stereotype(fq).generalizes:
            ancestor = _qualify(session, parent, profile)
            if ancestor is not None:
                todo.append(ancestor)
    return found


def check_ends(session, connector: Record) -> None:
    """Warn ``connector-end`` for each end whose stereotypes satisfy none of the catalogue's targets for a role."""
    values = connector.values
    ends = {
        "source": session.working.resolve(values.get("attr_start_object_id")),
        "target": session.working.resolve(values.get("attr_end_object_id")),
    }
    closures: dict[str, set[str]] = {}
    for name, fqname in stereotype_names(session, connector):
        resolved = _resolved(session, fqname or name)
        if resolved is None:
            continue
        # Constraints sharing a role are alternatives: the MDG lists "A;B" as one constraint per target.
        by_role: dict[str, list[str]] = {}
        for constraint in resolved.constraints:
            by_role.setdefault(constraint.role, []).append(constraint.target)
        profile = resolved.fqname.rpartition("::")[0]
        rule_source = " ".join(p for p in (profile, resolved.source.version, "metaconstraint") if p)
        for role, targets in by_role.items():
            side = "source" if role in SOURCE_ROLES else "target" if role in TARGET_ROLES else None
            if side is None or ends[side] is None:
                continue
            if side not in closures:
                closures[side] = _stereotype_closure(session, ends[side])
            have = closures[side]
            if any(t in have or _qualify(session, t, profile) in have for t in targets):
                continue
            element = ends[side].values.get("attr_name")
            stereotypes = ", ".join(n for n, _ in stereotype_names(session, ends[side])) or "no stereotype"
            session.warn(
                "connector-end",
                f"{resolved.fqname} {role} must be {' or '.join(targets)}; {side} {element!r} has {stereotypes}",
                guid_of(connector),
                rule_source,
            )


@operation("connect")
def connect(
    session,
    source: str,
    target: str,
    type: str | None = None,
    stereotype: str | None = None,
    name: str | None = None,
    direction: str | None = None,
    guid: str | None = None,
    **fields,
) -> str:
    start, end = _end(session, source), _end(session, target)
    metaclass = type or _metaclass(session, stereotype)
    kind, known = kind_for(metaclass)
    if kind.table != "t_connector":
        raise InvalidOperationError(f"{metaclass} is not a relationship: use create_element")
    if not known or not kind.verified:
        session.warn("unverified-kind", f"{metaclass} stored as Connector_Type {kind.type_value!r} is unverified")
    if direction is None and stereotype:
        resolved = _resolved(session, stereotype)
        direction = resolved.definition.properties.get("direction") if resolved is not None else None
    guid = primary_guid(session, guid)
    values = {
        kind.type_column: kind.type_value,
        **kind.extra,
        "attr_ea_guid": guid,
        "attr_name": name,
        "attr_start_object_id": Ref("t_object", start.key),
        "attr_end_object_id": Ref("t_object", end.key),
    }
    if direction is not None:
        values["attr_direction"] = direction
    record = new_record(session, "t_connector", values, kind.type_value)
    record.values.update(apply_fields("t_connector", record.values, fields))
    session.put(record)
    if stereotype:
        apply_stereotype(session, "t_connector", record, stereotype)
        check_ends(session, session.working.get("t_connector", record.key))
    return guid


@operation("update_connector")
def update_connector(session, conn: str, **fields) -> str:
    record = _connector(session, conn)
    session.put(Record("t_connector", record.key, apply_fields("t_connector", record.values, fields), record.rid))
    return guid_of(record)


def _shown(session, diagram: Ref, element: Key) -> Record | None:
    """The first diagram object showing ``element`` on ``diagram``."""
    for obj in session.working.records("t_diagramobjects"):
        values = obj.values
        if values.get("attr_diagram_id") == diagram and values.get("attr_object_id") == Ref("t_object", element):
            return obj
    return None


@operation("reconnect")
def reconnect(session, conn: str, source: str | None = None, target: str | None = None) -> str:
    if source is None and target is None:
        raise InvalidOperationError("reconnect needs source= or target=")
    record = _connector(session, conn)
    values = dict(record.values)
    moved: dict[str, Key] = {}  # SOID/EOID -> new end element
    for given, column, style_key in ((source, "attr_start_object_id", "SOID"), (target, "attr_end_object_id", "EOID")):
        if given is not None:
            end = _end(session, given)
            values[column] = Ref("t_object", end.key)
            moved[style_key] = end.key
    session.put(Record("t_connector", record.key, values, record.rid))
    connector = Ref("t_connector", record.key)
    for link in list(session.working.records("t_diagramlinks")):
        if link.values.get("attr_connectorid") != connector:
            continue
        diagram = link.values.get("attr_diagramid")
        style = link.values.get("attr_style") or ""
        shown = {style_key: _shown(session, diagram, element) for style_key, element in moved.items()}
        if any(obj is None for obj in shown.values()):
            # EA hides a link whose end element is not on the diagram; the row would only hold a stale DUID.
            session.drop("t_diagramlinks", link.key)
            session.warn("diagram-link-dropped", "the new end is not on the diagram", guid_of(record))
            continue
        duids = {style_key: duid(obj.values.get("attr_objectstyle")) for style_key, obj in shown.items()}
        if not all(duids.values()):
            # Without a DUID the link cannot name its new end; drop it rather than keep the old end's DUID.
            session.drop("t_diagramlinks", link.key)
            session.warn("diagram-link-dropped", "the new end's diagram object has no DUID", guid_of(record))
            continue
        for style_key, new in duids.items():
            style = re.sub(rf"(?<![A-Za-z]){style_key}=[^;]*", f"{style_key}={new}", style)
        if style != (link.values.get("attr_style") or ""):
            session.put(Record("t_diagramlinks", link.key, {**link.values, "attr_style": style}, link.rid))
    check_ends(session, session.working.get("t_connector", record.key))
    return guid_of(record)


@operation("delete_connector")
def delete_connector(session, conn: str) -> str:
    record = _connector(session, conn)
    guid, ref = guid_of(record), Ref("t_connector", record.key)
    rows: dict[tuple[str, Key], Record] = {("t_connector", record.key): record}
    for detail in connector_details(session, {ref}):
        rows[(detail.table, detail.key)] = detail
    for table, column, value in (
        ("t_diagramlinks", "attr_connectorid", ref),
        # Rows owned through the connector's GUID, as cascade_delete removes them for elements.
        ("t_xref", "attr_client", guid),
        ("t_taggedvalue", "attr_elementid", guid),
        ("t_document", "attr_elementid", guid),
    ):
        for row in session.working.records(table):
            if row.values.get(column) == value:
                rows[(table, row.key)] = row
    clear_references(session, rows)
    for table, key in rows:
        session.drop(table, key)
    return guid
