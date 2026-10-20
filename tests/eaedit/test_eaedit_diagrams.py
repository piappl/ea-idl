from datetime import datetime

import pytest

from eacore.backends.sql import load_file
from eacore.integrity import check
from eacore.records import Ref
from eaedit import InvalidOperationError, ScopeError, Session
from eaedit.defaults import DIAGRAM_PROPERTIES, defaults_for
from eaedit.resolve import find

FIXED = datetime(2026, 1, 2, 3, 4, 5)
FLEXIBLE = "Model::core::data::flexible"
P2 = "{E140E9F6-5A96-4f95-8B54-191D9EECD399}"


def _open(path, **kwargs):
    kwargs.setdefault("policy", "off")
    return Session.open(path, clock=lambda: FIXED, author="tester", **kwargs)


def _issues(rs):
    return {(i.severity, i.rule, i.ref, i.message) for i in check(rs)}


def test_create_naf_view_diagram(nafv4_path, qea_copy, naf_mdg_path):
    path = qea_copy(nafv4_path)
    baseline = _issues(load_file(nafv4_path))
    session = _open(path, catalogues=[naf_mdg_path])
    result = session.create_diagram("Model::p2", "New P2", "NAFv4-Core::P2")
    assert result.warnings == []
    session.commit()

    rs = load_file(path)
    assert sorted(i for i in _issues(rs) - baseline if i[0] == "error") == []
    row = rs.get("t_diagram", result.guid).values
    mdg = "MDGDgm=NAFv4-Core Physical Resource Specification Viewpoints::P2 - Resource Structure;"
    assert row["attr_diagram_type"] == "Custom" and mdg in row["attr_styleex"]
    assert row["attr_name"] == "New P2" and row["attr_package_id"] == find(rs, "Model::p2")
    assert row["attr_parentid"] == 0
    assert (row["attr_author"], row["attr_createddate"]) == ("tester", "2026-01-02 03:04:05")
    expected = {k: v for k, v in defaults_for("t_diagram", "Custom").values.items() if k != "attr_styleex"}
    assert {k: row[k] for k in expected} == expected
    assert row["attr_styleex"].replace(mdg, "") == defaults_for("t_diagram", "Custom").values["attr_styleex"]
    assert find(rs, "Model::p2::New P2", kinds=("diagram",)) == Ref("t_diagram", result.guid)


def test_create_unverified_view_warns(nafv4_path, qea_copy, naf_mdg_path):
    session = _open(qea_copy(nafv4_path), catalogues=[naf_mdg_path])
    result = session.create_diagram("Model::p2", "New P1", "NAFv4-Core::P1")
    assert "unverified-default" in {w.code for w in result.warnings}


