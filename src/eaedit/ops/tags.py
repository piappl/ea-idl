"""Tagged-value operations on elements, packages, attributes and connectors."""

from __future__ import annotations

from eacore.catalogue import AmbiguousStereotype
from eacore.records import Record
from eaedit.errors import InvalidOperationError, NotFoundError
from eaedit.ops import operation
from eaedit.ops.common import find_tags, resolve_target, set_tag_value, stereotype_names


def _guid(record: Record) -> str:
    return record.values.get("attr_ea_guid") or record.key


def _known_tags(session, record: Record) -> set[str] | None:
    """Tag names the target's catalogued stereotypes define; None when none of them defines any."""
    names: set[str] = set()
    for name, fqname in stereotype_names(session, record):
        try:
            resolved = session.catalogues.resolved(fqname or name)
        except AmbiguousStereotype:
            continue
        if resolved is not None:
            names.update(t.name for t in resolved.tags)
    return names or None


@operation("set_tag")
def set_tag(session, target: str, name: str, value: str | None, notes: str | None = None) -> str:
    if not name:
        raise InvalidOperationError("a tag needs a name")
    record = resolve_target(session, target)
    known = _known_tags(session, record)
    if known is not None and name not in known:
        session.warn("unknown-tag", f"{name!r} is not a tag of the target's stereotypes", _guid(record))
    set_tag_value(session, record.table, record, name, value, notes)
    return _guid(record)


@operation("delete_tag")
def delete_tag(session, target: str, name: str) -> str:
    record = resolve_target(session, target)
    found = find_tags(session, record.table, record, name)
    if not found:
        raise NotFoundError(f"{target!r} has no tag {name!r}")
    for tag in found:
        session.drop(tag.table, tag.key)
    return _guid(record)
