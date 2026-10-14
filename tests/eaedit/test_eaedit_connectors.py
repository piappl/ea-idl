from datetime import datetime

import pytest

from eacore.backends.sql import load_file
from eacore.integrity import check
from eacore.records import Ref
from eaedit import InvalidOperationError, ScopeError, Session
from eaedit.ops.common import stereotype_names

FIXED = datetime(2026, 1, 2, 3, 4, 5)
MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Model::core::message::Message
MESSAGE_HEADER = "{5BE95D32-6D93-4dfb-8010-F68E5891C7D7}"  # Model::core::message, on diagram 'header'
MESSAGE_TYPE = "{D41FAABA-A0FF-4b3b-97B6-A36E88A568FF}"  # Model::core::message, on diagram 'header'
TIME = "{B7F3CB58-65C8-49ce-BF01-B9F067BC4E82}"  # Model::core::types, on diagram 'header'
MEASUREMENT = "{360F4F18-9BCE-4efe-A337-2958FE3DCA3C}"  # Model::core::data, not on diagram 'header'
# AbstractMessageHeader -> Time, shown on diagram 'header' only.
HEADER_TIME = "{9D921DEA-2287-4319-9267-EE0C06A9F00C}"
# Message -> MessageHeader, shown on diagram 'header' only.
MESSAGE_HEADER_LINK = "{F6A9885A-C912-4295-A212-4925A0719F24}"
# «Implements» Abstraction with a tag, a stereotype t_xref row and a link on diagram 'L7'.
IMPLEMENTS = "{3E51008F-7711-4058-9F41-407FB91C7EE3}"


def _open(path, **kwargs):
    kwargs.setdefault("policy", "off")
    return Session.open(path, clock=lambda: FIXED, author="tester", **kwargs)


def _issues(rs):
    return {(i.severity, i.rule, i.ref, i.message) for i in check(rs)}


def _errors(rs, baseline):
    return sorted((i for i in _issues(rs) - baseline if i[0] == "error"), key=str)


def _links(rs, connector):
    return [
        link
        for link in rs.records("t_diagramlinks")
        if link.values["attr_connectorid"] == Ref("t_connector", connector)
    ]


def _codes(result, code):
    return [w for w in result.warnings if w.code == code]


def test_connect_association_roundtrip(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path, focus=["Model::core::message"], policy="connected")
    result = session.connect(source=MESSAGE, target=MEASUREMENT, name="measured", target_role="m")
    assert result.warnings == []
    guid = result.guid
    session.commit()

    rs = load_file(path)
    assert _errors(rs, baseline) == []
    values = rs.get("t_connector", guid).values
    assert values["attr_connector_type"] == "Association"
    assert values["attr_start_object_id"] == Ref("t_object", MESSAGE)
    assert values["attr_end_object_id"] == Ref("t_object", MEASUREMENT)
    assert (values["attr_name"], values["attr_destrole"]) == ("measured", "m")
    assert values["attr_direction"] == "Source -> Destination"
    assert values["attr_routestyle"] == 3 and values["attr_pdata5"] == "SX=0;SY=0;EX=0;EY=0;"
    assert values["attr_sourcestyle"].endswith("Navigable=Non-Navigable;")
    assert values["attr_ptstartx"] == 0 and values["attr_start_edge"] == 0


def test_connect_package_policy_cross_scope_raises(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path), focus=["Model::core::message"], policy="package")
    before = len(list(session.working.records("t_connector")))
    with pytest.raises(ScopeError):
        session.connect(source=MESSAGE, target=MEASUREMENT)
    assert len(list(session.working.records("t_connector"))) == before
    # Both ends inside the focus is fine.
    session.connect(source=MESSAGE, target=MESSAGE_TYPE)


def test_connect_with_stereotype_infers_type(nafv4_path, qea_copy, mini_mdg_path):
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path])
    result = session.connect(source=MESSAGE, target=MEASUREMENT, stereotype="MINI::Link")
    values = session.working.get("t_connector", result.guid).values
    assert (values["attr_connector_type"], values["attr_stereotype"]) == ("Dependency", "Link")
    record = session.working.get("t_connector", result.guid)
    assert stereotype_names(session, record) == [("Link", "MINI::Link")]
    # Dependency is not in nafv4.qea: its kind and defaults are unverified.
    assert {"unverified-kind", "unverified-default"} <= {w.code for w in result.warnings}


