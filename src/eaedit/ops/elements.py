"""Element operations, stereotype add/remove, and the cascading delete EA performs on an element."""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Iterable

from eacore.catalogue import AmbiguousStereotype
from eacore.embedded import is_guid
from eacore.records import Key, Record, Ref, TextRefs
from eacore.tablemap import EmbeddedGuidRule, GuidRefRule
from eaedit.defaults import apply_fields, kind_for, new_record, timestamp, unset_value
from eaedit.errors import InvalidOperationError, NotFoundError
from eaedit.ops import operation
from eaedit.ops.common import (
    apply_stereotype,
    find_tags,
    primary_guid,
    resolve_target,
    stereotype_names,
    stereotype_tags,
    write_stereotypes,
)


def _element(session, identifier: str) -> Record:
    record = session.working.resolve(session.find(identifier, kinds=("element",)))
    if record.values.get("attr_object_type") == "Package":
        raise InvalidOperationError(f"{identifier!r} is a package: use the *_package operations")
    return record


def _guid(record: Record) -> str:
    return record.values.get("attr_ea_guid") or record.key


def _base_type(session, stereotype: str | None) -> str:
    """``Class``, or the single metaclass the stereotype applies to."""
    if not stereotype:
        return "Class"
    try:
        resolved = session.catalogues.resolved(stereotype)
    except AmbiguousStereotype:
        return "Class"  # apply_stereotype warns
    if resolved is None or not resolved.applies_to:
        return "Class"
    if len(resolved.applies_to) > 1:
        allowed = ", ".join(resolved.applies_to)
        raise InvalidOperationError(f"{resolved.fqname} applies to {allowed}: pass type= to choose one")
    return resolved.applies_to[0]


@operation("create_element")
def create_element(
    session,
    package: str | None = None,
    name: str = "",
    stereotype: str | None = None,
    type: str | None = None,
    parent: str | None = None,
    notes: str | None = None,
    guid: str | None = None,
    **fields,
) -> str:
    if not name:
        raise InvalidOperationError("an element needs a name")
    package_ref = session.find(package, kinds=("package",)) if package is not None else None
    parent_ref = None
    if parent is not None:
        owner = _element(session, parent)
        parent_ref = Ref("t_object", owner.key)
        if package_ref is not None and package_ref != owner.values.get("attr_package_id"):
            raise InvalidOperationError(f"{parent!r} is not in package {package!r}")
        package_ref = owner.values.get("attr_package_id")
    if package_ref is None:
        raise InvalidOperationError("create_element needs package= or parent=")
    metaclass = type or _base_type(session, stereotype)
    kind, known = kind_for(metaclass)
    if kind.table != "t_object":
        raise InvalidOperationError(f"{metaclass} is a relationship: use connect")
    if not known or not kind.verified:
        session.warn("unverified-kind", f"{metaclass} stored as Object_Type {kind.type_value!r} is unverified", name)
    guid = primary_guid(session, guid)
    now = timestamp(session.now())
    values = {
        kind.type_column: kind.type_value,
        **kind.extra,
        "attr_ea_guid": guid,
        "attr_name": name,
        "attr_package_id": package_ref,
        "attr_note": notes,
        "attr_author": session.author,
        "attr_createddate": now,
        "attr_modifieddate": now,
    }
    if parent_ref is not None:
        values["attr_parentid"] = parent_ref
    record = new_record(session, "t_object", values, kind.type_value)
    record.values.update(apply_fields("t_object", record.values, fields))
    session.put(record)
    if stereotype:
        apply_stereotype(session, "t_object", record, stereotype)
    return guid


@operation("update_element")
def update_element(session, el: str, **fields) -> str:
    record = _element(session, el)
    values = apply_fields("t_object", record.values, fields)
    values["attr_modifieddate"] = timestamp(session.now())
    session.put(Record("t_object", record.key, values, record.rid))
    return _guid(record)


def _descendants(session, keys: Iterable[Key]) -> list[Key]:
    """``keys`` plus every element nested under them through ParentID, in breadth-first order."""
    children: dict[Key, list[Key]] = {}
    for obj in session.working.records("t_object"):
        parent = obj.values.get("attr_parentid")
        if isinstance(parent, Ref):
            children.setdefault(parent.key, []).append(obj.key)
    result: list[Key] = []
    seen: set[Key] = set()
    todo = deque(keys)
    while todo:
        key = todo.popleft()
        if key in seen:
            continue
        seen.add(key)
        result.append(key)
        todo.extend(children.get(key, []))
    return result


