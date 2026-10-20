"""Attribute operations and classifier (typing) assignment."""

from __future__ import annotations

from eacore.records import Record, Ref
from eaedit.defaults import apply_fields, new_record, unset_value
from eaedit.errors import InvalidOperationError, NotFoundError
from eaedit.ops import operation
from eaedit.ops.common import apply_stereotype, primary_guid
from eaedit.ops.elements import attribute_details, clear_references
from eaedit.resolve import guid_of

#: Element types EA lets you classify; any other t_object type is accepted with a warning.
_CLASSIFIABLE = ("Part", "Object", "Port")


def _attribute(session, identifier: str) -> Record:
    return session.working.resolve(session.find(identifier, kinds=("attribute",)))


def _classifier_element(session, identifier: str) -> Record | None:
    """The element ``identifier`` names, or None (EA types an attribute by plain text when no element matches)."""
    try:
        record = session.working.resolve(session.find(identifier, kinds=("element",)))
    except NotFoundError:
        return None
    return None if record.values.get("attr_object_type") == "Package" else record


def _typing(session, type_name: str | None) -> dict:
    """Type and Classifier column values for typing an attribute by an element identifier or a primitive name."""
    nothing = unset_value("t_attribute", "attr_classifier", {})[0]
    if type_name is None:
        return {"attr_type": None, "attr_classifier": nothing}
    element = _classifier_element(session, type_name)
    if element is None:
        return {"attr_type": type_name, "attr_classifier": nothing}
    return {"attr_type": element.values.get("attr_name"), "attr_classifier": Ref("t_object", element.key)}


@operation("add_attribute")
def add_attribute(
    session,
    el: str,
    name: str = "",
    type: str | None = None,
    lower: str = "1",
    upper: str = "1",
    default: str | None = None,
    stereotype: str | None = None,
    notes: str | None = None,
    guid: str | None = None,
) -> str:
    if not name:
        raise InvalidOperationError("an attribute needs a name")
    owner = session.working.resolve(session.find(el, kinds=("element",)))
    if owner.values.get("attr_object_type") == "Package":
        raise InvalidOperationError(f"{el!r} is a package, not an element")
    owner_ref = Ref("t_object", owner.key)
    siblings = [
        r.values.get("attr_pos") or 0
        for r in session.working.records("t_attribute")
        if r.values.get("attr_object_id") == owner_ref
    ]
    guid = primary_guid(session, guid)
    values = {
        "attr_ea_guid": guid,
        "attr_object_id": owner_ref,
        "attr_name": name,
        "attr_pos": max(siblings) + 1 if siblings else 0,
        "attr_lowerbound": lower,
        "attr_upperbound": upper,
        "attr_default": default,
        "attr_notes": notes,
        **_typing(session, type),
    }
    record = new_record(session, "t_attribute", values)
    session.put(record)
    if stereotype:
        apply_stereotype(session, "t_attribute", record, stereotype)
    return guid


@operation("update_attribute")
def update_attribute(session, attr: str, **fields) -> str:
    record = _attribute(session, attr)
    # Typing keeps the classifier and the type text in step, so it goes through the same path as add_attribute.
    typing = _typing(session, fields.pop("type")) if "type" in fields else {}
    values = {**apply_fields("t_attribute", record.values, fields), **typing}
    session.put(Record("t_attribute", record.key, values, record.rid))
    return guid_of(record)


@operation("move_attribute")
def move_attribute(session, attr: str, position: int) -> str:
    record = _attribute(session, attr)
    owner = record.values.get("attr_object_id")
    group = [r for r in session.working.records("t_attribute") if r.values.get("attr_object_id") == owner]
    group.sort(key=lambda r: (r.values.get("attr_pos") or 0, r.rid is None, r.rid or 0))
    group.remove(next(r for r in group if r.key == record.key))
    group.insert(max(0, min(position, len(group))), record)
    for index, member in enumerate(group):
        if member.values.get("attr_pos") != index:
            current = session.working.get("t_attribute", member.key)
            session.put(Record("t_attribute", member.key, {**current.values, "attr_pos": index}, current.rid))
    return guid_of(record)


@operation("delete_attribute")
def delete_attribute(session, attr: str) -> str:
    record = _attribute(session, attr)
    guid = guid_of(record)
    ref = Ref("t_attribute", record.key)
    rows = {("t_attribute", record.key): record}
    for detail in attribute_details(session, {ref}):
        rows[(detail.table, detail.key)] = detail
    for xref in session.working.records("t_xref"):
        if (xref.values.get("attr_client") or "").upper() == guid.upper():
            rows[(xref.table, xref.key)] = xref
    clear_references(session, rows)
    for table, key in rows:
        session.drop(table, key)
    return guid


@operation("set_classifier")
def set_classifier(session, target: str, classifier: str | None) -> str:
    record = session.working.resolve(session.find(target, kinds=("element", "attribute")))
    if record.table == "t_attribute":
        current = record.values.get("attr_type")
        typing = _typing(session, classifier)
        if classifier is None:
            # Clearing detaches the element but keeps the type name, as EA keeps it as text.
            typing["attr_type"] = current
        session.put(Record("t_attribute", record.key, {**record.values, **typing}, record.rid))
        return guid_of(record)
    kind = record.values.get("attr_object_type")
    if kind == "Package":
        raise InvalidOperationError(f"{target!r} is a package: it has no classifier")
    if kind not in _CLASSIFIABLE:
        session.warn("unverified-kind", f"classifier of a {kind} element is unverified", guid_of(record))
    if classifier is None:
        value = unset_value("t_object", "attr_classifier", record.values)[0]
        classifier_guid = None
    else:
        element = _classifier_element(session, classifier)
        if element is None:
            raise NotFoundError(f"nothing matches {classifier!r}")
        value = Ref("t_object", element.key)
        # EA 16.1 (API) writes the classifier's GUID next to its ID when typing a Part.
        classifier_guid = guid_of(element)
    values = {**record.values, "attr_classifier": value, "attr_classifier_guid": classifier_guid}
    session.put(Record("t_object", record.key, values, record.rid))
    return guid_of(record)
