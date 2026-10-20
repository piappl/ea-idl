import sqlite3
from datetime import datetime

import pytest

from eacore.backends.sql import load_file
from eacore.catalogue import Catalogue, Source, StereotypeDef, TagDef
from eacore.integrity import check
from eacore.records import Ref
from eaedit import InvalidOperationError, NotFoundError, ScopeError, Session
from eaedit.ops.common import stereotype_names
from eaedit.ops.elements import PART_PROPERTIES
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


def test_move_package_sets_modified_on_twin_only(nafv4_path, qea_copy):
    # EA 16.1 changes only the t_object twin's ModifiedDate when a package is dragged to another parent.
    session = _open(qea_copy(nafv4_path))
    p2 = find(session.working, "Model::p2").key
    before = session.working.get("t_package", p2).values["attr_modifieddate"]
    session.move_package(pkg=p2, new_parent="Model::core")
    assert session.working.get("t_object", p2).values["attr_modifieddate"] == "2026-01-02 03:04:05"
    assert session.working.get("t_package", p2).values["attr_modifieddate"] == before


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


def _stereo_description(rs, guid):
    [xref] = [
        x for x in rs.records("t_xref") if x.values["attr_name"] == "Stereotypes" and x.values["attr_client"] == guid
    ]
    return xref.values["attr_description"]


INTERFACE = "{8693AE90-C279-4519-AC3B-E77DD1076F13}"  # t_stereotypes 'interface' applying to 'class'


def test_unknown_profile_stereotypes_are_written_as_ea_does(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)  # infer=True: the model's FQName-less stereotypes land in the "(unknown)" profile
    # EA names a stereotype without a profile by its t_stereotypes row's GUID ...
    interface = session.create_element(package="Model::core", name="I", stereotype="interface")
    assert interface.warnings == []
    assert (
        _stereo_description(session.working, interface.guid) == f"@STEREO;Name=interface;GUID={INTERFACE};@ENDSTEREO;"
    )
    # ... and by its name alone when there is no such row (EA's own 'collapse' entries in nafv4.qea).
    collapse = session.create_element(package="Model::core", name="C", stereotype="(unknown)::collapse").guid
    assert _stereo_description(session.working, collapse) == "@STEREO;Name=collapse;@ENDSTEREO;"
    # A list rewritten for another stereotype keeps the GUID entries it had.
    session.add_stereotype(target=interface.guid, name="collapse")
    assert _stereo_description(session.working, interface.guid) == (
        f"@STEREO;Name=interface;GUID={INTERFACE};@ENDSTEREO;@STEREO;Name=collapse;@ENDSTEREO;"
    )
    session.commit()
    rs = load_file(path)
    assert _errors(rs, baseline) == []
    assert "(unknown)" not in "".join(x.values["attr_description"] or "" for x in rs.records("t_xref"))


def test_bare_name_prefers_named_profile_over_inferred_unknown(nafv4_path, qea_copy):
    idl = Catalogue(profile="IDL", source=Source(kind="eaidl"), stereotypes=[StereotypeDef(name="idlStruct")])
    session = _open(qea_copy(nafv4_path), catalogues=[idl])
    result = session.create_element(package="Model::core", name="S", stereotype="idlStruct")
    assert result.warnings == []
    assert (
        _stereo_description(session.working, result.guid) == "@STEREO;Name=idlStruct;FQName=IDL::idlStruct;@ENDSTEREO;"
    )


def test_apply_stereotype_with_ambiguous_ancestor_warns(nafv4_path, qea_copy):
    child = StereotypeDef(name="S", applies_to=["Class"], generalizes=["B"], tags=[TagDef(name="own")])
    catalogues = [
        Catalogue(profile="P", source=Source(kind="yaml"), stereotypes=[child]),
        Catalogue(profile="Q", source=Source(kind="yaml"), stereotypes=[StereotypeDef(name="B")]),
        Catalogue(profile="R", source=Source(kind="yaml"), stereotypes=[StereotypeDef(name="B")]),
    ]
    session = _open(qea_copy(nafv4_path), catalogues=catalogues, infer=False)
    result = session.create_element(package="Model::core", name="X", stereotype="P::S", type="Class")
    assert [w.code for w in result.warnings] == ["ambiguous-stereotype"]
    assert stereotype_names(session, session.working.get("t_object", result.guid)) == [("S", "P::S")]
    assert _tags(session.working, result.guid) == {}