@operation("move_element")
def move_element(session, el: str, package: str) -> str:
    record = _element(session, el)
    package_ref = session.find(package, kinds=("package",))
    now = timestamp(session.now())
    for key in _descendants(session, [record.key]):
        current = session.working.get("t_object", key)
        values = {**current.values, "attr_package_id": package_ref}
        if key == record.key:
            values["attr_modifieddate"] = now
        session.put(Record("t_object", key, values, current.rid))
    return _guid(record)


def _where(session, table: str, columns: tuple[str, ...], targets: set) -> list[Record]:
    return [r for r in session.working.records(table) if any(r.values.get(c) in targets for c in columns)]


def cascade_delete(session, elements: Iterable[Key], diagrams: Iterable[Key] = ()) -> None:
    """Delete elements and diagrams with everything EA deletes alongside them, each row once."""
    element_keys = _descendants(session, elements)
    element_refs = {Ref("t_object", k) for k in element_keys}
    rows: dict[tuple[str, Key], Record] = {}

    def add(records: Iterable[Record]) -> set[Ref]:
        refs = set()
        for record in records:
            rows.setdefault((record.table, record.key), record)
            refs.add(Ref(record.table, record.key))
        return refs

    add(session.working.get("t_object", k) for k in element_keys)
    attributes = add(_where(session, "t_attribute", ("attr_object_id",), element_refs))
    add(_where(session, "t_attributetag", ("attr_elementid",), attributes))
    operations = add(_where(session, "t_operation", ("attr_object_id",), element_refs))
    add(_where(session, "t_operationparams", ("attr_operationid",), operations))
    add(_where(session, "t_operationtag", ("attr_elementid",), operations))
    add(_where(session, "t_objectproperties", ("attr_object_id",), element_refs))
    add(_where(session, "t_objectconstraint", ("attr_object_id",), element_refs))
    connectors = add(_where(session, "t_connector", ("attr_start_object_id", "attr_end_object_id"), element_refs))
    add(_where(session, "t_connectortag", ("attr_elementid",), connectors))
    # Diagrams owned by a deleted element (ParentID) go with it, like those of a deleted package.
    diagram_refs = {Ref("t_diagram", k) for k in diagrams}
    diagram_refs |= add(_where(session, "t_diagram", ("attr_parentid",), element_refs))
    add(session.working.resolve(d) for d in diagram_refs)
    add(_where(session, "t_diagramobjects", ("attr_object_id",), element_refs))
    add(_where(session, "t_diagramobjects", ("attr_diagram_id",), diagram_refs))
    add(_where(session, "t_diagramlinks", ("attr_connectorid",), connectors))
    add(_where(session, "t_diagramlinks", ("attr_diagramid",), diagram_refs))
    guids = {r.values.get("attr_ea_guid") for r in rows.values()} - {None}
    # Rows owned by a deleted record through its GUID: stereotype lists and properties (t_xref), tags, documents.
    add(_where(session, "t_xref", ("attr_client",), guids))
    add(_where(session, "t_taggedvalue", ("attr_elementid",), guids))
    add(_where(session, "t_document", ("attr_elementid",), guids))
    clear_references(session, rows)
    for table, key in rows:
        session.drop(table, key)


def cascade_delete_element(session, ref: Ref) -> None:
    """Delete element ``ref`` with what EA deletes alongside it, clearing references to them from other rows."""
    cascade_delete(session, [ref.key])


def _strip_text_refs(value: TextRefs, gone: set[Ref], unset: Any) -> TextRefs | Any:
    """``value`` without its ``key=ID;`` entries naming ``gone`` rows; ``unset`` when no reference is left."""
    marks = [f"\x00{i}\x00" for i in range(len(value.refs))]
    text = value.template.format(*marks)
    kept = []
    for mark, ref in zip(marks, value.refs):
        if ref in gone:
            text = re.sub(r"[^;=\x00]*=" + re.escape(mark) + ";?", "", text)
        else:
            kept.append(mark)
    if not kept:
        return text if text.strip() else unset
    text = text.replace("{", "{{").replace("}", "}}")
    for index, mark in enumerate(kept):
        text = text.replace(mark, f"{{{index}}}")
    return TextRefs(text, tuple(ref for mark, ref in zip(marks, value.refs) if mark in kept))


