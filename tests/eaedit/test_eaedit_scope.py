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
    assert scope.violations(bare, load_file_empty(before, attr, elem), after, extra) == []
    outside = next(r for r in before.records("t_attribute") if _owner_pkg(before, r) == B)
    assert scope.violations(ChangeSet(deletes=[Delete("t_attribute", outside.key, outside)]), before, after)


def load_file_empty(before, attr, elem):
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
        "{22222222-0000-0000-0000-000000000002}",
        {
            **twin_src.values,
            "attr_ea_guid": guid,
            "attr_package_id": Ref("t_package", A),
            "attr_pdata1": Ref("t_package", guid),
        },
    )
    after = before.copy()
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
