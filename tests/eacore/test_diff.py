from eacore.diff import diff
from eacore.records import Record, RecordSet, Ref

G1, G2, G3 = (f"{{{n * 8}-1111-1111-1111-111111111111}}" for n in "123")


def _rs(*records):
    rs = RecordSet()
    for r in records:
        rs.add(r)
    return rs


def test_diff_detects_insert_update_delete():
    a = _rs(Record("t_object", G1, {"attr_name": "A"}), Record("t_object", G2, {"attr_name": "B"}))
    b = _rs(Record("t_object", G1, {"attr_name": "A2"}), Record("t_object", G3, {"attr_name": "C"}))
    cs = diff(a, b)
    assert [i.record.key for i in cs.inserts] == [G3]
    assert [(d.key, d.record.values["attr_name"]) for d in cs.deletes] == [(G2, "B")]
    assert [(u.key, u.changes) for u in cs.updates] == [(G1, {"attr_name": ("A", "A2")})]


def test_renumbering_is_invisible():
    a = _rs(Record("t_object", G1, {"attr_package_id": Ref("t_package", G2)}, rid=1))
    b = _rs(Record("t_object", G1, {"attr_package_id": Ref("t_package", G2)}, rid=999))
    assert diff(a, b).is_empty()


def test_diff_of_identical_files_is_empty(nafv4_path):
    from eacore.backends.sql import load_file

    assert diff(load_file(nafv4_path), load_file(nafv4_path)).is_empty()
