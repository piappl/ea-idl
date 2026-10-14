"""Read-only queries over a session's working copy. Not operations: nothing is changed or logged."""

from __future__ import annotations

from typing import Any

from eacore.records import Key, Record, Ref, key_str
from eaedit.defaults import FIELDS
from eaedit.errors import EaeditError, NotFoundError
from eaedit.ops.common import package_twin, stereotype_names, tag_table
from eaedit.resolve import qualified_name
from eaedit.scope import Scope

KIND = {"t_package": "package", "t_object": "element", "t_attribute": "attribute", "t_connector": "connector"}
#: Column holding each kind's own type (an attribute's type is its FIELDS "type").
TYPE_COLUMN = {"t_object": "attr_object_type", "t_connector": "attr_connector_type", "t_attribute": "attr_type"}


def _guid(record: Record) -> str:
    return record.values.get("attr_ea_guid") or record.key


def _is_twin(record: Record) -> bool:
    return record.values.get("attr_object_type") == "Package" and isinstance(record.values.get("attr_pdata1"), Ref)


def _plain(session, value: Any) -> Any:
    """A column value fit for YAML or JSON: references become qualified names where they have one."""
    if not isinstance(value, Ref):
        return value
    try:
        return qualified_name(session.working, value)
    except EaeditError:
        return key_str(value.key)


def _subject(session, record: Record) -> Record:
    """The row the caller means: a package's ``t_object`` twin reads as the package."""
    if record.table == "t_object" and _is_twin(record):
        package = session.working.resolve(record.values["attr_pdata1"])
        if package is not None:
            return package
    return record


def _summary(session, record: Record) -> dict:
    record = _subject(session, record)
    holder = package_twin(session, record) if record.table == "t_package" else record
    column = TYPE_COLUMN.get(record.table)
    return {
        "kind": KIND[record.table],
        "guid": _guid(record),
        "name": record.values.get("attr_name"),
        "qualified_name": qualified_name(session.working, Ref(record.table, record.key)),
        "type": record.values.get(column) if column else "Package",
        "stereotype": holder.values.get("attr_stereotype"),
    }


def _tags(session, record: Record) -> dict[str, Any]:
    owner = package_twin(session, record) if record.table == "t_package" else record
    table, column = tag_table(owner.table)
    ref = Ref(owner.table, owner.key)
    rows = [t for t in session.working.records(table) if t.values.get(column) == ref]
    # As EA shows duplicates: the lowest PropertyID first, new rows last; the first of a name wins.
    rows.sort(key=lambda t: (t.rid is None, t.rid or 0))
    tags: dict[str, Any] = {}
    for row in rows:
        tags.setdefault(row.values.get("attr_property"), row.values.get("attr_value"))
    return tags


def get(session, identifier: str) -> dict:
    record = session.working.resolve(session.find(identifier))
    result = _summary(session, record)
    del result["stereotype"]
    if record.table == "t_package":
        # element properties of a package live on its twin; the package row's own columns win
        twin = package_twin(session, record)
        sources = [(FIELDS["t_object"], twin), (FIELDS["t_package"], record)]
    else:
        sources = [(FIELDS.get(record.table, {}), record)]
    for fields, row in sources:
        for name, column in fields.items():
            result[name] = _plain(session, row.values.get(column))
    if record.table == "t_connector":
        for end, column in (("source", "attr_start_object_id"), ("target", "attr_end_object_id")):
            result[end] = _plain(session, record.values.get(column))
    elif record.table == "t_attribute":
        result["owner"] = _plain(session, record.values.get("attr_object_id"))
        result["classifier"] = _plain(session, record.values.get("attr_classifier"))
    result["stereotypes"] = [fq or name for name, fq in stereotype_names(session, record)]
    result["tags"] = _tags(session, record)
    return result


def _roots(session, package: str | None) -> list[Ref]:
    """The package given, else the focus, else every root package."""
    if package is not None:
        return [session.find(package, kinds=("package",))]
    if session.scope.focus:
        return list(session.scope.focus)
    return [Ref("t_package", p.key) for p in session.working.records("t_package") if not _parent(p)]


def _parent(package: Record) -> Key | None:
    parent = package.values.get("attr_parent_id")
    return parent.key if isinstance(parent, Ref) else None


def _packages(session, roots: list[Ref]) -> set[Key]:
    return Scope(roots, "off").focus_packages(session.working)


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row["qualified_name"], row["guid"]))


