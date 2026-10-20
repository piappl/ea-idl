"""Helpers shared by operations: stereotype lists (``t_xref``) and tagged values."""

from __future__ import annotations

from eacore.catalogue import UNKNOWN_PROFILE, AmbiguousStereotype, TagDef
from eacore.embedded import Stereotype, is_guid, parse_stereotypes
from eacore.integrity import STEREO_XREF_TYPES
from eacore.records import Record, Ref
from eaedit.defaults import kind_for, new_record
from eaedit.errors import InvalidOperationError, NotFoundError
from eaedit.resolve import guid_of

#: EA's tag value column holds 255 characters; longer text goes to Notes behind this marker (Inside EA).
MEMO = "<memo>"
MEMO_LIMIT = 255

_TAG_TABLES = {
    "t_object": ("t_objectproperties", "attr_object_id"),
    "t_attribute": ("t_attributetag", "attr_elementid"),
    "t_connector": ("t_connectortag", "attr_elementid"),
}


def package_twin(session, package: Record) -> Record:
    """The ``t_object`` row of a package; it carries the package's stereotype and tags."""
    for ref in session.working.by_guid(package.values.get("attr_ea_guid") or package.key):
        record = session.working.resolve(ref)
        if ref.table == "t_object" and record.values.get("attr_pdata1") == Ref("t_package", package.key):
            return record
    raise NotFoundError(f"package {package.values.get('attr_name')!r} has no t_object row")


def _owner(session, table: str, target: Record) -> Record:
    """Current working row holding stereotype and tags for ``target`` (a package's twin)."""
    if table == "t_package":
        return package_twin(session, session.working.get(table, target.key) or target)
    current = session.working.get(table, target.key)
    if current is None:
        raise NotFoundError(f"no record {table} {target.key}")
    return current


def primary_guid(session, guid: str | None) -> str:
    """The GUID for a new top-level record: ``guid`` if given (checked and logged), else a minted one."""
    if guid is None:
        return session.new_guid()
    if not is_guid(guid):
        raise InvalidOperationError(f"{guid!r} is not a GUID")
    if session.working.by_guid(guid):
        raise InvalidOperationError(f"GUID {guid} is already used")
    session.created(guid)
    return guid


def resolve_target(session, identifier: str) -> Record:
    """The record a stereotype or tag operation acts on: a package, element, attribute or connector."""
    return session.working.resolve(session.find(identifier))


def _stereotype_xref(session, owner: Record) -> Record | None:
    guid, xref_type = guid_of(owner), STEREO_XREF_TYPES[owner.table]
    for xref in session.working.records("t_xref"):
        values = xref.values
        if values.get("attr_name") == "Stereotypes" and values.get("attr_client") == guid:
            if values.get("attr_type") == xref_type:
                return xref
    return None


def stereotype_entries(session, target: Record) -> list[Stereotype]:
    """Every stereotype on ``target`` as its ``t_xref`` list holds it, primary first."""
    owner = _owner(session, target.table, target)
    xref = _stereotype_xref(session, owner)
    if xref is None:
        primary = owner.values.get("attr_stereotype")
        return [Stereotype(primary, None, None)] if primary else []
    return parse_stereotypes(xref.values.get("attr_description"))


def stereotype_names(session, target: Record) -> list[tuple[str, str | None]]:
    """``(name, fqname)`` of every stereotype on ``target``, primary first."""
    return [(s.name, s.fqname) for s in stereotype_entries(session, target)]


def stereotype_tags(session, entries: list[tuple[str, str | None]]) -> set[str]:
    """Tag names the catalogue defines for these stereotypes (``stereotype_names`` entries); unresolved ones add none."""
    names: set[str] = set()
    for name, fqname in entries:
        try:
            resolved = session.catalogues.resolved(fqname or name)
        except AmbiguousStereotype:
            continue
        if resolved is not None:
            names.update(t.name for t in resolved.tags)
    return names


def _description(entries: list[Stereotype]) -> str:
    parts = []
    for entry in entries:
        # A stereotype of no known profile is named by its t_stereotypes row, as EA does.
        qualifier = f"FQName={entry.fqname};" if entry.fqname else f"GUID={entry.guid};" if entry.guid else ""
        parts.append(f"@STEREO;Name={entry.name};{qualifier}@ENDSTEREO;")
    return "".join(parts)


def write_stereotypes(session, table: str, target: Record, entries: list[Stereotype]) -> None:
    """Make ``entries`` the stereotype list: the Stereotype column and the ``t_xref`` row agree."""
    owner = _owner(session, table, target)
    primary = entries[0].name if entries else None
    values = {**owner.values, "attr_stereotype": primary}
    if owner.table == "t_connector":
        values["attr_btm_mid_label"] = _connector_label(owner, primary)
    if values != owner.values:
        session.put(Record(owner.table, owner.key, values, owner.rid))
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
            "attr_client": guid_of(owner),
        }
        session.put(new_record(session, "t_xref", values, "Stereotypes"))
    elif xref.values.get("attr_description") != description:
        session.put(Record("t_xref", xref.key, {**xref.values, "attr_description": description}, xref.rid))


def _connector_label(connector: Record, primary: str | None) -> str | None:
    """The label EA keeps for a stereotyped connector (nafv4.qea; EA 16.1 API): ``«S»``, an Abstraction's with
    ``«abstraction»`` above it. Sequence messages get none."""
    kind = connector.values.get("attr_connector_type")
    if primary is None or kind == "Sequence":
        return None
    return ("\u00ababstraction\u00bb \n" if kind == "Abstraction" else "") + f"\u00ab{primary}\u00bb"


