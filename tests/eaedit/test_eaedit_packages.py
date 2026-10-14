from datetime import datetime

import pytest

from eacore.backends.sql import load_file
from eacore.embedded import parse_stereotypes
from eacore.integrity import check
from eacore.records import Ref
from eaedit import InvalidOperationError, Session
from eaedit.resolve import find
from eaedit.ops.common import apply_stereotype, set_tag_value, stereotype_names

FIXED = datetime(2026, 1, 2, 3, 4, 5)
CORE = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"  # Model::core, a DataModel-free package


def _open(path, **kwargs):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester", **kwargs)


def _issues(rs):
    return {(i.severity, i.rule, i.ref, i.message) for i in check(rs)}


def _errors(rs, baseline):
    return [i for i in _issues(rs) - baseline if i[0] == "error"]


def _stereo_xrefs(rs, guid):
    return [
        x for x in rs.records("t_xref") if x.values["attr_name"] == "Stereotypes" and x.values["attr_client"] == guid
    ]


def test_create_package_pair(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    result = session.create_package(parent="Model", name="New")
    guid = result.guid
    [logged] = session.log
    assert logged.args["guid"] == guid and logged.created == [guid]
    session.commit()

    rs = load_file(path)
    assert _errors(rs, baseline) == []
    assert not [i for i in check(rs) if i.rule == "package-pair"]
    ref = find(rs, "Model::New")
    assert ref == Ref("t_package", guid)
    package = rs.resolve(ref).values
    twin = rs.get("t_object", guid).values
    assert rs.resolve(twin["attr_pdata1"]) is rs.resolve(ref)
    model = find(rs, "Model")
    assert package["attr_parent_id"] == model and twin["attr_package_id"] == model
    assert package["attr_createddate"] == package["attr_modifieddate"] == "2026-01-02 03:04:05"
    assert (twin["attr_object_type"], twin["attr_name"], twin["attr_author"]) == ("Package", "New", "tester")
    assert twin["attr_createddate"] == "2026-01-02 03:04:05"
    assert package["attr_version"] == twin["attr_version"] == "1.0"
    assert twin["attr_tpos"] == 1 + max(
        (
            o.values["attr_tpos"] or 0
            for o in rs.records("t_object")
            if o.values["attr_package_id"] == model and o.key != guid
        ),
        default=0,
    )
    assert result.warnings == []


def test_create_package_with_given_guid_and_notes(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    guid = "{11111111-2222-3333-4444-555555555555}"
    assert session.create_package(parent="Model::core", name="Given", notes="Text", guid=guid).guid == guid
    [logged] = session.log
    assert logged.args["guid"] == guid and logged.created == []
    assert session.working.get("t_package", guid).values["attr_notes"] == "Text"
    assert session.working.get("t_object", guid).values["attr_note"] == "Text"
    with pytest.raises(InvalidOperationError, match="already"):
        session.create_package(parent="Model", name="Again", guid=CORE)
    with pytest.raises(InvalidOperationError, match="GUID"):
        session.create_package(parent="Model", name="Bad", guid="nope")


def test_create_package_with_stereotype_writes_xref(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path, infer=False)
    result = session.create_package(parent="Model", name="Typed", stereotype="P::S")
    assert [w.code for w in result.warnings] == ["unknown-stereotype"]
    guid = result.guid
    assert len(session.log[0].created) == 2  # package GUID, then the t_xref XrefID
    session.commit()

    rs = load_file(path)
    [xref] = _stereo_xrefs(rs, guid)
    values = xref.values
    assert values["attr_description"] == "@STEREO;Name=S;FQName=P::S;@ENDSTEREO;"
    assert (values["attr_type"], values["attr_visibility"], values["attr_partition"], values["attr_supplier"]) == (
        "element property",
        "Public",
        "0",
        "<none>",
    )
    assert rs.get("t_object", guid).values["attr_stereotype"] == "S"
    assert not [i for i in check(rs) if i.rule.startswith("stereotype")]
    assert _errors(rs, baseline) == []


def test_create_package_in_empty_model(empty_path, qea_copy):
    path = qea_copy(empty_path)
    session = _open(path)
    guid = session.create_package(parent="Model", name="First").guid
    session.commit()
    rs = load_file(path)
    assert [i for i in check(rs) if i.severity == "error"] == []
    assert find(rs, "Model::First") == Ref("t_package", guid)
    assert rs.get("t_object", guid).values["attr_tpos"] == 1


def test_apply_known_stereotype_adds_tags_with_values_notes(nafv4_path, qea_copy):
    from eacore.catalogue import Catalogue, Source, StereotypeDef, TagDef

    tags = [
        TagDef(name="kind", type="enumeration", values=["A", "B"]),
        TagDef(name="URI"),
        TagDef(name="n", default="3"),
    ]
    catalogue = Catalogue(
        profile="T",
        source=Source(kind="yaml"),
        stereotypes=[StereotypeDef(name="Model", applies_to=["Package"], tags=tags)],
    )
    session = _open(qea_copy(nafv4_path), catalogues=[catalogue], infer=False)
    result = session.create_package(parent="Model", name="Data", stereotype="Model")
    assert result.warnings == []
    guid = result.guid
    assert session.working.get("t_object", guid).values["attr_stereotype"] == "Model"
    assert stereotype_names(session, session.working.get("t_package", guid)) == [("Model", "T::Model")]
    rows = {
        t.values["attr_property"]: (t.values["attr_value"], t.values["attr_notes"])
        for t in session.working.records("t_objectproperties")
        if t.values["attr_object_id"] == Ref("t_object", guid)
    }
    # Enumeration choices go to Notes as on EA-made DataModel packages in nafv4.qea ('kind').
    assert rows == {"kind": (None, "Values: A,B\r\n"), "URI": (None, None), "n": ("3", None)}
    assert not [i for i in check(session.working) if i.rule.startswith("stereotype")]


def _in_op(session, fn):
    """Run ``fn(session)`` as an ad-hoc operation, returning its warnings."""
    from eaedit.ops import OPERATIONS

    OPERATIONS["_test_adhoc"] = lambda s: fn(s)
    try:
        return session.run("_test_adhoc").warnings
    finally:
        OPERATIONS.pop("_test_adhoc")


def test_apply_stereotype_second_entry_ambiguous_and_duplicate(nafv4_path, qea_copy, mini_mdg_path):
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path])
    element = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Message class: DataElement, idlStruct
    record = session.working.get("t_object", element)
    before = stereotype_names(session, record)

    warnings = _in_op(session, lambda s: apply_stereotype(s, "t_object", s.working.get("t_object", element), "Thing"))
    assert warnings == []
    after = stereotype_names(session, session.working.get("t_object", element))
    assert after == before + [("Thing", "MINI::Thing")]
    assert session.working.get("t_object", element).values["attr_stereotype"] == after[0][0]
    tags = {
        t.values["attr_property"]
        for t in session.working.records("t_objectproperties")
        if t.values["attr_object_id"] == Ref("t_object", element)
    }
    assert {"owner", "kind", "ref"} <= tags

    again = _in_op(session, lambda s: apply_stereotype(s, "t_object", s.working.get("t_object", element), "Thing"))
    assert again == [] and stereotype_names(session, session.working.get("t_object", element)) == after

    codes = _in_op(session, lambda s: apply_stereotype(s, "t_object", s.working.get("t_object", element), "Base"))
    assert [w.code for w in codes] == ["abstract-stereotype"]
    codes = _in_op(session, lambda s: apply_stereotype(s, "t_object", s.working.get("t_object", element), "Link"))
    assert [w.code for w in codes] == ["wrong-base-type"]
    assert not [i for i in check(session.working) if i.rule.startswith("stereotype")]