def clear_references(session, rows: dict[tuple[str, Key], Record]) -> None:
    """Reset references from surviving rows into ``rows`` to EA's "nothing" value, keeping names held as text.

    Covers ID references (``Ref``/``TextRefs``), GUID columns and GUIDs embedded in text, per the table map.
    """
    gone = {Ref(table, key) for table, key in rows}
    guids = {g.upper() for g in (r.values.get("attr_ea_guid") for r in rows.values()) if g}
    tablemap = session.working.tablemap
    for table in session.working.tables():
        if not tablemap.is_mapped(table):
            continue
        rules = tablemap.spec(table).rules
        for record in session.working.records(table):
            if (table, record.key) in rows:
                continue
            values = record.values
            changed: dict[str, Any] = {}
            unverified = False

            def unset(column: str) -> Any:
                nonlocal unverified
                value, verified = unset_value(table, column, values)
                unverified = unverified or not verified
                return value

            for column, value in values.items():
                if isinstance(value, Ref) and value in gone:
                    changed[column] = unset(column)
                elif isinstance(value, TextRefs) and gone.intersection(value.refs):
                    changed[column] = _strip_text_refs(value, gone, unset(column))
            for rule in rules:
                value = values.get(rule.column)
                if isinstance(rule, GuidRefRule):
                    if rule.when is not None and not rule.when(values):
                        continue
                    if is_guid(value) and value.upper() in guids:
                        changed[rule.column] = unset(rule.column)
                elif isinstance(rule, EmbeddedGuidRule) and isinstance(value, str):
                    current = changed.get(rule.column, value)
                    # EA writes a side letter after LFSP/LFEP GUIDs (``LFSP={GUID}L;``).
                    tail = "[LR]?;?" if rule.column == "attr_styleex" else ";?"
                    text = re.sub(
                        rule.pattern + tail, lambda m: "" if m.group(1).upper() in guids else m.group(0), current
                    )
                    if text != current:
                        changed[rule.column] = text or None
            if not changed:
                continue
            session.put(Record(table, record.key, {**values, **changed}, record.rid))
            columns = ", ".join(sorted(changed))
            session.warn("reference-cleared", f"{table} {columns}: referenced a deleted record", _guid(record))
            if unverified:
                session.warn("unverified-default", f"{table} {columns}: EA's unset value is unverified", _guid(record))


@operation("delete_element")
def delete_element(session, el: str) -> str:
    record = _element(session, el)
    cascade_delete_element(session, Ref("t_object", record.key))
    return _guid(record)


@operation("add_stereotype")
def add_stereotype(session, target: str, name: str) -> str:
    record = resolve_target(session, target)
    apply_stereotype(session, record.table, record, name)
    return _guid(record)


def _resolved(session, name: str):
    try:
        return session.catalogues.resolved(name)
    except AmbiguousStereotype:
        return None


@operation("remove_stereotype")
def remove_stereotype(session, target: str, name: str) -> str:
    record = resolve_target(session, target)
    entries = stereotype_names(session, record)
    matches = [e for e in entries if name in (e[0], e[1])]
    if not matches:
        raise NotFoundError(f"{target!r} has no stereotype {name!r}")
    removed = matches[0]
    write_stereotypes(session, record.table, record, [e for e in entries if e != removed])
    resolved = _resolved(session, removed[1] or removed[0])
    if resolved is not None:
        # Tags a remaining stereotype also defines still belong to the element.
        others = stereotype_tags(session, [e for e in entries if e != removed])
        kept = [
            t.name for t in resolved.tags if t.name not in others and find_tags(session, record.table, record, t.name)
        ]
        if kept:
            session.warn(
                "stereotype-removed-tags-kept",
                f"{resolved.fqname} removed; its tags {', '.join(kept)} remain",
                _guid(record),
            )
    return _guid(record)
