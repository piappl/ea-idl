"""Package operations. A package is a pair: a ``t_package`` row and a ``t_object`` row of type Package."""

from __future__ import annotations

from eacore.embedded import is_guid
from eacore.records import Ref
from eaedit.defaults import new_record, timestamp
from eaedit.errors import InvalidOperationError
from eaedit.ops import operation
from eaedit.ops.common import apply_stereotype


def _primary_guid(session, guid: str | None) -> str:
    if guid is None:
        return session.new_guid()
    if not is_guid(guid):
        raise InvalidOperationError(f"{guid!r} is not a GUID")
    if session.working.by_guid(guid):
        raise InvalidOperationError(f"GUID {guid} is already used")
    session.created(guid)
    return guid


@operation("create_package")
def create_package(
    session, parent: str, name: str, stereotype: str | None = None, notes: str | None = None, guid: str | None = None
) -> str:
    if not name:
        raise InvalidOperationError("a package needs a name")
    parent_ref = session.find(parent, kinds=("package",))
    guid = _primary_guid(session, guid)
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
