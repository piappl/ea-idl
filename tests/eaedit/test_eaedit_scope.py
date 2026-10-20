import pytest

from eacore.backends.sql import load_file
from eacore.changes import ChangeSet, Delete, Insert, Update
from eacore.records import Record, Ref
from eaedit.errors import InvalidOperationError
from eaedit.scope import Scope

A = "{3522A830-8853-4c52-9908-40871435BB3B}"  # message
B = "{B68C47BB-5B85-42e7-8FD5-131C7126DCFB}"  # data, sibling of message


@pytest.fixture
def before(nafv4_path):
    return load_file(nafv4_path)


def _element_in(rs, pkg):
    return next(r for r in rs.records("t_object") if r.values["attr_package_id"] == Ref("t_package", pkg))


def _clone(rec, guid, **values):
    return Record(rec.table, guid, {**rec.values, "attr_ea_guid": guid, **values})


def test_insert_inside_allowed_outside_violates(before):
    scope = Scope([Ref("t_package", A)], "package")
    after = before.copy()
    inside = _clone(_element_in(before, A), "{11111111-0000-0000-0000-000000000001}")
    outside = _clone(_element_in(before, B), "{11111111-0000-0000-0000-000000000002}")
    after.add(inside)
    after.add(outside)
    assert scope.violations(ChangeSet(inserts=[Insert(inside)]), before, after) == []
    problems = scope.violations(ChangeSet(inserts=[Insert(outside)]), before, after)
    assert len(problems) == 1 and "Model::core::data" in problems[0]


def _connector(rs, a, b):
    for c in rs.records("t_connector"):
        s, e = (rs.owner_package(c.values[k]).key for k in ("attr_start_object_id", "attr_end_object_id"))
        if (s, e) == (a, b):
            return c
    raise AssertionError("no connector")


def test_connector_crossing(before):
    conn = _connector(before, A, B)
    changes = ChangeSet(inserts=[Insert(conn)])
    assert Scope([Ref("t_package", A)], "connected").violations(changes, before, before) == []
    assert len(Scope([Ref("t_package", A)], "package").violations(changes, before, before)) == 1
    # neither end inside: violates even when connected
    other = Scope([Ref("t_package", "{885B0071-AB32-44c5-A415-7CFBAFAEAB65}")], "connected")
    assert len(other.violations(changes, before, before)) == 1


def test_move_out_violates(before):
    scope = Scope([Ref("t_package", A)], "package")
    elem = _element_in(before, A)
    after = before.copy()
    after.get("t_object", elem.key).values["attr_package_id"] = Ref("t_package", B)
    old = elem.values["attr_package_id"]
    change = Update("t_object", elem.key, {"attr_package_id": (old, Ref("t_package", B))})
    problems = scope.violations(ChangeSet(updates=[change]), before, after)
    assert problems and all("outside the focus" in p for p in problems)
    # moving into focus from outside also violates (source side)
    back = Scope([Ref("t_package", B)], "package").violations(ChangeSet(updates=[change]), before, after)
    assert back


def test_delete_cascade_owner_from_before(before):
    scope = Scope([Ref("t_package", A)], "package")
    attr = next(r for r in before.records("t_attribute") if _owner_pkg(before, r) == A)
    elem = before.resolve(attr.values["attr_object_id"])
    after = before.copy()
    after.remove("t_attribute", attr.key)
    after.remove("t_object", elem.key)
    changes = ChangeSet(deletes=[Delete("t_attribute", attr.key, attr), Delete("t_object", elem.key, elem)])
    assert scope.violations(changes, before, after) == []
    # record not supplied on the Delete: owners come from `before`, or from extra_before
    bare = ChangeSet(deletes=[Delete("t_attribute", attr.key)])
    assert scope.violations(bare, before, after) == []
    extra = {("t_attribute", attr.key): attr, ("t_object", elem.key): elem}
    assert scope.violations(bare, _without(before, attr, elem), after, extra) == []
    outside = next(r for r in before.records("t_attribute") if _owner_pkg(before, r) == B)
    assert scope.violations(ChangeSet(deletes=[Delete("t_attribute", outside.key, outside)]), before, after)


def _without(before, attr, elem):
    stripped = before.copy()
    stripped.remove("t_attribute", attr.key)
    stripped.remove("t_object", elem.key)
    return stripped


def _owner_pkg(rs, rec):
    ref = rs.owner_package(Ref(rec.table, rec.key))
    return ref.key if ref else None


