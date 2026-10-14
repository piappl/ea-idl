from datetime import datetime

import pytest

from eacore.backends.sql import load_file
from eacore.catalogue import Catalogue, Source, StereotypeDef, TagDef
from eacore.integrity import check
from eacore.records import Ref
from eaedit import InvalidOperationError, NotFoundError, ScopeError, Session
from eaedit.ops.common import stereotype_names
from eaedit.resolve import find

FIXED = datetime(2026, 1, 2, 3, 4, 5)
MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Model::core::message::Message: 3 attributes, 5 connectors


def _open(path, **kwargs):
    kwargs.setdefault("policy", "off")
    return Session.open(path, clock=lambda: FIXED, author="tester", **kwargs)


def _issues(rs):
    return {(i.severity, i.rule, i.ref, i.message) for i in check(rs)}


def _errors(rs, baseline):
    return sorted((i for i in _issues(rs) - baseline if i[0] == "error"), key=str)


def _tags(rs, guid):
    return {
        t.values["attr_property"]: t.values["attr_value"]
        for t in rs.records("t_objectproperties")
        if t.values["attr_object_id"] == Ref("t_object", guid)
    }


def test_create_element_from_stereotype_gets_tags(nafv4_path, qea_copy, mini_mdg_path):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path, catalogues=[mini_mdg_path])
    result = session.create_element(package="Model::core", name="T1", stereotype="MINI::Thing")
    assert result.warnings == []
    guid = result.guid
    session.commit()

    rs = load_file(path)
    assert _errors(rs, baseline) == []
    element = rs.get("t_object", guid).values
    assert (element["attr_object_type"], element["attr_stereotype"], element["attr_name"]) == ("Class", "Thing", "T1")
    assert element["attr_package_id"] == find(rs, "Model::core")
    assert element["attr_author"] == "tester" and element["attr_createddate"] == "2026-01-02 03:04:05"
    assert element["attr_tpos"] is None
    assert _tags(rs, guid) == {"kind": "a", "ref": None, "owner": None}
    assert find(rs, "Model::core::T1") == Ref("t_object", guid)