def list_(session, package: str | None = None, recursive: bool = True) -> list[dict]:
    """Packages and elements below ``package`` (default: the focus), the starting packages excluded."""
    roots = _roots(session, package)
    starts = {ref.key for ref in roots}
    if recursive:
        packages = _packages(session, roots)
        holders = packages
    else:
        packages = {p.key for p in session.working.records("t_package") if _parent(p) in starts}
        holders = starts
    rows = [_summary(session, session.working.get("t_package", key)) for key in packages - starts]
    for obj in session.working.records("t_object"):
        package_ref = obj.values.get("attr_package_id")
        if not _is_twin(obj) and isinstance(package_ref, Ref) and package_ref.key in holders:
            rows.append(_summary(session, obj))
    return _sorted(rows)


def tree(session, package: str | None = None) -> str:
    """An indented outline: each starting package, then its packages and elements, nested elements under owners."""
    working = session.working
    sub: dict[Key, list[Record]] = {}
    for pkg in working.records("t_package"):
        sub.setdefault(_parent(pkg), []).append(pkg)
    in_package: dict[Key, list[Record]] = {}
    in_element: dict[Key, list[Record]] = {}
    for obj in working.records("t_object"):
        if _is_twin(obj):
            continue
        parent, package_ref = obj.values.get("attr_parentid"), obj.values.get("attr_package_id")
        if isinstance(parent, Ref):
            in_element.setdefault(parent.key, []).append(obj)
        elif isinstance(package_ref, Ref):
            in_package.setdefault(package_ref.key, []).append(obj)

    def label(record: Record) -> str:
        holder = package_twin(session, record) if record.table == "t_package" else record
        kind = "Package" if record.table == "t_package" else record.values.get("attr_object_type")
        stereotype = holder.values.get("attr_stereotype")
        return f"{record.values.get('attr_name') or ''} [{kind}]" + (f" «{stereotype}»" if stereotype else "")

    def by_name(records: list[Record]) -> list[Record]:
        return sorted(records, key=lambda r: (r.values.get("attr_name") or "", key_str(r.key)))

    lines: list[str] = []

    def element(obj: Record, depth: int) -> None:
        lines.append("  " * depth + label(obj))
        for child in by_name(in_element.get(obj.key, [])):
            element(child, depth + 1)

    def package_(pkg: Record, depth: int) -> None:
        for child in by_name(sub.get(pkg.key, [])):
            lines.append("  " * depth + label(child))
            package_(child, depth + 1)
        for obj in by_name(in_package.get(pkg.key, [])):
            element(obj, depth)

    for root in _roots(session, package):
        record = working.resolve(root)
        if record is None:
            raise NotFoundError(f"package {key_str(root.key)} is not in the model (deleted?)")
        lines.append(qualified_name(working, root))
        package_(record, 1)
    return "\n".join(lines)


def _has_stereotype(session, record: Record, stereotype: str) -> bool:
    return any(stereotype in (name, fq) for name, fq in stereotype_names(session, _subject(session, record)))


def search(session, text: str, stereotype: str | None = None, type: str | None = None) -> list[dict]:
    """Elements and packages in the focus whose name, alias or notes contain ``text``, ignoring case."""
    needle = text.casefold()
    packages = _packages(session, _roots(session, None))
    rows = []
    for obj in session.working.records("t_object"):
        package_ref = obj.values.get("attr_package_id")
        if not isinstance(package_ref, Ref) or package_ref.key not in packages:
            continue
        if type is not None and obj.values.get("attr_object_type") != type:
            continue
        haystack = [obj.values.get(c) for c in ("attr_name", "attr_alias", "attr_note")]
        if not any(needle in value.casefold() for value in haystack if isinstance(value, str)):
            continue
        if stereotype is not None and not _has_stereotype(session, obj, stereotype):
            continue
        rows.append(_summary(session, obj))
    return _sorted(rows)


def _end_key(session, identifier: str) -> Key:
    record = session.working.resolve(session.find(identifier, kinds=("element", "package")))
    return package_twin(session, record).key if record.table == "t_package" else record.key


def find_connectors(
    session,
    source: str | None = None,
    target: str | None = None,
    type: str | None = None,
    stereotype: str | None = None,
) -> list[dict]:
    """Connectors matching every given filter: end identifiers, connector type and stereotype."""
    ends = {
        column: _end_key(session, identifier)
        for column, identifier in (("attr_start_object_id", source), ("attr_end_object_id", target))
        if identifier is not None
    }
    rows = []
    for conn in session.working.records("t_connector"):
        values = conn.values
        if any(values.get(column) != Ref("t_object", key) for column, key in ends.items()):
            continue
        if type is not None and values.get("attr_connector_type") != type:
            continue
        if stereotype is not None and not _has_stereotype(session, conn, stereotype):
            continue
        row = _summary(session, conn)
        row["source"] = _plain(session, values.get("attr_start_object_id"))
        row["target"] = _plain(session, values.get("attr_end_object_id"))
        rows.append(row)
    return _sorted(rows)
