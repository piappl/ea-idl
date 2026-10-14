import pytest

from eacore.records import Record, RecordSet, Ref, TextRefs, key_str

G1 = "{11111111-1111-1111-1111-111111111111}"
G2 = "{22222222-2222-2222-2222-222222222222}"


def _rs(*records):
    rs = RecordSet()
    for r in records:
        rs.add(r)
    return rs


def test_record_equality_ignores_rid():
    assert Record("t_object", G1, {"attr_name": "A"}, rid=1) == Record("t_object", G1, {"attr_name": "A"}, rid=99)


def test_add_get_resolve_remove():
    rec = Record("t_object", G1, {"attr_name": "A", "attr_ea_guid": G1})
    rs = _rs(rec)
    assert rs.get("t_object", G1) is rec
    assert rs.resolve(Ref("t_object", G1)) is rec
    assert rs.tables() == ["t_object"]
    assert len(rs) == 1
    assert rs.remove("t_object", G1) is rec
    assert rs.get("t_object", G1) is None
    assert rs.tables() == []


def test_duplicate_key_rejected():
    rs = _rs(Record("t_object", G1, {}))
    with pytest.raises(KeyError):
        rs.add(Record("t_object", G1, {}))


def test_same_records_ignores_rids_and_empty_tables():
    a = _rs(Record("t_object", G1, {"attr_package_id": Ref("t_package", G2)}, rid=5))
    b = _rs(Record("t_object", G1, {"attr_package_id": Ref("t_package", G2)}, rid=500))
    assert a.same_records(b)
    b.add(Record("t_xref", G2, {}))
    b.remove("t_xref", G2)
    assert a.same_records(b)
    b.get("t_object", G1).values["attr_package_id"] = Ref("t_package", G1)
    assert not a.same_records(b)


def test_by_guid_finds_ea_guid_and_guid_keys():
    rs = _rs(
        Record("t_object", G1, {"attr_ea_guid": G1}),
        Record("t_package", G1, {"attr_ea_guid": G1}),
        Record("t_xref", G2, {"attr_xrefid": G2}),
    )
    assert sorted(r.table for r in rs.by_guid(G1)) == ["t_object", "t_package"]
    assert rs.by_guid(G2) == [Ref("t_xref", G2)]
    assert rs.by_guid("{nope}") == []


def test_key_str_and_hashable_values():
    assert key_str(G1) == G1
    assert key_str((Ref("t_diagram", G1), "ABCD1234")) == f"(t_diagram:{G1}, ABCD1234)"
    assert hash(TextRefs("idref1={0};", (Ref("t_connector", G1),)))
