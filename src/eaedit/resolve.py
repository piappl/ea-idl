"""Identifier resolution: GUIDs and qualified names (``Root::Pkg::Element``, ``.attr`` for attributes)."""

from __future__ import annotations

from typing import Iterable

from eacore.records import Key, Record, RecordSet, Ref
from eaedit.errors import AmbiguousNameError, InvalidOperationError, NotFoundError

KINDS = {
    "package": ("t_package",),
    "element": ("t_object",),
    "attribute": ("t_attribute",),
    "connector": ("t_connector",),
    "diagram": ("t_diagram",),
}


def _name(record: Record) -> str:
    return record.values.get("attr_name") or ""


def guid_of(record: Record) -> str | None:
    """The record's GUID: its ``ea_guid``, else its key when that is a GUID key; None for other keys."""
    value = record.values.get("attr_ea_guid")
    if value is None and isinstance(record.key, str):
        value = record.key
    return value


def twin_package(record: Record) -> Key | None:
    """Key of the package whose ``t_object`` twin ``record`` is, else None."""
    if record.table == "t_object" and record.values.get("attr_object_type") == "Package":
        package = record.values.get("attr_pdata1")
        if isinstance(package, Ref) and package.table == "t_package":
            return package.key
    return None


def is_package_twin(record: Record) -> bool:
    return twin_package(record) is not None


def _package_name(rs: RecordSet, key: Key) -> str:
    names: list[str] = []
    seen: set[Key] = set()
    record = rs.get("t_package", key)
    while record is not None and record.key not in seen:
        seen.add(record.key)
        names.append(_name(record))
        parent = record.values.get("attr_parent_id")
        record = rs.resolve(parent) if isinstance(parent, Ref) else None
    return "::".join(reversed(names))


def _element_name(rs: RecordSet, record: Record) -> str:
    package_key = twin_package(record)
    if package_key is not None:
        return _package_name(rs, package_key)
    names = [_name(record)]
    seen = {record.key}
    parent = record.values.get("attr_parentid")
    while isinstance(parent, Ref):
        owner = rs.resolve(parent)
        if owner is None or owner.key in seen:
            break
        seen.add(owner.key)
        names.append(_name(owner))
        parent = owner.values.get("attr_parentid")
    package = record.values.get("attr_package_id")
    prefix = _package_name(rs, package.key) if isinstance(package, Ref) else ""
    return "::".join(([prefix] if prefix else []) + list(reversed(names)))


def qualified_name(rs: RecordSet, ref: Ref) -> str:
    record = rs.resolve(ref)
    if record is None:
        raise NotFoundError(f"no record {ref.table} {ref.key}")
    if ref.table == "t_package":
        return _package_name(rs, ref.key)
    if ref.table == "t_object":
        return _element_name(rs, record)
    if ref.table == "t_attribute":
        owner = record.values.get("attr_object_id")
        element = _element_name(rs, rs.resolve(owner)) if isinstance(owner, Ref) and rs.resolve(owner) else ""
        return f"{element}.{_name(record)}"
    if ref.table in ("t_connector", "t_diagram"):
        package = rs.owner_package(ref)
        prefix = _package_name(rs, package.key) if package else ""
        return f"{prefix}::{_name(record) or guid_of(record)}"
    raise InvalidOperationError(f"{ref.table} rows have no qualified name")


def find(
    rs: RecordSet, identifier: str, kinds: Iterable[str] = ("package", "element", "attribute", "connector")
) -> Ref:
    kinds = tuple(kinds)
    tables = {table for kind in kinds for table in KINDS[kind]}
    with_packages = "package" in kinds

    def candidates() -> list[Record]:
        found = []
        for table in sorted(tables):
            for record in rs.records(table):
                # The Package t_object twin shares its package's GUID and name; the t_package row wins.
                if with_packages and is_package_twin(record):
                    continue
                found.append(record)
        return found

    text = identifier.strip()
    if text.startswith("{") and text.endswith("}"):
        wanted = text.upper()
        matches = [Ref(r.table, r.key) for r in candidates() if (guid_of(r) or "").upper() == wanted]
    else:
        matches = [Ref(r.table, r.key) for r in candidates() if qualified_name(rs, Ref(r.table, r.key)) == text]
    if not matches:
        raise NotFoundError(f"nothing matches {identifier!r}")
    if len(matches) > 1:
        raise AmbiguousNameError(identifier, [guid_of(rs.resolve(m)) or str(m.key) for m in matches])
    return matches[0]
