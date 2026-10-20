from datetime import datetime

from eacore.backends.sql import load_file
from eacore.integrity import check
from eacore.records import Record, Ref
from eaedit import Session
from eaedit.defaults import DEFAULTS
from eaedit.ops.common import stereotype_names
from eaedit.resolve import find

FIXED = datetime(2026, 1, 2, 3, 4, 5)
MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Model::core::message::Message: 3 attributes


def _open(path, **kwargs):
    kwargs.setdefault("policy", "off")
    return Session.open(path, clock=lambda: FIXED, author="tester", **kwargs)


def _issues(rs):
    return {(i.severity, i.rule, i.ref, i.message) for i in check(rs)}


def _attrs(rs, owner_guid):
    owner = Ref("t_object", owner_guid)
    found = [r for r in rs.records("t_attribute") if r.values["attr_object_id"] == owner]
    return sorted(found, key=lambda r: r.values["attr_pos"])


def _names(rs, owner_guid):
    return [r.values["attr_name"] for r in _attrs(rs, owner_guid)]


def test_attribute_defaults_entry_verified():
    entry = DEFAULTS[("t_attribute", "*")]
    assert entry.verified and entry.values["attr_styleex"] == "volatile=0;"


def test_add_attribute_primitive_and_classifier(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    prim = session.add_attribute(el=MESSAGE, name="count", type="int").guid
    typed = session.add_attribute(el=MESSAGE, name="owner", type=MESSAGE, lower="0", upper="*").guid
    session.commit()

    rs = load_file(path)
    assert {i for i in _issues(rs) - baseline if i[0] == "error"} == set()
    p, t = rs.get("t_attribute", prim).values, rs.get("t_attribute", typed).values
    assert (p["attr_type"], p["attr_classifier"], p["attr_pos"]) == ("int", "0", 3)
    assert (p["attr_scope"], p["attr_containment"], p["attr_styleex"]) == ("Public", "Not Specified", "volatile=0;")
    assert t["attr_classifier"] == Ref("t_object", MESSAGE) and t["attr_type"] == "Message"
    assert (t["attr_lowerbound"], t["attr_upperbound"], t["attr_pos"]) == ("0", "*", 4)
    assert find(rs, "Model::core::message::Message.owner") == Ref("t_attribute", typed)


def test_move_attribute_renumbers(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    before = _names(session.working, MESSAGE)
    session.move_attribute(attr=f"Model::core::message::Message.{before[-1]}", position=0)
    session.commit()
    rs = load_file(path)
    assert _names(rs, MESSAGE) == [before[-1], *before[:-1]]
    assert [r.values["attr_pos"] for r in _attrs(rs, MESSAGE)] == [0, 1, 2]


def test_attribute_stereotype_xref_type(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    guid = session.add_attribute(el=MESSAGE, name="x", stereotype="lobw").guid
    session.commit()
    rs = load_file(path)
    xrefs = [x.values for x in rs.records("t_xref") if x.values["attr_client"] == guid]
    assert [(x["attr_name"], x["attr_type"]) for x in xrefs] == [("Stereotypes", "attribute property")]
    assert [n for n, _ in stereotype_names(rs_session(path), rs.get("t_attribute", guid))] == ["lobw"]


def rs_session(path):
    return _open(path)


def test_delete_attribute_drops_tags_and_xrefs(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    guid = session.add_attribute(el=MESSAGE, name="x", stereotype="lobw").guid
    session.commit()
    session = _open(path)
    record = session.working.get("t_attribute", guid)
    session.run("set_tag", target=guid, name="t", value="v")
    assert any(
        t.values["attr_elementid"] == Ref("t_attribute", guid) for t in session.working.records("t_attributetag")
    )
    session.delete_attribute(attr=guid)
    session.commit()
    rs = load_file(path)
    assert rs.get("t_attribute", record.key) is None
    assert not list(rs.records("t_attributetag"))
    assert not [x for x in rs.records("t_xref") if x.values["attr_client"] == guid]
    assert {i for i in _issues(rs) - baseline if i[0] == "error"} == set()


def test_delete_attribute_clears_side_letter_references(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    a = session.add_attribute(el=MESSAGE, name="a").guid
    connector = next(iter(session.working.records("t_connector")))
    other = "{11111111-1111-1111-1111-111111111111}"
    # LFSP/LFEP link a connector end to an attribute; EA writes a side letter after the GUID.
    style = f"Mode=3;LFSP={a}L;LFEP={a}R;LFSP={other}L;"
    session.working.remove("t_connector", connector.key)
    session.working.add(
        Record("t_connector", connector.key, {**connector.values, "attr_styleex": style}, connector.rid)
    )
    result = session.delete_attribute(attr=a)
    assert session.working.get("t_connector", connector.key).values["attr_styleex"] == f"Mode=3;LFSP={other}L;"
    assert "reference-cleared" in [w.code for w in result.warnings]


def test_delete_attribute_strips_whole_feature_link_entries_in_the_file(nafv4_path, qea_copy):
    import sqlite3

    path = qea_copy(nafv4_path)
    nationality = "{2D501BC6-55E7-4902-8D24-0F94971CFB1B}"  # Message.nationality
    uuid = "{114D8348-AB4E-46d0-9C4E-75F731B80914}"  # Message.uuid, kept
    styles = {
        "only": f"LFSP={nationality}R;",
        "last, no semicolon": f"Mode=3;LFEP={nationality}L",
        "between": f"LFSP={uuid}L;LFEP={nationality}R;paramvalues=Argument1;",
        "lower case": f"LFSP={nationality.lower()}L;Mode=3;",
    }
    expected = {
        "only": None,  # as the EA-made connectors in nafv4.qea without one (StyleEx NULL)
        "last, no semicolon": "Mode=3;",
        "between": f"LFSP={uuid}L;paramvalues=Argument1;",
        "lower case": "Mode=3;",
    }
    with sqlite3.connect(path) as conn:
        ids = [row[0] for row in conn.execute("SELECT Connector_ID FROM t_connector WHERE StyleEx IS NULL LIMIT 4")]
        for connector_id, style in zip(ids, styles.values()):
            conn.execute("UPDATE t_connector SET StyleEx = ? WHERE Connector_ID = ?", (style, connector_id))
    session = _open(path)
    session.delete_attribute(attr=nationality)
    session.commit()
    with sqlite3.connect(path) as conn:
        found = {
            case: conn.execute("SELECT StyleEx FROM t_connector WHERE Connector_ID = ?", (i,)).fetchone()[0]
            for case, i in zip(styles, ids)
        }
    assert found == expected


def test_set_classifier_on_part(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    part = session.create_element(package="Model::core", name="P1", type="Part").guid
    session.set_classifier(target=part, classifier=MESSAGE)
    session.commit()
    rs = load_file(path)
    assert rs.get("t_object", part).values["attr_classifier"] == Ref("t_object", MESSAGE)
    assert {i for i in _issues(rs) - baseline if i[0] == "error"} == set()

    session = _open(path)
    session.set_classifier(target=part, classifier=None)
    session.commit()
    assert load_file(path).get("t_object", part).values["attr_classifier"] == 0


def test_set_classifier_on_attribute_and_other_kind(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    attr = session.add_attribute(el=MESSAGE, name="x", type="int").guid
    session.set_classifier(target=attr, classifier=MESSAGE)
    values = session.working.get("t_attribute", attr).values
    assert (values["attr_type"], values["attr_classifier"]) == ("Message", Ref("t_object", MESSAGE))
    session.set_classifier(target=attr, classifier=None)
    assert session.working.get("t_attribute", attr).values["attr_classifier"] == "0"
    result = session.set_classifier(target=MESSAGE, classifier=MESSAGE)
    assert [w.code for w in result.warnings] == ["unverified-kind"]
