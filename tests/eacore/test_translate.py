import pytest

from eacore.records import Ref, TextRefs
from eacore.tablemap import EA_TABLEMAP, ContentKey, DuidKey, GuidKey, NaturalKey, RefRule, TableSpec
from eacore.translate import UnresolvedReferenceError, candidate_key, decode_row, encode_value

PKG = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"
OBJ = "{04468E7C-0837-4f18-926C-CDE648A3912B}"
CON = "{145A428A-6EBC-4dc8-80B3-3CF43A35FAE8}"
DIA = "{3522A830-8853-4c52-9908-40871435BB3B}"
IDMAPS = {"t_package": {3: PKG}, "t_object": {7: OBJ}, "t_connector": {54: CON, 55: CON + "x"}, "t_diagram": {12: DIA}}
RIDMAPS = {t: {k: i for i, k in m.items()} for t, m in IDMAPS.items()}
T_OBJECT = EA_TABLEMAP.spec("t_object")


def _obj(**cols):
    row = {"attr_object_type": "Class", "attr_ntype": 0, "attr_package_id": 3, "attr_parentid": 0, "attr_classifier": 0}
    row.update(cols)
    return row


def test_int_and_text_refs_decode_and_encode_back():
    values, problems = decode_row(T_OBJECT, _obj(attr_object_type="Package", attr_pdata1="3"), IDMAPS)
    assert problems == []
    assert values["attr_package_id"] == Ref("t_package", PKG)
    assert values["attr_pdata1"] == Ref("t_package", PKG)
    assert values["attr_parentid"] == 0  # null value stays raw and exact
    assert encode_value(T_OBJECT, "attr_package_id", values["attr_package_id"], RIDMAPS) == 3
    assert encode_value(T_OBJECT, "attr_pdata1", values["attr_pdata1"], RIDMAPS) == "3"


def test_pattern_refs_round_trip_with_braces():
    raw = "idref1=54;idref2=55;{x}"
    values, problems = decode_row(T_OBJECT, _obj(attr_object_type="Note", attr_ntype=1, attr_pdata4=raw), IDMAPS)
    assert problems == []
    assert isinstance(values["attr_pdata4"], TextRefs)
    assert encode_value(T_OBJECT, "attr_pdata4", values["attr_pdata4"], RIDMAPS) == raw


def test_conditional_rule_picks_by_object_type():
    values, _ = decode_row(T_OBJECT, _obj(attr_object_type="InteractionFragment", attr_pdata1="12"), IDMAPS)
    assert values["attr_pdata1"] == Ref("t_diagram", DIA)
    values, problems = decode_row(T_OBJECT, _obj(attr_object_type="Part", attr_pdata1=OBJ), IDMAPS)
    assert values["attr_pdata1"] == OBJ and problems == []  # GUIDs stay text


def test_unexplained_and_dangling_are_reported_and_raw_kept():
    values, problems = decode_row(T_OBJECT, _obj(attr_pdata1="abc"), IDMAPS)
    assert values["attr_pdata1"] == "abc"
    assert [p.kind for p in problems] == ["unexplained"]
    values, problems = decode_row(T_OBJECT, _obj(attr_package_id=999), IDMAPS)
    assert values["attr_package_id"] == 999
    assert [p.kind for p in problems] == ["dangling"]


def test_encode_unknown_ref_raises():
    with pytest.raises(UnresolvedReferenceError):
        encode_value(T_OBJECT, "attr_package_id", Ref("t_package", "{missing}"), RIDMAPS)


def test_candidate_keys():
    assert candidate_key(TableSpec("t", GuidKey("attr_ea_guid")), {"attr_ea_guid": OBJ}) == OBJ
    assert candidate_key(TableSpec("t", NaturalKey(("attr_a", "attr_b"))), {"attr_a": 1, "attr_b": "x"}) == (1, "x")
    spec = TableSpec("t", DuidKey("attr_diagram_id", "attr_objectstyle", "attr_object_id"))
    d = Ref("t_diagram", DIA)
    assert candidate_key(spec, {"attr_diagram_id": d, "attr_objectstyle": "DUID=AB12CD34;"}) == (d, "AB12CD34")
    o = Ref("t_object", OBJ)
    no_duid = {"attr_diagram_id": d, "attr_objectstyle": "", "attr_object_id": o}
    assert candidate_key(spec, no_duid) == (d, o, "#no-duid")
    assert candidate_key(TableSpec("t", ContentKey()), {"attr_b": 2, "attr_a": b"\x00"}) == (
        ("attr_a", b"\x00"),
        ("attr_b", 2),
    )


def test_refrule_target_must_be_guid_keyed():
    from eacore.tablemap import TableMap

    with pytest.raises(ValueError):
        TableMap([TableSpec("t_a", GuidKey("attr_ea_guid"), rules=(RefRule("attr_x", "t_b"),))])