def test_create_element_child_uses_parent_package(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    guid = session.create_element(package=None, name="Inner", parent=MESSAGE).guid
    values = session.working.get("t_object", guid).values
    assert values["attr_parentid"] == Ref("t_object", MESSAGE)
    assert values["attr_package_id"] == session.working.get("t_object", MESSAGE).values["attr_package_id"]
    with pytest.raises(InvalidOperationError, match="package"):
        session.create_element(package="Model::core::data", name="Wrong", parent=MESSAGE)


def test_create_element_ambiguous_stereotype_warns(nafv4_path, qea_copy, tmp_path):
    paths = []
    for profile in ("P", "Q"):
        yaml_path = tmp_path / f"{profile}.yaml"
        stereo = StereotypeDef(name="S", applies_to=["Class"], tags=[TagDef(name="t", default="1")])
        Catalogue(profile=profile, source=Source(kind="yaml"), stereotypes=[stereo]).save_yaml(yaml_path)
        paths.append(yaml_path)
    session = _open(qea_copy(nafv4_path), catalogues=paths, infer=False)
    result = session.create_element(package="Model::core", name="Amb", stereotype="S")
    assert [w.code for w in result.warnings] == ["ambiguous-stereotype"]
    assert session.working.get("t_object", result.guid).values["attr_object_type"] == "Class"
    assert _tags(session.working, result.guid) == {}


def test_create_element_type_from_applies_to(nafv4_path, qea_copy):
    stereos = [StereotypeDef(name="N", applies_to=["Note"]), StereotypeDef(name="Two", applies_to=["Class", "Part"])]
    catalogue = Catalogue(profile="T", source=Source(kind="yaml"), stereotypes=stereos)
    session = _open(qea_copy(nafv4_path), catalogues=[catalogue], infer=False)
    guid = session.create_element(package="Model::core", name="n", stereotype="T::N").guid
    assert session.working.get("t_object", guid).values["attr_object_type"] == "Note"
    with pytest.raises(InvalidOperationError, match="type="):
        session.create_element(package="Model::core", name="x", stereotype="T::Two")
    guid = session.create_element(package="Model::core", name="y", stereotype="T::Two", type="Class").guid
    assert session.working.get("t_object", guid).values["attr_object_type"] == "Class"
    with pytest.raises(InvalidOperationError, match="connect"):
        session.create_element(package="Model::core", name="z", type="Association")


def test_create_element_unknown_type_warns_unverified(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    result = session.create_element(package="Model::core", name="G", type="Gizmo")
    assert "unverified-kind" in [w.code for w in result.warnings]
    assert session.working.get("t_object", result.guid).values["attr_object_type"] == "Gizmo"
    plain = session.create_element(package="Model::core", name="C")
    assert plain.warnings == []
    assert session.working.get("t_object", plain.guid).values["attr_object_type"] == "Class"


def test_update_element_fields_and_unknown_field_error(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    guid = session.update_element(el=MESSAGE, alias="Msg", status="Approved", abstract=True).guid
    assert guid == MESSAGE
    values = session.working.get("t_object", MESSAGE).values
    assert (values["attr_alias"], values["attr_status"], values["attr_abstract"]) == ("Msg", "Approved", "1")
    assert values["attr_modifieddate"] == "2026-01-02 03:04:05"
    with pytest.raises(InvalidOperationError, match="colour"):
        session.update_element(el=MESSAGE, colour="red")
    with pytest.raises(InvalidOperationError, match="_package operations"):
        session.update_element(el="{753A4DFC-7876-4b00-BB5A-6274AD3817C3}", alias="x")
    session.commit()
    assert load_file(path).get("t_object", MESSAGE).values["attr_alias"] == "Msg"


def test_unicode_name_and_notes_roundtrip(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    name, notes = "Zażółć gęślą jaźń", "pierwsza linia\r\ndruga — ąę"
    guid = session.create_element(package="Model::core", name=name, notes=notes).guid
    session.commit()
    values = load_file(path).get("t_object", guid).values
    assert (values["attr_name"], values["attr_note"]) == (name, notes)


def test_move_element_and_scope(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    child = session.create_element(package=None, name="Inner", parent=MESSAGE).guid
    session.move_element(el=MESSAGE, package="Model::core::data")
    data = find(session.working, "Model::core::data")
    assert session.working.get("t_object", MESSAGE).values["attr_package_id"] == data
    assert session.working.get("t_object", child).values["attr_package_id"] == data
    assert session.working.get("t_object", MESSAGE).values["attr_modifieddate"] == "2026-01-02 03:04:05"

    scoped = _open(qea_copy(nafv4_path, "scoped.qea"), focus=["Model::core::message"], policy="connected")
    with pytest.raises(ScopeError):
        scoped.move_element(el=MESSAGE, package="Model::core::data")
    assert scoped.working.same_records(scoped.original)
    outside = find(scoped.working, "Model::core::data::Measurement").key
    with pytest.raises(ScopeError):
        scoped.move_element(el=outside, package="Model::core::message")
    assert scoped.working.same_records(scoped.original)


def test_delete_element_cascades(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    original = session.working
    element = Ref("t_object", MESSAGE)
    attributes = {a.key for a in original.records("t_attribute") if a.values["attr_object_id"] == element}
    connectors = {
        c.key
        for c in original.records("t_connector")
        if element in (c.values["attr_start_object_id"], c.values["attr_end_object_id"])
    }
    shown = [d.key for d in original.records("t_diagramobjects") if d.values["attr_object_id"] == element]
    assert len(attributes) == 3 and len(connectors) == 5 and len(shown) == 3
    guids = {MESSAGE} | attributes | connectors

    session.delete_element(el=MESSAGE)
    deleted = {(d.table, d.key) for d in session.preview().changes.deletes}
    assert ("t_object", MESSAGE) in deleted
    assert {("t_attribute", k) for k in attributes} <= deleted
    assert {("t_connector", k) for k in connectors} <= deleted
    assert {("t_diagramobjects", k) for k in shown} <= deleted
    tables = {t for t, _ in deleted}
    assert {"t_objectproperties", "t_xref", "t_diagramlinks"} <= tables
    assert session.preview().new_issues == []
    session.commit()

    rs = load_file(path)
    assert _errors(rs, baseline) == []
    assert not [g for g in guids if rs.by_guid(g)]
    assert not [x for x in rs.records("t_xref") if x.values["attr_client"] in guids]


def test_delete_element_drops_children_and_their_tags(nafv4_path, qea_copy, mini_mdg_path):
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path])
    parent = session.create_element(package="Model::core", name="Parent").guid
    child = session.create_element(package=None, name="Child", parent=parent, stereotype="MINI::Thing").guid
    grandchild = session.create_element(package=None, name="Grand", parent=child).guid
    session.delete_element(el=parent)
    assert session.working.same_records(session.original)
    for guid in (parent, child, grandchild):
        assert session.working.by_guid(guid) == []


def test_delete_package_requires_recursive(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    with pytest.raises(InvalidOperationError, match="recursive"):
        session.delete_package(pkg="Model::core")
    assert session.working.same_records(session.original)

    # Model::core holds sub-packages (common::types two levels down), elements, diagrams and connectors.
    packages = [p.key for p in session.working.records("t_package") if p.key != find(session.working, "Model").key]
    packages = [k for k in packages if find(session.working, "Model::core").key in _ancestors(session.working, k)]
    assert find(session.working, "Model::core::common::types").key in packages
    refs = {Ref("t_package", k) for k in packages}
    contained = [o.key for o in session.working.records("t_object") if o.values["attr_package_id"] in refs]
    diagrams = [d.key for d in session.working.records("t_diagram") if d.values["attr_package_id"] in refs]
    assert diagrams and len(contained) > 20
    session.delete_package(pkg="Model::core", recursive=True)
    session.commit()

    rs = load_file(path)
    assert _errors(rs, baseline) == []
    for guid in [*packages, *contained, *diagrams]:
        assert rs.by_guid(guid) == []
    with pytest.raises(NotFoundError):
        find(rs, "Model::core")


def _ancestors(rs, key):
    """``key`` and the keys of the packages above it."""
    result = []
    while key is not None:
        result.append(key)
        parent = rs.get("t_package", key).values["attr_parent_id"]
        key = parent.key if isinstance(parent, Ref) else None
    return result


def test_delete_package_with_diagram(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    l7 = find(session.working, "Model::L7")
    [diagram] = [d.key for d in session.working.records("t_diagram") if d.values["attr_package_id"] == l7]
    session.delete_package(pkg="Model::L7", recursive=True)
    session.commit()
    rs = load_file(path)
    assert _errors(rs, baseline) == []
    assert rs.by_guid(diagram) == [] and rs.by_guid(l7.key) == []
    assert not [d for d in rs.records("t_diagramobjects") if d.values["attr_diagram_id"] == Ref("t_diagram", diagram)]
    assert not [x for x in rs.records("t_xref") if x.values["attr_client"] == diagram]


def _cleared(warnings):
    return sorted(w.target for w in warnings if w.code == "reference-cleared")


def test_delete_package_clears_references_from_outside(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    measurement = find(session.working, "Model::core::data::Measurement.temperature_measurement")
    node_id = find(session.working, "Model::core::recursion::Node::id")
    result = session.delete_package(pkg="Model::core::common::types", recursive=True)
    assert not [i for i in session.preview().new_issues if i.rule == "dangling-reference"]
    attribute = session.working.resolve(measurement).values
    # EA's unset Classifier on attributes is '0' (nafv4.qea); the type name stays as text.
    assert (attribute["attr_classifier"], attribute["attr_type"]) == ("0", "TemperatureMeasurement")
    assert session.working.resolve(node_id).values["attr_pdata1"] is None
    cleared = _cleared(result.warnings)
    assert measurement.key in cleared and node_id.key in cleared
    assert len(cleared) == len(set(cleared))  # once per row
    session.commit()
    assert _errors(load_file(path), baseline) == []


def test_delete_element_clears_attribute_type(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    header = find(session.working, "Model::core::message::Message.header")
    result = session.delete_element(el="Model::core::message::MessageHeader")
    values = session.working.resolve(header).values
    assert (values["attr_classifier"], values["attr_type"]) == ("0", "MessageHeader")
    [warning] = [w for w in result.warnings if w.target == header.key]
    assert "t_attribute" in warning.message and "attr_classifier" in warning.message
    session.commit()
    assert _errors(load_file(path), baseline) == []


def test_delete_element_resets_xref_supplier_and_part_type(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    node_id = find(session.working, "Model::core::recursion::Node::id")
    [props] = [x for x in session.working.records("t_xref") if x.values["attr_client"] == node_id.key]
    connector = props.values["attr_supplier"]  # Node -> Identifier association, deleted with Identifier
    result = session.delete_element(el="Model::core::common::types::Identifier")
    assert session.working.get("t_connector", connector) is None
    kept = session.working.get("t_xref", props.key)
    assert kept is not None and kept.values["attr_supplier"] == "<none>"
    assert kept.values["attr_description"] == props.values["attr_description"]
    assert session.working.resolve(node_id).values["attr_pdata1"] is None
    assert {props.key, node_id.key} <= set(_cleared(result.warnings))
    session.commit()
    assert _errors(load_file(path), baseline) == []


def test_delete_element_strips_note_link_to_deleted_connector(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    note = "{FE0B8C60-0CE2-449d-A789-1ABA2873AAFE}"  # Note in Model::p6 linked to a message in Model::p2
    assert session.working.get("t_object", note).values["attr_pdata4"].refs
    result = session.delete_element(el="Model::p2::ResourceArchitecture::Asset2")
    assert session.working.get("t_object", note).values["attr_pdata4"] is None
    assert _cleared(result.warnings) == [note]
    session.commit()
    assert _errors(load_file(path), baseline) == []


def test_strip_text_refs_keeps_other_entries():
    from eacore.records import TextRefs
    from eaedit.ops.elements import _strip_text_refs

    a, b, c = (Ref("t_connector", k) for k in "abc")
    value = TextRefs("idref1={0};idref2={1};x={{y}};idref3={2};", (a, b, c))
    assert _strip_text_refs(value, {b}, None) == TextRefs("idref1={0};x={{y}};idref3={1};", (a, c))
    assert _strip_text_refs(TextRefs("idref1={0};", (a,)), {a}, None) is None


def test_delete_empty_package(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    guid = session.create_package(parent="Model", name="Empty").guid
    session.delete_package(pkg=guid)
    assert session.working.same_records(session.original)


def test_update_and_move_package(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    guid = session.create_package(parent="Model", name="Old").guid
    session.update_package(pkg=guid, name="New", alias="Al", notes="N", status="Approved")
    package, twin = session.working.get("t_package", guid).values, session.working.get("t_object", guid).values
    assert package["attr_name"] == twin["attr_name"] == "New"
    assert package["attr_notes"] == twin["attr_note"] == "N"
    assert (twin["attr_alias"], twin["attr_status"]) == ("Al", "Approved")
    with pytest.raises(InvalidOperationError, match="colour"):
        session.update_package(pkg=guid, colour="red")

    session.move_package(pkg=guid, new_parent="Model::core")
    core = find(session.working, "Model::core")
    assert session.working.get("t_package", guid).values["attr_parent_id"] == core
    assert session.working.get("t_object", guid).values["attr_package_id"] == core
    session.commit()
    rs = load_file(path)
    assert _errors(rs, baseline) == []
    assert find(rs, "Model::core::New") == Ref("t_package", guid)


def test_move_package_sets_modified_on_both_rows(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    p2 = find(session.working, "Model::p2").key
    session.move_package(pkg=p2, new_parent="Model::core")
    for table in ("t_package", "t_object"):
        assert session.working.get(table, p2).values["attr_modifieddate"] == "2026-01-02 03:04:05"


def test_remove_stereotype_ignores_tags_of_remaining_stereotypes(nafv4_path, qea_copy, mini_mdg_path):
    other = Catalogue(
        profile="Y",
        source=Source(kind="yaml"),
        stereotypes=[StereotypeDef(name="Other", applies_to=["Class"], tags=[TagDef(name="kind")])],
    )
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path, other], infer=False)
    guid = session.create_element(package="Model::core", name="E", stereotype="MINI::Thing").guid
    session.add_stereotype(target=guid, name="Y::Other")
    [warning] = session.remove_stereotype(target=guid, name="Thing").warnings
    assert warning.code == "stereotype-removed-tags-kept"
    assert "ref" in warning.message and "owner" in warning.message and "kind" not in warning.message
    assert session.remove_stereotype(target=guid, name="Other").warnings  # 'kind' is now nobody's


def test_move_package_cycle_error(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    with pytest.raises(InvalidOperationError, match="cycle"):
        session.move_package(pkg="Model::core", new_parent="Model::core::common::types")
    with pytest.raises(InvalidOperationError, match="cycle"):
        session.move_package(pkg="Model::core", new_parent="Model::core")
    with pytest.raises(InvalidOperationError, match="root"):
        session.move_package(pkg="Model", new_parent="Model::core")
    assert session.working.same_records(session.original)


def test_add_remove_stereotype_xref_consistent(nafv4_path, qea_copy, mini_mdg_path):
    path = qea_copy(nafv4_path)
    session = _open(path, catalogues=[mini_mdg_path])
    record = lambda: session.working.get("t_object", MESSAGE)  # noqa: E731
    before = stereotype_names(session, record())
    primary = record().values["attr_stereotype"]
    assert len(before) >= 2 and before[0][0] == primary

    assert session.add_stereotype(target=MESSAGE, name="MINI::Thing").guid == MESSAGE
    assert stereotype_names(session, record()) == before + [("Thing", "MINI::Thing")]
    assert record().values["attr_stereotype"] == primary

    session.remove_stereotype(target=MESSAGE, name=primary)
    after = stereotype_names(session, record())
    assert after == before[1:] + [("Thing", "MINI::Thing")]
    assert record().values["attr_stereotype"] == after[0][0]
    assert not [i for i in check(session.working) if i.rule.startswith("stereotype")]
    with pytest.raises(NotFoundError):
        session.remove_stereotype(target=MESSAGE, name=primary)

    session.remove_stereotype(target=MESSAGE, name="Thing")
    assert stereotype_names(session, record()) == before[1:]


def test_remove_last_stereotype_drops_xref(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path), infer=False)
    guid = session.create_element(package="Model::core", name="E", stereotype="X::Only").guid
    session.remove_stereotype(target=guid, name="X::Only")
    assert session.working.get("t_object", guid).values["attr_stereotype"] is None
    assert not [x for x in session.working.records("t_xref") if x.values["attr_client"] == guid]


def test_undo_create_element(nafv4_path, qea_copy, mini_mdg_path):
    session = _open(qea_copy(nafv4_path), catalogues=[mini_mdg_path])
    session.create_element(package="Model::core", name="T1", stereotype="MINI::Thing")
    assert not session.working.same_records(session.original)
    session.undo()
    assert session.working.same_records(session.original)
