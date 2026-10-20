import re
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


def test_close_disposes_engines_and_releases_the_file(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    record = _first_class(rs)
    backend.apply(ChangeSet(updates=[Update("t_object", record.key, {"attr_note": (record.values["attr_note"], "x")})]))
    backend.close()
    # No pooled connection is left: the engines hold none after dispose().
    assert backend._read_engine.pool.checkedin() == 0 and backend._write_engine.pool.checkedin() == 0
    backend.close()  # closing twice is harmless


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


def test_hash_is_checked_under_the_write_lock(nafv4_path, qea_copy, monkeypatch):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    real_begin = backend._write_engine.begin

    def begin_after_other_writer():
        # Another program saves in the window just before we take the lock.
        with sqlite3.connect(path) as con:
            con.execute("update t_object set Name = 'saved by EA' where Object_ID = ?", (obj.rid,))
        return real_begin()

    monkeypatch.setattr(backend._write_engine, "begin", begin_after_other_writer, raising=False)
    with pytest.raises(ConcurrentModificationError):
        backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_alias": (None, "x")})]))
    other = SqlBackend.for_file(path).load().get("t_object", obj.key)
    assert other.values["attr_name"] == "saved by EA"
    assert other.values["attr_alias"] == obj.values["attr_alias"]


def _wal_copy(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    return path


def test_wal_mode_first_apply_succeeds(nafv4_path, qea_copy):
    """Opening a WAL file creates an empty -wal; that alone must not count as a change."""
    path = _wal_copy(nafv4_path, qea_copy)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_alias": (obj.values["attr_alias"], "x")})]))
    backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_alias": ("x", "y")})]))
    assert SqlBackend.for_file(path).load().get("t_object", obj.key).values["attr_alias"] == "y"


def test_wal_mode_external_commit_to_same_column_is_refused(nafv4_path, qea_copy):
    path = _wal_copy(nafv4_path, qea_copy)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    other = sqlite3.connect(path)  # stays open, so its commit stays in the -wal file
    try:
        other.execute("update t_object set Name = 'saved by EA' where Object_ID = ?", (obj.rid,))
        other.commit()
        with pytest.raises(ConcurrentModificationError):
            backend.apply(
                ChangeSet(updates=[Update("t_object", obj.key, {"attr_name": (obj.values["attr_name"], "mine")})])
            )
    finally:
        other.close()
    assert SqlBackend.for_file(path).load().get("t_object", obj.key).values["attr_name"] == "saved by EA"


def test_wal_mode_external_commit_elsewhere_is_refused(nafv4_path, qea_copy):
    """The whole-file guard covers the -wal file too, not only the main database file."""
    path = _wal_copy(nafv4_path, qea_copy)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    other = sqlite3.connect(path)
    try:
        other.execute("update t_object set Name = 'saved by EA' where Object_ID <> ?", (obj.rid,))
        other.commit()
        with pytest.raises(ConcurrentModificationError):
            backend.apply(
                ChangeSet(updates=[Update("t_object", obj.key, {"attr_alias": (obj.values["attr_alias"], "x")})])
            )
    finally:
        other.close()
    assert SqlBackend.for_file(path).load().get("t_object", obj.key).values["attr_alias"] == obj.values["attr_alias"]


def test_stale_old_value_is_refused_and_nothing_written(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    before = path.read_bytes()
    stale = ChangeSet(
        updates=[
            Update("t_object", obj.key, {"attr_alias": (obj.values["attr_alias"], "x")}),
            Update("t_object", obj.key, {"attr_name": ("not the current name", "mine")}),
        ]
    )
    with pytest.raises(ConcurrentModificationError):
        backend.apply(stale)
    assert path.read_bytes() == before


def test_stale_old_ref_value_is_refused(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    other_pkg = next(p.key for p in rs.records("t_package") if Ref("t_package", p.key) != obj.values["attr_package_id"])
    old = Ref("t_package", other_pkg)
    with pytest.raises(ConcurrentModificationError):
        backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_package_id": (old, old)})]))


def test_delete_of_vanished_row_is_refused(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    with sqlite3.connect(path) as con:
        con.execute("delete from t_object where Object_ID = ?", (obj.rid,))
    backend._hash = backend._file_hash()  # isolate the row check from the whole-file guard
    with pytest.raises(ConcurrentModificationError):
        backend.apply(ChangeSet(deletes=[Delete("t_object", obj.key)]))


def test_update_or_delete_of_unloaded_key_names_table_and_key(nafv4_path, qea_copy):
    from eacore.backends.sql import UnknownRecordError

    path = qea_copy(nafv4_path)
    before = path.read_bytes()
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    missing = "{00000000-0000-0000-0000-0000000000AA}"
    obj = _first_class(rs)
    with pytest.raises(UnknownRecordError, match=rf"t_object {re.escape(missing)}"):
        backend.apply(ChangeSet(updates=[Update("t_object", missing, {"attr_name": ("a", "b")})]))
    with pytest.raises(UnknownRecordError, match=rf"t_attribute {re.escape(missing)}"):
        # nothing is written, not even the valid change listed with it
        backend.apply(
            ChangeSet(
                updates=[Update("t_object", obj.key, {"attr_note": (obj.values["attr_note"], "x")})],
                deletes=[Delete("t_attribute", missing)],
            )
        )
    assert path.read_bytes() == before


def test_delete_then_insert_of_the_same_key(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    backend = SqlBackend.for_file(path)
    rs = backend.load()
    obj = _first_class(rs)
    replacement = Record("t_object", obj.key, dict(obj.values, attr_name="Replaced"))
    # a new row referring to the replaced one resolves to the replacement's ID
    child_guid = "{" + str(uuid.uuid4()).upper() + "}"
    child = Record(
        "t_object", child_guid, dict(obj.values, attr_ea_guid=child_guid, attr_parentid=Ref("t_object", obj.key))
    )
    backend.apply(ChangeSet(inserts=[Insert(replacement), Insert(child)], deletes=[Delete("t_object", obj.key)]))
    after = SqlBackend.for_file(path).load()
    new = after.get("t_object", obj.key)
    assert new.values["attr_name"] == "Replaced" and new.rid != obj.rid
    assert after.get("t_object", child_guid).values["attr_parentid"] == Ref("t_object", obj.key)
    with sqlite3.connect(path) as con:
        assert con.execute("select count(*) from t_object where ea_guid = ?", (obj.key,)).fetchone()[0] == 1
    # the backend's own ID map follows: a later update of the key reaches the new row
    backend.apply(ChangeSet(updates=[Update("t_object", obj.key, {"attr_name": ("Replaced", "Again")})]))
    assert SqlBackend.for_file(path).load().get("t_object", obj.key).values["attr_name"] == "Again"