ASSET1 = "Model::p2::ResourceArchitecture::Asset1"  # a Part nested under ResourceArchitecture (ParentID)


def test_move_nested_element_unnests_it(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    guid = find(session.working, ASSET1).key
    result = session.move_element(el=ASSET1, package="Model::core")
    assert [w.code for w in result.warnings] == ["unnested"]
    values = session.working.get("t_object", guid).values
    assert (values["attr_package_id"], values["attr_parentid"]) == (find(session.working, "Model::core"), 0)
    # Moved to the package its owner is in, a nested element stays nested.
    asset2 = "Model::p2::ResourceArchitecture::Asset2"
    nested = session.working.get("t_object", find(session.working, asset2).key).values["attr_parentid"]
    assert session.move_element(el=asset2, package="Model::p2").warnings == []
    assert session.working.get("t_object", find(session.working, asset2).key).values["attr_parentid"] == nested
    session.commit()
    rs = load_file(path)
    assert _errors(rs, baseline) == []
    assert find(rs, "Model::core::Asset1") == Ref("t_object", guid)


def test_move_element_moves_diagrams_it_owns(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    with sqlite3.connect(path) as db:
        owner, package = db.execute(
            "select Object_ID, Package_ID from t_object where Name='ResourceArchitecture'"
        ).fetchone()
        columns = [r[1] for r in db.execute("pragma table_info(t_diagram)") if r[1] != "Diagram_ID"]
        row = dict(zip(columns, db.execute(f"select {', '.join(columns)} from t_diagram limit 1").fetchone()))
        row.update(ParentID=owner, Package_ID=package, Name="Owned", ea_guid="{22222222-0000-0000-0000-000000000001}")
        db.execute(f"insert into t_diagram ({', '.join(row)}) values ({', '.join('?' * len(row))})", list(row.values()))
    baseline = _issues(load_file(path))
    session = _open(path)
    result = session.move_element(el="Model::p2::ResourceArchitecture", package="Model::core")
    assert "unnested" not in [w.code for w in result.warnings]  # its nested parts move with it
    diagram = session.working.get("t_diagram", "{22222222-0000-0000-0000-000000000001}").values
    assert diagram["attr_package_id"] == find(session.working, "Model::core")
    session.commit()
    assert _errors(load_file(path), baseline) == []


def test_create_element_without_parent_writes_no_parent_value(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    part = session.create_element(package="Model::core", name="P", type="Part").guid
    session.commit()
    assert load_file(path).get("t_object", part).values["attr_parentid"] == 0


def _insert_details(path):
    with sqlite3.connect(path) as db:
        oid = db.execute("select Object_ID from t_object where ea_guid = ?", (MESSAGE,)).fetchone()[0]
        attribute_id, attribute_guid = db.execute(
            "select ID, ea_guid from t_attribute where Object_ID = ? order by Pos limit 1", (oid,)
        ).fetchone()
        connector_id, connector_guid = db.execute(
            "select Connector_ID, ea_guid from t_connector where Start_Object_ID = ? limit 1", (oid,)
        ).fetchone()
        db.execute(
            "insert into t_objectrequires (Object_ID, Requirement, ReqType) values (?, 'R1', 'Functional')", (oid,)
        )
        db.execute(
            "insert into t_objectscenarios (Object_ID, Scenario, ea_guid) values (?, 'S1', ?)",
            (oid, "{22222222-0000-0000-0000-000000000002}"),
        )
        db.execute("insert into t_objectfiles (Object_ID, FileName) values (?, 'f.txt')", (oid,))
        db.execute("insert into t_method (Object_ID, Name) values (?, 'm')", (oid,))
        db.execute(
            "insert into t_attributeconstraints (Object_ID, \"Constraint\", AttName, ID) values (?, 'c', 'a', ?)",
            (oid, attribute_id),
        )
        db.execute("insert into t_connectorconstraint (ConnectorID, \"Constraint\") values (?, 'cc')", (connector_id,))
        db.execute(
            'insert into t_roleconstraint (ConnectorID, "Constraint", ConnectorEnd, ConstraintType) '
            "values (?, 'rc', 'Source', 'Pre')",
            (connector_id,),
        )
    return attribute_guid, connector_guid


#: Detail tables of elements, attributes and connectors that a delete must not leave orphaned.
DETAIL_TABLES = (
    "t_objectrequires",
    "t_objectscenarios",
    "t_objectfiles",
    "t_method",
    "t_attributeconstraints",
    "t_connectorconstraint",
    "t_roleconstraint",
)


def _counts(path):
    with sqlite3.connect(path) as db:
        return {t: db.execute(f"select count(*) from {t}").fetchone()[0] for t in DETAIL_TABLES}


def test_delete_element_removes_detail_rows(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    _insert_details(path)
    rs = load_file(path)
    assert [i for i in rs.issues if i.table in DETAIL_TABLES] == []
    assert len(list(rs.records("t_objectrequires"))) == 1
    baseline = _issues(rs)
    session = _open(path)
    session.delete_element(el=MESSAGE)
    session.commit()
    assert _counts(path) == dict.fromkeys(DETAIL_TABLES, 0)
    assert _errors(load_file(path), baseline) == []


def test_delete_attribute_and_connector_remove_their_constraints(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    attribute, connector = _insert_details(path)
    baseline = _issues(load_file(path))
    session = _open(path)
    session.delete_attribute(attr=attribute)
    session.delete_connector(conn=connector)
    session.commit()
    counts = _counts(path)
    assert (counts["t_attributeconstraints"], counts["t_connectorconstraint"], counts["t_roleconstraint"]) == (0, 0, 0)
    assert counts["t_objectrequires"] == 1
    assert _errors(load_file(path), baseline) == []


def test_real_operations_take_positional_arguments(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    guid = session.create_element("Model::core", "Pos").guid
    session.update_element(guid, alias="A")  # **fields are flattened into the logged arguments
    assert session.log[-1].args == {"el": guid, "alias": "A"}
    session.delete_element(guid)
    assert session.log[-1].args == {"el": guid}
    assert session.working.get("t_object", guid) is None


def test_new_free_text_stereotype_is_registered(nafv4_path, qea_copy):
    # EA 16.1 adds a stereotype new to the model to t_stereotypes and refers to it by GUID.
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = Session.open(path, focus=["Model::core"], policy="package", clock=lambda: FIXED, author="tester")
    guid = session.create_element(package="Model::core", name="F", stereotype="brandNew").guid
    row = session.working.get("t_stereotypes", ("brandNew", "Class"))
    assert row is not None and row.values["attr_description"] == "brandNew"
    stereo = row.values["attr_ea_guid"]
    assert _stereo_description(session.working, guid) == f"@STEREO;Name=brandNew;GUID={stereo};@ENDSTEREO;"
    # Applying it again reuses the row; the repository-wide row is allowed under a package focus.
    other = session.create_element(package="Model::core", name="G", stereotype="brandNew").guid
    assert _stereo_description(session.working, other) == f"@STEREO;Name=brandNew;GUID={stereo};@ENDSTEREO;"
    session.commit()
    assert _errors(load_file(path), baseline) == []


def test_part_has_custom_properties_and_classifier_guid(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path)
    owner = session.create_element(package="Model::core", name="Whole").guid
    typ = session.create_element(package="Model::core", name="Kind").guid
    part = session.create_element(parent=owner, name="p", type="Part").guid
    props = [x for x in session.working.records("t_xref") if x.values["attr_client"] == part]
    assert [(x.values["attr_name"], x.values["attr_description"], x.values["attr_supplier"]) for x in props] == [
        ("CustomProperties", PART_PROPERTIES, "<none>")
    ]
    session.set_classifier(part, typ)
    assert session.working.get("t_object", part).values["attr_classifier_guid"] == typ
    session.set_classifier(part, None)
    assert session.working.get("t_object", part).values["attr_classifier_guid"] is None
    session.delete_element(part)
    assert not [x for x in session.working.records("t_xref") if x.values["attr_client"] == part]
    session.commit()
    assert _errors(load_file(path), baseline) == []
