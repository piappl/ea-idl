import sqlite3
import uuid

import pytest

from eacore.backends.sql import ConcurrentModificationError, RepositoryLockedError, SqlBackend
from eacore.changes import ChangeSet, Delete, Insert, Update
from eacore.records import Record, Ref


def _first_class(rs):
    return next(o for o in rs.records("t_object") if o.values["attr_object_type"] == "Class")


def test_empty_changeset_leaves_file_byte_identical(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    before = path.read_bytes()
    backend = SqlBackend.for_file(path)
    backend.load()
    backend.apply(ChangeSet())
    assert path.read_bytes() == before


def test_update_writes_only_that_column(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    name = "Zażółć gęślą jaźń\nline two"
    backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_name": (obj.values["attr_name"], name)})]))
    after = SqlBackend.for_file(path).load()
    changed = after.get("t_object", obj.key)
    assert changed.values["attr_name"] == name
    assert {k: v for k, v in changed.values.items() if k != "attr_name"} == {
        k: v for k, v in obj.values.items() if k != "attr_name"
    }


def test_insert_with_refs_and_delete(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    guid = "{" + str(uuid.uuid4()).upper() + "}"
    values = dict(obj.values, attr_ea_guid=guid, attr_name="NewClass")
    backend.apply(ChangeSet(inserts=[Insert(Record("t_object", guid, values))]))
    after = SqlBackend.for_file(path).load()
    new = after.get("t_object", guid)
    assert new.values["attr_package_id"] == obj.values["attr_package_id"]
    assert new.rid > rs.meta["max_ids"]["t_object"]  # a fresh ID, above every existing one
    assert after.meta["sequences"]["t_object"] >= new.rid  # SQLite advanced the sequence itself

    backend2 = SqlBackend.for_file(path)
    backend2.load()
    backend2.apply(ChangeSet(deletes=[Delete("t_object", guid)]))
    assert SqlBackend.for_file(path).load().get("t_object", guid) is None


def test_refuses_when_file_changed_since_load(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    with sqlite3.connect(path) as con:
        con.execute(
            "update t_object set Name = 'changed by EA' where Object_ID = (select min(Object_ID) from t_object)"
        )
    obj = _first_class(rs)
    with pytest.raises(ConcurrentModificationError):
        backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_alias": (None, "x")})]))


def test_refuses_when_locked_and_writes_nothing(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    before = path.read_bytes()
    locker = sqlite3.connect(path, isolation_level=None)
    locker.execute("BEGIN IMMEDIATE")
    try:
        obj = _first_class(rs)
        with pytest.raises(RepositoryLockedError):
            backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_alias": (None, "x")})]))
    finally:
        locker.execute("ROLLBACK")
        locker.close()
    assert path.read_bytes() == before


def test_without_columns_drops_only_those_changes():
    cs = ChangeSet(updates=[Update("t_object", "k", {"attr_modifieddate": (1, 2), "attr_name": ("a", "b")})])
    filtered = cs.without_columns(frozenset({("t_object", "attr_modifieddate")}))
    assert filtered.updates[0].changes == {"attr_name": ("a", "b")}
    assert (
        ChangeSet(updates=[Update("t_object", "k", {"attr_modifieddate": (1, 2)})])
        .without_columns(frozenset({("t_object", "attr_modifieddate")}))
        .is_empty()
    )


def test_ref_to_unknown_record_is_rejected(nafv4_path, qea_copy):
    from eacore.translate import UnresolvedReferenceError

    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    bad = Ref("t_package", "{00000000-0000-0000-0000-000000000000}")
    with pytest.raises(UnresolvedReferenceError):
        backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_package_id": (None, bad)})]))