def test_create_uml_diagram_warns(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    result = session.create_diagram("Model::p2", "Classes")
    assert "unverified-default" in {w.code for w in result.warnings}
    assert session.working.get("t_diagram", result.guid).values["attr_diagram_type"] == "Class"


def test_create_diagram_needs_a_name(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    with pytest.raises(InvalidOperationError):
        session.create_diagram("Model::p2", "")


def test_create_element_owned_diagram(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    owner = find(session.working, "Model::core::message::Message")
    package = session.working.resolve(owner).values["attr_package_id"]
    guid = session.create_diagram("Model::core::message::Message", "Inside", "Custom").guid
    row = session.working.get("t_diagram", guid).values
    assert row["attr_parentid"] == owner and row["attr_package_id"] == package
    assert row["attr_diagram_type"] == "Custom"

    session.delete_element("Model::core::message::Message")
    assert session.working.get("t_diagram", guid) is None

    scoped = _open(qea_copy(nafv4_path, "scoped.qea"), focus=["Model::p2"], policy="package")
    with pytest.raises(ScopeError):
        scoped.create_diagram("Model::core::message::Message", "Inside", "Custom")


def test_diagram_name_taken_in_package_refused(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    flexible = "{95DEF889-09FC-4a48-8F89-006A14B4402D}"
    with pytest.raises(InvalidOperationError, match=f"'flexible'.*{flexible}"):
        session.create_diagram("Model::core::data", "flexible")
    # an element's diagram is found by its package's name too, so it cannot reuse a name there either
    with pytest.raises(InvalidOperationError, match="'message'"):
        session.create_diagram("Model::core::message::Message", "message")
    with pytest.raises(InvalidOperationError, match=f"'flexible'.*{flexible}"):
        session.update_diagram("Model::core::data::measurement", name="flexible")
    assert session.log == []
    # the same name in another package, and a diagram keeping its own name, are fine
    session.create_diagram("Model::core::message", "flexible")
    session.update_diagram(FLEXIBLE, name="flexible", notes="kept")


def test_update_and_delete_diagram(nafv4_path, qea_copy):
    path = qea_copy(nafv4_path)
    session = _open(path)
    session.update_diagram(FLEXIBLE, name="Flex", notes="n", page_width=900, page_height=1200, orientation="L")
    row = session.working.resolve(find(session.working, "Model::core::data::Flex", kinds=("diagram",))).values
    assert (row["attr_notes"], row["attr_cx"], row["attr_cy"], row["attr_orientation"]) == ("n", 900, 1200, "L")
    assert row["attr_modifieddate"] == "2026-01-02 03:04:05"
    with pytest.raises(InvalidOperationError):
        session.update_diagram("Model::core::data::Flex", orientation="X")
    with pytest.raises(InvalidOperationError):
        session.update_diagram("Model::core::data::Flex", colour="red")


@pytest.mark.parametrize(
    "name, has_notes",
    [(FLEXIBLE, False), ("Model::core::data::measurement", True), ("Model::p6::p6", True)],
)
def test_delete_diagram(nafv4_path, qea_copy, name, has_notes):
    path = qea_copy(nafv4_path)
    before = load_file(nafv4_path)
    session = _open(path)
    diagram = find(before, name, kinds=("diagram",))
    objects = [r for r in before.records("t_diagramobjects") if r.values["attr_diagram_id"] == diagram]
    assert objects
    on_it = {r.values["attr_object_id"] for r in objects}
    elsewhere = {
        r.values["attr_object_id"] for r in before.records("t_diagramobjects") if r.values["attr_diagram_id"] != diagram
    }
    notes = {o for o in on_it - elsewhere if before.resolve(o).values["attr_object_type"] == "Note"}
    assert bool(notes) == has_notes
    session.delete_diagram(name)
    session.commit()

    after = load_file(path)
    assert after.get("t_diagram", diagram.key) is None
    assert not [r for r in after.records("t_diagramobjects") if r.values["attr_diagram_id"] == diagram]
    assert not [r for r in after.records("t_diagramlinks") if r.values["attr_diagramid"] == diagram]
    gone = {(r.table, r.key) for r in before.records("t_object") if after.get("t_object", r.key) is None}
    assert gone == {("t_object", n.key) for n in notes}
    lost = {r.key for r in before.records("t_connector") if after.get("t_connector", r.key) is None}
    note_links = {
        r.key
        for r in before.records("t_connector")
        if r.values["attr_connector_type"] == "NoteLink"
        and {r.values["attr_start_object_id"], r.values["attr_end_object_id"]} & notes
    }
    assert lost == note_links
    # every other diagram keeps its objects
    kept = [r for r in before.records("t_diagramobjects") if r.values["attr_diagram_id"] != diagram]
    assert all(after.get("t_diagramobjects", r.key) is not None for r in kept)


def _properties(rs, guid):
    return [x for x in rs.records("t_xref") if x.values["attr_client"] == guid]


def test_diagram_properties_row_created_and_deleted(nafv4_path, qea_copy):
    before = load_file(nafv4_path)
    session = _open(qea_copy(nafv4_path))
    guid = session.create_diagram("Model::p2", "Props", "Custom").guid
    (row,) = _properties(session.working, guid)
    (hand,) = _properties(before, P2)
    skip = {"attr_xrefid", "attr_description", "attr_client"}
    assert {k: v for k, v in row.values.items() if k not in skip} == {
        k: v for k, v in hand.values.items() if k not in skip
    }
    assert row.values["attr_description"] == DIAGRAM_PROPERTIES
    session.delete_diagram(guid)
    assert _properties(session.working, guid) == []
