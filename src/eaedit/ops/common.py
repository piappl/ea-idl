"""Helpers shared by operations: stereotype lists (``t_xref``) and tagged values."""

from __future__ import annotations

from eacore.catalogue import AmbiguousStereotype
from eacore.embedded import parse_stereotypes
from eacore.integrity import STEREO_XREF_TYPES
from eacore.records import Record, Ref
from eaedit.defaults import kind_for, new_record
from eaedit.errors import InvalidOperationError, NotFoundError

#: EA's tag value column holds 255 characters; longer text goes to Notes behind this marker (Inside EA).
MEMO = "<memo>"
MEMO_LIMIT = 255

_TAG_TABLES = {
    "t_object": ("t_objectproperties", "attr_object_id"),
    "t_attribute": ("t_attributetag", "attr_elementid"),
    "t_connector": ("t_connectortag", "attr_elementid"),
}


def _twin(session, package: Record) -> Record:
    """The ``t_object`` row of a package; it carries the package's stereotype and tags."""
    for ref in session.working.by_guid(package.values.get("attr_ea_guid") or package.key):
        record = session.working.resolve(ref)
        if ref.table == "t_object" and record.values.get("attr_pdata1") == Ref("t_package", package.key):
            return record
    raise NotFoundError(f"package {package.values.get('attr_name')!r} has no t_object row")


def _owner(session, table: str, target: Record) -> Record:
    """Current working row holding stereotype and tags for ``target`` (a package's twin)."""
    if table == "t_package":
        return _twin(session, session.working.get(table, target.key) or target)
    current = session.working.get(table, target.key)
    if current is None:
        raise NotFoundError(f"no record {table} {target.key}")
    return current


def _guid(record: Record) -> str:
    return record.values.get("attr_ea_guid") or record.key


def _stereotype_xref(session, owner: Record) -> Record | None:
    guid, xref_type = _guid(owner), STEREO_XREF_TYPES[owner.table]
    for xref in session.working.records("t_xref"):
        values = xref.values
        if values.get("attr_name") == "Stereotypes" and values.get("attr_client") == guid:
            if values.get("attr_type") == xref_type:
                return xref
    return None


def stereotype_names(session, target: Record) -> list[tuple[str, str | None]]:
    """``(name, fqname)`` of every stereotype on ``target``, primary first."""
    owner = _owner(session, target.table, target)
    xref = _stereotype_xref(session, owner)
    if xref is None:
        primary = owner.values.get("attr_stereotype")
        return [(primary, None)] if primary else []
    return [(s.name, s.fqname) for s in parse_stereotypes(xref.values.get("attr_description"))]


def _description(entries: list[tuple[str, str | None]]) -> str:
    parts = []
    for name, fqname in entries:
        fq = f"FQName={fqname};" if fqname else ""
        parts.append(f"@STEREO;Name={name};{fq}@ENDSTEREO;")
    return "".join(parts)


def write_stereotypes(session, table: str, target: Record, entries: list[tuple[str, str | None]]) -> None:
    """Make ``entries`` the stereotype list: the Stereotype column and the ``t_xref`` row agree."""
    owner = _owner(session, table, target)
    primary = entries[0][0] if entries else None
    if owner.values.get("attr_stereotype") != primary:
        session.put(Record(owner.table, owner.key, {**owner.values, "attr_stereotype": primary}, owner.rid))
    xref = _stereotype_xref(session, owner)
    if not entries:
        if xref is not None:
            session.drop("t_xref", xref.key)
        return
    description = _description(entries)
    if xref is None:
        values = {
            "attr_name": "Stereotypes",
            "attr_type": STEREO_XREF_TYPES[owner.table],
            "attr_description": description,
            "attr_client": _guid(owner),
        }
        session.put(new_record(session, "t_xref", values, "Stereotypes"))
    elif xref.values.get("attr_description") != description:
        session.put(Record("t_xref", xref.key, {**xref.values, "attr_description": description}, xref.rid))


def _base_type(owner: Record) -> str:
    if owner.table == "t_object":
        return owner.values.get("attr_object_type") or ""
    if owner.table == "t_connector":
        return owner.values.get("attr_connector_type") or ""
    return "Attribute"