def _base_type(owner: Record) -> str:
    if owner.table == "t_object":
        return owner.values.get("attr_object_type") or ""
    if owner.table == "t_connector":
        return owner.values.get("attr_connector_type") or ""
    return "Attribute"


def _applies(metaclasses: list[str], base: str) -> bool:
    return not metaclasses or any(m == base or kind_for(m)[0].type_value == base for m in metaclasses)


def _values_note(tag: TagDef) -> str | None:
    # What EA writes to a new tag's Notes (EA 16.1 applying every NAFv4-Core stereotype through the API): the choices
    # of an enumeration or boolean tag, then the default of any tag. Other types' values (a RefGUID tag's
    # metaclasses) are no choices.
    note = ""
    if tag.type in ("enumeration", "boolean") and tag.values:
        note += "Values: " + ",".join(tag.values) + "\r\n"
    if tag.default:
        note += f"Default: {tag.default}\r\n"
    return note or None


def _stereotype_guid(session, name: str, base: str) -> str | None:
    """GUID of the ``t_stereotypes`` row for ``name`` applying to ``base`` (EA writes ``class``, ``Class``)."""
    for row in session.working.records("t_stereotypes"):
        values = row.values
        if values.get("attr_stereotype") == name and (values.get("attr_appliesto") or "").lower() == base.lower():
            return values.get("attr_ea_guid")
    return None


def _entry(session, owner: Record, name: str, fqname: str | None) -> Stereotype:
    """The list entry for stereotype ``name``: profile-less ones (no or the unknown profile) as EA writes them."""
    if fqname is not None and fqname.rpartition("::")[0] != UNKNOWN_PROFILE:
        return Stereotype(name, fqname, None)
    base = _base_type(owner)
    guid = _stereotype_guid(session, name, base)
    if guid is None and fqname is None:
        # A stereotype new to the model: EA 16.1 adds it to its stereotype list when first applied. Profile-less
        # ones the model already uses without such a row (nafv4.qea's 'collapse') stay as they are.
        guid = session.new_guid()
        values = {
            "attr_stereotype": name,
            "attr_appliesto": base,
            "attr_description": name,
            "attr_mfenabled": 0,
            "attr_ea_guid": guid,
        }
        session.put(Record("t_stereotypes", (name, base), values, None))
    return Stereotype(name, None, guid)


def apply_stereotype(session, table: str, target: Record, name: str) -> None:
    """Add stereotype ``name`` (bare or ``Profile::Name``) and the catalogue tags ``target`` lacks."""
    owner = _owner(session, table, target)
    resolved = None
    try:
        fqname = session.catalogues.lookup(name)
        if fqname is not None:
            resolved = session.catalogues.resolved(fqname)
    except AmbiguousStereotype as exc:
        # The name itself, or an ancestor it generalizes, names stereotypes in several profiles.
        session.warn("ambiguous-stereotype", str(exc), name)
        entry = _entry(session, owner, name.rpartition("::")[2], name if "::" in name else None)
    else:
        if fqname is None:
            session.warn("unknown-stereotype", f"{name!r} is in no catalogue", name)
            profile, _, bare = name.rpartition("::")
            entry = _entry(session, owner, bare, name if profile else None)
        else:
            entry = _entry(session, owner, fqname.rpartition("::")[2], fqname)
    if resolved is not None:
        source = resolved.source.file or resolved.source.kind
        if resolved.definition.abstract:
            session.warn("abstract-stereotype", f"{resolved.fqname} is abstract", resolved.fqname, source)
        if resolved.missing:
            session.warn(
                "missing-base",
                f"{resolved.fqname} inherits from {', '.join(resolved.missing)}, which no catalogue defines; "
                "their tags are not added",
                resolved.fqname,
                source,
            )
        base = _base_type(owner)
        if not _applies(resolved.applies_to, base):
            allowed = ", ".join(resolved.applies_to)
            session.warn(
                "wrong-base-type", f"{resolved.fqname} applies to {allowed}, not {base}", resolved.fqname, source
            )
    entries = stereotype_entries(session, target)
    if entry.name not in [e.name for e in entries]:
        write_stereotypes(session, table, target, entries + [entry])
    if resolved is not None:
        for tag in resolved.tags:
            set_tag_value(
                session, table, target, tag.name, tag.default or None, _values_note(tag), only_if_missing=True
            )


def tag_table(table: str) -> tuple[str, str]:
    """``(tag table, owner column)`` for an owner table; package tags sit on the twin's t_objectproperties."""
    if table == "t_package":
        table = "t_object"
    try:
        return _TAG_TABLES[table]
    except KeyError:
        raise InvalidOperationError(f"{table} rows have no tagged values") from None


def find_tags(session, table: str, target: Record, name: str) -> list[Record]:
    """Every tag row named ``name`` on ``target``, in the order EA lists them."""
    owner = _owner(session, table, target)
    tags, column = tag_table(owner.table)
    owner_ref = Ref(owner.table, owner.key)
    found = [
        t
        for t in session.working.records(tags)
        if t.values.get(column) == owner_ref and t.values.get("attr_property") == name
    ]
    # With duplicates EA shows the row with the lowest PropertyID; new rows have none yet and come last.
    found.sort(key=lambda t: (t.rid is None, t.rid or 0))
    return found


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
    existing = next(iter(find_tags(session, table, target, name)), None)
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