def test_connect_type_and_direction(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    guid = session.connect(source=MESSAGE, target=MEASUREMENT, type="Composition", direction="Unspecified").guid
    values = session.working.get("t_connector", guid).values
    assert (values["attr_connector_type"], values["attr_subtype"]) == ("Aggregation", "Strong")
    assert values["attr_direction"] == "Unspecified"
    with pytest.raises(InvalidOperationError, match="not a relationship"):
        session.connect(source=MESSAGE, target=MEASUREMENT, type="Class")
    with pytest.raises(InvalidOperationError, match="unknown field"):
        session.connect(source=MESSAGE, target=MEASUREMENT, colour="red")


def test_connector_end_warning(nafv4_path, qea_copy, mini_mdg_path):
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path])
    result = session.connect(source=MESSAGE, target=MEASUREMENT, stereotype="MINI::Link")
    warnings = _codes(result, "connector-end")
    # client and source constrain the start, supplier the end; realizingMeassage is ignored.
    assert len(warnings) == 3
    assert {w.rule_source for w in warnings} == {"MINI 1.0 metaconstraint"}
    assert all(w.target == result.guid for w in warnings)

    t1 = session.create_element(package="Model::core", name="T1", stereotype="MINI::Thing").guid
    t2 = session.create_element(package="Model::core", name="T2", stereotype="MINI::Thing").guid
    assert _codes(session.connect(source=t1, target=t2, stereotype="MINI::Link"), "connector-end") == []

    # A Base element satisfies "source" (Thing or Base, any-of) but not "client" (Thing only).
    base = session.create_element(package="Model::core", name="B", stereotype="MINI::Base").guid
    warnings = _codes(session.connect(source=base, target=t2, stereotype="MINI::Link"), "connector-end")
    assert len(warnings) == 1 and "client" in warnings[0].message


def test_connector_end_follows_generalization(nafv4_path, qea_copy, tmp_path, mini_mdg_path):
    # A stereotype specialising the required one satisfies the constraint.
    from eacore.catalogue import Catalogue, Source, StereotypeDef

    yaml_path = tmp_path / "x.yaml"
    special = StereotypeDef(name="Special", applies_to=["Class"], generalizes=["MINI::Thing"])
    Catalogue(profile="X", source=Source(kind="yaml"), stereotypes=[special]).save_yaml(yaml_path)
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path, yaml_path])
    s = session.create_element(package="Model::core", name="S", stereotype="X::Special").guid
    t = session.create_element(package="Model::core", name="T", stereotype="MINI::Thing").guid
    assert _codes(session.connect(source=s, target=t, stereotype="MINI::Link"), "connector-end") == []


def test_reconnect_drops_stale_links(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    assert len(_links(session.working, HEADER_TIME)) == 1
    session.reconnect(conn=HEADER_TIME, target=MEASUREMENT)
    values = session.working.get("t_connector", HEADER_TIME).values
    assert values["attr_end_object_id"] == Ref("t_object", MEASUREMENT)
    assert _links(session.working, HEADER_TIME) == []

    # The new end is on the diagram: the link stays and points at that object's DUID.
    (link,) = _links(session.working, MESSAGE_HEADER_LINK)
    assert "EOID=F76E5818;" in link.values["attr_style"]
    session.reconnect(conn=MESSAGE_HEADER_LINK, target=MESSAGE_TYPE)
    (link,) = _links(session.working, MESSAGE_HEADER_LINK)
    assert "EOID=CCBEFE7C;" in link.values["attr_style"] and "SOID=10AF495B;" in link.values["attr_style"]

    assert [i for i in _errors(session.working, baseline) if i[1] == "link-duid"] == []
    session.commit()
    assert _errors(load_file(path), baseline) == []


def test_reconnect_rechecks_ends(nafv4_path, qea_copy, mini_mdg_path):
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path])
    t1 = session.create_element(package="Model::core", name="T1", stereotype="MINI::Thing").guid
    t2 = session.create_element(package="Model::core", name="T2", stereotype="MINI::Thing").guid
    conn = session.connect(source=t1, target=t2, stereotype="MINI::Link").guid
    warnings = _codes(session.reconnect(conn=conn, target=MEASUREMENT), "connector-end")
    assert len(warnings) == 1 and "supplier" in warnings[0].message
    with pytest.raises(InvalidOperationError):
        session.reconnect(conn=conn)


def test_update_connector(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    session.update_connector(conn=HEADER_TIME, name="when", source_card="1")
    values = session.working.get("t_connector", HEADER_TIME).values
    assert (values["attr_name"], values["attr_sourcecard"]) == ("when", "1")
    with pytest.raises(InvalidOperationError, match="unknown field"):
        session.update_connector(conn=HEADER_TIME, colour="red")


def test_delete_connector_cascade(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    connector = Ref("t_connector", IMPLEMENTS)
    assert [t for t in session.working.records("t_connectortag") if t.values["attr_elementid"] == connector]
    assert [x for x in session.working.records("t_xref") if x.values["attr_client"] == IMPLEMENTS]
    assert _links(session.working, IMPLEMENTS)

    session.delete_connector(conn=IMPLEMENTS)
    assert session.working.get("t_connector", IMPLEMENTS) is None
    assert not [t for t in session.working.records("t_connectortag") if t.values["attr_elementid"] == connector]
    assert not [x for x in session.working.records("t_xref") if x.values["attr_client"] == IMPLEMENTS]
    assert _links(session.working, IMPLEMENTS) == []
    session.commit()
    assert _errors(load_file(path), baseline) == []