def _applies(metaclasses: list[str], base: str) -> bool:
    return not metaclasses or any(m == base or kind_for(m)[0].type_value == base for m in metaclasses)


def _values_note(values: list[str]) -> str | None:
    # EA-made tags of enumeration type keep the choices like this (EA-made enumeration tags in nafv4.qea).
    return "Values: " + ",".join(values) + "\r\n" if values else None


def apply_stereotype(session, table: str, target: Record, name: str) -> None:
    """Add stereotype ``name`` (bare or ``Profile::Name``) and the catalogue tags ``target`` lacks."""
    resolved = None
    try:
        fqname = session.catalogues.lookup(name)
    except AmbiguousStereotype as exc:
        session.warn("ambiguous-stereotype", str(exc), name)
        entry = (name, None)
    else:
        if fqname is None:
            session.warn("unknown-stereotype", f"{name!r} is in no catalogue", name)
            profile, _, bare = name.rpartition("::")
            entry = (bare, name if profile else None)
        else:
            resolved = session.catalogues.resolved(fqname)
            entry = (fqname.rpartition("::")[2], fqname)
    owner = _owner(session, table, target)
    if resolved is not None:
        source = resolved.source.file or resolved.source.kind
        if resolved.definition.abstract:
            session.warn("abstract-stereotype", f"{resolved.fqname} is abstract", resolved.fqname, source)
        base = _base_type(owner)
        if not _applies(resolved.applies_to, base):
            allowed = ", ".join(resolved.applies_to)
            session.warn(
                "wrong-base-type", f"{resolved.fqname} applies to {allowed}, not {base}", resolved.fqname, source
            )
    entries = stereotype_names(session, target)
    if entry[0] not in [n for n, _ in entries]:
        write_stereotypes(session, table, target, entries + [entry])
    if resolved is not None:
        for tag in resolved.tags:
            set_tag_value(
                session, table, target, tag.name, tag.default or None, _values_note(tag.values), only_if_missing=True
            )


def tag_table(table: str) -> tuple[str, str]:
    """``(tag table, owner column)`` for an owner table; package tags sit on the twin's t_objectproperties."""
    if table == "t_package":
        table = "t_object"
    try:
        return _TAG_TABLES[table]
    except KeyError:
        raise InvalidOperationError(f"{table} rows have no tagged values") from None


def _find_tag(session, tags: str, column: str, owner: Ref, name: str) -> Record | None:
    found = [
        t
        for t in session.working.records(tags)
        if t.values.get(column) == owner and t.values.get("attr_property") == name
    ]
    # With duplicates EA shows the row with the lowest PropertyID; new rows have none yet and come last.
    found.sort(key=lambda t: (t.rid is None, t.rid or 0))
    return found[0] if found else None


def set_tag_value(
    session,
    table: str,
    target: Record,
    name: str,
    value: str | None,
    notes: str | None = None,
    only_if_missing: bool = False,
) -> Record:
    """Set tagged value ``name`` on ``target``, creating the tag row if needed; returns the tag row."""
    owner = _owner(session, table, target)
    tags, column = tag_table(owner.table)
    owner_ref = Ref(owner.table, owner.key)
    existing = _find_tag(session, tags, column, owner_ref, name)
    if existing is not None and only_if_missing:
        return existing
    if value is not None and len(value) > MEMO_LIMIT:
        if notes is not None:
            raise InvalidOperationError(f"tag {name!r}: a value over {MEMO_LIMIT} characters is kept in notes")
        # nafv4.qea holds no memo tag, so the rule (from Inside EA and the 255-character column) is unverified.
        session.warn("unverified-default", f"tag {name!r}: value over {MEMO_LIMIT} characters stored as {MEMO}")
        value, notes = MEMO, value
    if existing is None:
        values = {column: owner_ref, "attr_property": name, "attr_value": value, "attr_notes": notes}
        record = new_record(session, tags, values)
    else:
        changes = {"attr_value": value} | ({"attr_notes": notes} if notes is not None else {})
        record = Record(tags, existing.key, {**existing.values, **changes}, existing.rid)
    session.put(record)
    return record