def test_apply_stereotype_ambiguous_uses_bare_name(nafv4_path, qea_copy, mini_mdg_path):
    from eacore.catalogue import Catalogue, Source, StereotypeDef

    other = Catalogue(profile="OTHER", source=Source(kind="yaml"), stereotypes=[StereotypeDef(name="Thing")])
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path, other], infer=False)
    guid = "{9F3D867F-2B36-4ab7-9F95-7EB442443042}"  # DataMessage class
    warnings = _in_op(session, lambda s: apply_stereotype(s, "t_object", s.working.get("t_object", guid), "Thing"))
    assert [w.code for w in warnings] == ["ambiguous-stereotype"]
    assert stereotype_names(session, session.working.get("t_object", guid))[-1] == ("Thing", None)
    [xref] = _stereo_xrefs(session.working, guid)
    assert [s.fqname for s in parse_stereotypes(xref.values["attr_description"])][-1] is None


def test_set_tag_value_update_and_memo(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    guid = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"

    def set_values(s):
        target = s.working.get("t_object", guid)
        first = set_tag_value(s, "t_object", target, "fresh", "v1")
        second = set_tag_value(s, "t_object", target, "fresh", "v2")
        assert first.key == second.key and second.values["attr_value"] == "v2"
        kept = set_tag_value(s, "t_object", target, "fresh", "v3", only_if_missing=True)
        assert kept.values["attr_value"] == "v2"
        memo = set_tag_value(s, "t_object", target, "long", "x" * 300)
        assert (memo.values["attr_value"], memo.values["attr_notes"]) == ("<memo>", "x" * 300)

    warnings = _in_op(session, set_values)
    assert [w.code for w in warnings] == ["unverified-default"]