def test_off_and_empty_focus(before):
    outside = _clone(_element_in(before, B), "{11111111-0000-0000-0000-000000000003}")
    after = before.copy()
    after.add(outside)
    changes = ChangeSet(inserts=[Insert(outside)])
    assert Scope([Ref("t_package", A)], "off").violations(changes, before, after) == []
    assert Scope([], "package").violations(changes, before, after) == []


def test_new_subpackage_inside_focus_allowed(before):
    scope = Scope([Ref("t_package", A)], "package")
    guid = "{22222222-0000-0000-0000-000000000001}"
    parent = before.get("t_package", A)
    pkg = Record("t_package", guid, {**parent.values, "attr_ea_guid": guid, "attr_parent_id": Ref("t_package", A)})
    twin_src = next(r for r in before.records("t_object") if r.values["attr_object_type"] == "Package")
    twin = Record(
        "t_object",
        guid,
        {
            **twin_src.values,
            "attr_ea_guid": guid,
            "attr_package_id": Ref("t_package", A),
            "attr_pdata1": Ref("t_package", guid),
        },
    )
    after = before.copy()
    # EA keys the twin by its GUID as well; t_package and t_object are separate tables, so no clash.
    after.add(pkg)
    after.add(twin)
    assert scope.violations(ChangeSet(inserts=[Insert(pkg), Insert(twin)]), before, after) == []
    assert scope.contains(guid, after) and not scope.contains(guid, before)
    # the same sub-package under an outside parent violates
    pkg2 = Record(
        "t_package", "{22222222-0000-0000-0000-000000000009}", {**pkg.values, "attr_parent_id": Ref("t_package", B)}
    )
    after.add(pkg2)
    assert Scope([Ref("t_package", A)], "package").violations(ChangeSet(inserts=[Insert(pkg2)]), before, after)


def test_unknown_policy():
    with pytest.raises(InvalidOperationError):
        Scope([], "bogus")


CORE = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"
L7 = "{E39189FC-1B6D-4472-8701-39724501EBE3}"


def _move_package(before, key, new_parent):
    """(after, changes) for moving a package and its twin under ``new_parent``."""
    after = before.copy()
    old = before.get("t_package", key).values["attr_parent_id"]
    new = Ref("t_package", new_parent)
    after.get("t_package", key).values["attr_parent_id"] = new
    updates = [Update("t_package", key, {"attr_parent_id": (old, new)})]
    twin = next(r for r in after.records("t_object") if r.values["attr_pdata1"] == Ref("t_package", key))
    old_pkg = twin.values["attr_package_id"]
    twin.values["attr_package_id"] = new
    updates.append(Update("t_object", twin.key, {"attr_package_id": (old_pkg, new)}))
    return after, ChangeSet(updates=updates)


def test_package_move_out_in_and_focus_root(before):
    core = Scope([Ref("t_package", CORE)], "package")
    out, changes = _move_package(before, A, L7)  # message: core -> L7
    assert core.violations(changes, before, out)
    inn, changes = _move_package(before, L7, CORE)  # L7: outside -> core
    assert core.violations(changes, before, inn)
    root = Scope([Ref("t_package", A)], "package")
    under, changes = _move_package(before, A, B)  # the focus root itself
    assert root.violations(changes, before, under)
    # a move wholly inside the focus is fine
    sub = Scope([Ref("t_package", CORE)], "package")
    ok, changes = _move_package(before, A, B)
    assert sub.violations(changes, before, ok) == []


def _xrefs(rs, table):
    for x in rs.records("t_xref"):
        guid = x.values.get("attr_client")
        if isinstance(guid, str) and any(r.table == table for r in rs.by_guid(guid)):
            yield x


def _xref_owned_by(rs, table, pkg):
    return next(x for x in _xrefs(rs, table) if _owner_pkg(rs, x) == pkg)


def test_guid_owned_rows(before):
    scope = Scope([Ref("t_package", A)], "package")
    for table in ("t_object", "t_connector", "t_attribute"):
        by_owner = {}
        for x in _xrefs(before, table):
            owners, _ = scope.owners(x.table, x, before.resolve, before.by_guid)
            by_owner.setdefault(frozenset(owners), x)
        inside = by_owner.get(frozenset({A}))
        outside = next((x for o, x in by_owner.items() if A not in o and o), None)
        for rec, ok in ((inside, True), (outside, False)):
            if rec is None:
                continue
            problems = scope.violations(ChangeSet(inserts=[Insert(rec)]), before, before)
            assert (problems == []) is ok, (table, rec.key, problems)
    pkg_xref = next(x for x in _xrefs(before, "t_package"))
    assert (
        Scope([Ref("t_package", _owner_pkg(before, pkg_xref))], "package").violations(
            ChangeSet(inserts=[Insert(pkg_xref)]), before, before
        )
        == []
    )


