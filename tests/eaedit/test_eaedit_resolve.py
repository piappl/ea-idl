import sqlite3
import uuid

import pytest

from eacore.backends.sql import load_file
from eacore.records import Ref
from eaedit.errors import AmbiguousNameError, EditWarning, NotFoundError
from eaedit.resolve import find, qualified_name


@pytest.fixture
def rs(nafv4_path):
    return load_file(nafv4_path)


def test_qualified_name_roundtrip(rs):
    checked = 0
    for rec in rs.records("t_object"):
        if rec.values["attr_object_type"] != "Class":
            continue
        ref = Ref("t_object", rec.key)
        try:
            found = find(rs, qualified_name(rs, ref), kinds=("element",))
        except AmbiguousNameError:
            continue
        assert found == ref
        checked += 1
    assert checked >= 10


def test_find_by_guid_case_insensitive(rs):
    rec = next(rs.records("t_object"))
    guid = rec.values["attr_ea_guid"]
    assert find(rs, guid.lower(), kinds=("element",)) == Ref("t_object", rec.key)
    assert find(rs, guid.upper(), kinds=("element",)) == Ref("t_object", rec.key)


def test_package_guid_resolves_to_t_package(rs):
    guid = "{3522A830-8853-4c52-9908-40871435BB3B}"
    assert find(rs, guid) == Ref("t_package", guid)
    assert qualified_name(rs, Ref("t_package", guid)) == "Model::core::message"
    assert find(rs, "Model::core::message") == Ref("t_package", guid)


def test_attribute_qualified_name(rs):
    attr = next(rs.records("t_attribute"))
    ref = Ref("t_attribute", attr.key)
    name = qualified_name(rs, ref)
    owner = rs.resolve(attr.values["attr_object_id"])
    assert name == f"{qualified_name(rs, Ref('t_object', owner.key))}.{attr.values['attr_name']}"
    assert find(rs, name, kinds=("attribute",)) == ref


def test_not_found(rs):
    with pytest.raises(NotFoundError):
        find(rs, "Model::nope")
    with pytest.raises(NotFoundError):
        find(rs, "{00000000-0000-0000-0000-000000000000}")


def test_resolve_duplicate_names_is_ambiguous(qea_copy, nafv4_path):
    path = qea_copy(nafv4_path)
    con = sqlite3.connect(path)
    row = con.execute("select * from t_object where Object_Type='Class' limit 1").fetchone()
    cols = [d[0] for d in con.execute("select * from t_object limit 1").description]
    data = dict(zip(cols, row))
    data.pop("Object_ID")
    data["ea_guid"] = "{" + str(uuid.uuid4()).upper() + "}"
    con.execute(f"insert into t_object ({','.join(data)}) values ({','.join('?' * len(data))})", list(data.values()))
    con.commit()
    con.close()
    dup = load_file(path)
    original = next(r for r in dup.records("t_object") if r.values["attr_ea_guid"] == row[cols.index("ea_guid")])
    name = qualified_name(dup, Ref("t_object", original.key))
    with pytest.raises(AmbiguousNameError) as exc:
        find(dup, name, kinds=("element",))
    assert len(exc.value.candidates) == 2
    assert exc.value.candidates == sorted(exc.value.candidates)


def test_edit_warning_str():
    assert str(EditWarning("c", "msg")) == "c: msg"
    assert str(EditWarning("c", "msg", "T", "mdg")) == "c: msg [T] (mdg)"
