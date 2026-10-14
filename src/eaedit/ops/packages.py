"""Package operations. A package is a pair: a ``t_package`` row and a ``t_object`` row of type Package."""

from __future__ import annotations

from eacore.records import Key, Record, Ref
from eaedit.defaults import FIELDS, apply_fields, new_record, timestamp
from eaedit.errors import InvalidOperationError
from eaedit.ops import operation
from eaedit.ops.common import apply_stereotype, package_twin, primary_guid
from eaedit.ops.elements import cascade_delete


@operation("create_package")
def create_package(
    session, parent: str, name: str, stereotype: str | None = None, notes: str | None = None, guid: str | None = None
) -> str:
    if not name:
        raise InvalidOperationError("a package needs a name")
    parent_ref = session.find(parent, kinds=("package",))
    guid = primary_guid(session, guid)
    now = timestamp(session.now())
    dates = {"attr_createddate": now, "attr_modifieddate": now}
    package = new_record(
        session,
        "t_package",
        {"attr_ea_guid": guid, "attr_name": name, "attr_parent_id": parent_ref, "attr_notes": notes, **dates},
    )
    twin = new_record(
        session,
        "t_object",
        {
            "attr_object_type": "Package",
            "attr_ea_guid": guid,
            "attr_name": name,
            "attr_package_id": parent_ref,
            "attr_pdata1": Ref("t_package", guid),
            # Package notes are shown from either row, so both carry them.
            "attr_note": notes,
            "attr_author": session.author,
            **dates,
        },
        "Package",
    )
    session.put(package)
    session.put(twin)
    if stereotype:
        apply_stereotype(session, "t_package", package, stereotype)
    return guid


def _package(session, identifier: str) -> Record:
    return session.working.resolve(session.find(identifier, kinds=("package",)))


@operation("update_package")
def update_package(session, pkg: str, **fields) -> str:
    package = _package(session, pkg)
    twin = package_twin(session, package)
    unknown = sorted(set(fields) - set(FIELDS["t_package"]) - set(FIELDS["t_object"]))
    if unknown:
        allowed = ", ".join(sorted(set(FIELDS["t_package"]) | set(FIELDS["t_object"])))
        raise InvalidOperationError(f"unknown field(s) {', '.join(unknown)} for a package; allowed: {allowed}")
    now = timestamp(session.now())
    own = {k: v for k, v in fields.items() if k in FIELDS["t_package"]}
    # Name, notes and version are kept on both rows; the other element properties (alias, status, ...) on the twin.
    values = {**apply_fields("t_package", package.values, own), "attr_modifieddate": now}
    session.put(Record("t_package", package.key, values, package.rid))
    values = {**apply_fields("t_object", twin.values, fields), "attr_modifieddate": now}
    session.put(Record("t_object", twin.key, values, twin.rid))
    return package.key


def _subtree(session, key: Key) -> list[Key]:
    """``key`` and every package below it."""
    children: dict[Key, list[Key]] = {}
    for package in session.working.records("t_package"):
        parent = package.values.get("attr_parent_id")
        if isinstance(parent, Ref):
            children.setdefault(parent.key, []).append(package.key)
    result, todo = [], [key]
    while todo:
        current = todo.pop()
        if current not in result:
            result.append(current)
            todo.extend(children.get(current, []))
    return result


@operation("move_package")
def move_package(session, pkg: str, new_parent: str) -> str:
    package = _package(session, pkg)
    if not isinstance(package.values.get("attr_parent_id"), Ref):
        raise InvalidOperationError(f"{pkg!r} is the root package and cannot be moved")
    parent = session.find(new_parent, kinds=("package",))
    if parent.key in _subtree(session, package.key):
        raise InvalidOperationError(f"moving {pkg!r} under {new_parent!r} would make a cycle")
    twin = package_twin(session, package)
    now = timestamp(session.now())
    values = {**package.values, "attr_parent_id": parent, "attr_modifieddate": now}
    session.put(Record("t_package", package.key, values, package.rid))
    values = {**twin.values, "attr_package_id": parent, "attr_modifieddate": now}
    session.put(Record("t_object", twin.key, values, twin.rid))
    return package.key


@operation("delete_package")
def delete_package(session, pkg: str, recursive: bool = False) -> str:
    package = _package(session, pkg)
    if not isinstance(package.values.get("attr_parent_id"), Ref):
        raise InvalidOperationError(f"{pkg!r} is the root package and cannot be deleted")
    packages = _subtree(session, package.key)
    refs = {Ref("t_package", k) for k in packages}
    elements = [o.key for o in session.working.records("t_object") if o.values.get("attr_package_id") in refs]
    diagrams = [d.key for d in session.working.records("t_diagram") if d.values.get("attr_package_id") in refs]
    if (elements or diagrams) and not recursive:
        raise InvalidOperationError(f"package {pkg!r} is not empty: pass recursive=True to delete its contents")
    # The package's own twin goes through the cascade too: its tags, stereotype t_xref and diagram objects.
    cascade_delete(session, [package_twin(session, package).key, *elements], diagrams)
    for key in packages:
        session.drop("t_package", key)
    return package.key