def test_connector_children_connected_vs_package(before):
    conn = _connector(before, A, B)
    tag = Record(
        "t_connectortag",
        "{33333333-0000-0000-0000-000000000001}",
        {"attr_elementid": Ref("t_connector", conn.key), "attr_property": "p", "attr_value": "v"},
    )
    xref = Record(
        "t_xref",
        "{33333333-0000-0000-0000-000000000002}",
        {"attr_client": conn.key, "attr_ea_guid": "{33333333-0000-0000-0000-000000000002}"},
    )
    after = before.copy()
    after.add(tag)
    after.add(xref)
    changes = ChangeSet(inserts=[Insert(tag), Insert(xref)])
    assert Scope([Ref("t_package", A)], "connected").violations(changes, before, after) == []
    assert len(Scope([Ref("t_package", A)], "package").violations(changes, before, after)) == 2


def test_guid_owned_cascade_only_in_extra_before(before):
    scope = Scope([Ref("t_package", A)], "package")
    elem = next(
        e
        for e in before.records("t_object")
        if e.values["attr_package_id"] == Ref("t_package", A)
        and any(x.values["attr_client"] == e.key for x in before.records("t_xref"))
    )
    xref = next(x for x in before.records("t_xref") if x.values["attr_client"] == elem.key)
    gone = before.copy()
    gone.remove("t_xref", xref.key)
    gone.remove("t_object", elem.key)
    changes = ChangeSet(deletes=[Delete("t_xref", xref.key, xref)])
    assert scope.violations(changes, gone, gone) != []  # owner unknown: fails closed
    assert scope.violations(changes, gone, gone, {("t_object", elem.key): elem}) == []


def test_delete_owner_resolved_where_it_stood_just_before(before):
    """A cascade delete judges a row's owner by its pre-image in the change, not by the session's start."""
    scope = Scope([Ref("t_package", A)], "package")
    elem = _element_in(before, B)  # outside at the session's start
    attr = next(r for r in before.records("t_attribute") if r.values["attr_object_id"] == Ref("t_object", elem.key))
    moved = Record(elem.table, elem.key, {**elem.values, "attr_package_id": Ref("t_package", A)}, elem.rid)
    after = before.copy()
    after.remove("t_attribute", attr.key)
    after.remove("t_object", elem.key)
    changes = ChangeSet(deletes=[Delete("t_attribute", attr.key, attr), Delete("t_object", elem.key, moved)])
    extra = {("t_attribute", attr.key): attr, ("t_object", elem.key): moved}
    assert scope.violations(changes, before, after, extra) == []


def test_session_delete_after_move_into_new_subpackage(nafv4_path, qea_copy):
    from eaedit import Session

    session = Session.open(qea_copy(nafv4_path), focus=["Model::core::message"], policy="package")
    package = session.create_package(parent="Model::core::message", name="P").guid
    session.move_element(el="Model::core::message::MessageTypeEnum", package=package)
    result = session.delete_attribute(attr="{873D5B47-B4A5-44af-8B7C-F81A9FDF92FE}")  # MessageTypeEnum_MEASUREMENT
    assert result.warnings == []
    session.delete_element(el="Model::core::message::P::MessageTypeEnum")
    session.commit()


def test_session_delete_after_move_in_warns_only_for_rows_outside(nafv4_path, qea_copy):
    from eaedit import Session

    session = Session.open(qea_copy(nafv4_path), focus=["Model::core::message"], policy="advisory")
    session.move_element(el="Model::core::data::Measurement", package="Model::core::message")
    warnings = session.delete_element(el="Model::core::message::Measurement").warnings
    flagged = [w.message for w in warnings if w.code == "scope"]
    # Measurement's own attributes, tags and xrefs stood inside the focus when they were deleted; only rows of
    # connectors crossing to Model::core::data are outside.
    assert flagged
    owned_by_data_only = [m for m in flagged if m.endswith("owned by Model::core::data is outside the focus")]
    assert not [m for m in owned_by_data_only if m.split()[1] in ("t_attribute", "t_objectproperties", "t_xref")]
