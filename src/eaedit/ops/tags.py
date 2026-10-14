"""Tagged-value operations on elements, packages, attributes and connectors."""

from __future__ import annotations

from eaedit.errors import InvalidOperationError, NotFoundError
from eaedit.ops import operation
from eaedit.ops.common import find_tags, resolve_target, set_tag_value, stereotype_names, stereotype_tags
from eaedit.resolve import guid_of


@operation("set_tag")
def set_tag(session, target: str, name: str, value: str | None, notes: str | None = None) -> str:
    if not name:
        raise InvalidOperationError("a tag needs a name")
    record = resolve_target(session, target)
    # Only stereotypes that define tags make a name unknown.
    known = stereotype_tags(session, stereotype_names(session, record))
    if known and name not in known:
        session.warn("unknown-tag", f"{name!r} is not a tag of the target's stereotypes", guid_of(record))
    set_tag_value(session, record.table, record, name, value, notes)
    return guid_of(record)


@operation("delete_tag")
def delete_tag(session, target: str, name: str) -> str:
    record = resolve_target(session, target)
    found = find_tags(session, record.table, record, name)
    if not found:
        raise NotFoundError(f"{target!r} has no tag {name!r}")
    for tag in found:
        session.drop(tag.table, tag.key)
    return guid_of(record)
