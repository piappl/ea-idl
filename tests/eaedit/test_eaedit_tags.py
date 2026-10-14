from datetime import datetime

import pytest

from eacore.backends.sql import load_file
from eacore.integrity import check
from eacore.records import Ref
from eaedit import InvalidOperationError, NotFoundError, Session

FIXED = datetime(2026, 1, 2, 3, 4, 5)
MESSAGE = "{308FD88F-3514-4a20-942B-5CF2F35B042F}"  # Message class: DataElement, idlStruct
HEADER = "{93ADE616-99F2-43fe-9EA2-581497C0235C}"  # Message.header attribute
ABSTRACTION = "{F610F724-B54B-493b-B763-ED4BD6079B71}"  # Abstraction from Message, carries tag URI
CORE = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"  # Model::core


def _open(path, **kwargs):
    return Session.open(path, policy="off", clock=lambda: FIXED, author="tester", **kwargs)


def _rows(rs, table, column, owner, name):
    return [t for t in rs.records(table) if t.values[column] == owner and t.values["attr_property"] == name]


TARGETS = [
    (MESSAGE, "t_objectproperties", "attr_object_id", Ref("t_object", MESSAGE)),
    (HEADER, "t_attributetag", "attr_elementid", Ref("t_attribute", HEADER)),
    (ABSTRACTION, "t_connectortag", "attr_elementid", Ref("t_connector", ABSTRACTION)),
    # A package's tags sit on its t_object twin.
    ("Model::core", "t_objectproperties", "attr_object_id", Ref("t_object", CORE)),
]


@pytest.mark.parametrize(("target", "table", "column", "owner"), TARGETS)
def test_set_tag_on_element_attribute_connector_package(nafv4_path, qea_copy, target, table, column, owner):
    path = qea_copy(nafv4_path)
    baseline = {(i.severity, i.rule, i.ref, i.message) for i in check(load_file(nafv4_path))}
    session = _open(path, infer=False)
    assert session.set_tag(target=target, name="fresh", value="v1", notes="n").guid == owner.key
    [row] = _rows(session.working, table, column, owner, "fresh")
    assert (row.values["attr_value"], row.values["attr_notes"]) == ("v1", "n")
    session.set_tag(target=target, name="fresh", value="v2")
    [again] = _rows(session.working, table, column, owner, "fresh")
    assert again.key == row.key and (again.values["attr_value"], again.values["attr_notes"]) == ("v2", "n")
    session.commit()

    rs = load_file(path)
    [saved] = _rows(rs, table, column, owner, "fresh")
    assert saved.values["attr_value"] == "v2"
    new = {(i.severity, i.rule, i.ref, i.message) for i in check(rs)} - baseline
    assert [i for i in new if i[0] == "error"] == []


def test_set_tag_updates_existing_and_warns_unknown(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    owner = Ref("t_connector", ABSTRACTION)
    [before] = _rows(session.working, "t_connectortag", "attr_elementid", owner, "URI")
    result = session.set_tag(target=ABSTRACTION, name="URI", value="http://x")
    assert result.warnings == []
    [after] = _rows(session.working, "t_connectortag", "attr_elementid", owner, "URI")
    assert after.key == before.key and after.values["attr_value"] == "http://x"

    # The inferred catalogue gives Message's stereotypes their tags; 'colour' is none of them.
    assert [w.code for w in session.set_tag(target=MESSAGE, name="colour", value="red").warnings] == ["unknown-tag"]
    assert session.set_tag(target=MESSAGE, name="URI", value="u").warnings == []


def test_delete_tag_missing_raises(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    owner = Ref("t_object", MESSAGE)
    session.set_tag(target=MESSAGE, name="dup", value="1")
    with pytest.raises(NotFoundError, match="dup2"):
        session.delete_tag(target=MESSAGE, name="dup2")
    assert session.delete_tag(target=MESSAGE, name="URI").guid == MESSAGE
    assert _rows(session.working, "t_objectproperties", "attr_object_id", owner, "URI") == []
    session.delete_tag(target=MESSAGE, name="dup")
    with pytest.raises(NotFoundError):
        session.delete_tag(target=MESSAGE, name="dup")


def test_delete_tag_removes_every_duplicate(nafv4_path, qea_copy):
    from eaedit.defaults import new_record
    from eaedit.ops import OPERATIONS

    session = _open(qea_copy(nafv4_path))
    owner = Ref("t_object", MESSAGE)

    def two_rows(s):
        for value in ("a", "b"):
            values = {"attr_object_id": owner, "attr_property": "twice", "attr_value": value}
            s.put(new_record(s, "t_objectproperties", values))

    OPERATIONS["_test_two_rows"] = two_rows
    try:
        session.run("_test_two_rows")
    finally:
        OPERATIONS.pop("_test_two_rows")
    assert len(_rows(session.working, "t_objectproperties", "attr_object_id", owner, "twice")) == 2
    session.delete_tag(target=MESSAGE, name="twice")
    assert _rows(session.working, "t_objectproperties", "attr_object_id", owner, "twice") == []


def test_set_tag_rejects_other_targets(nafv4_path, qea_copy):
    session = _open(qea_copy(nafv4_path))
    with pytest.raises(NotFoundError):
        session.set_tag(target="Model::nothing", name="x", value="1")
    with pytest.raises(InvalidOperationError):
        session.set_tag(target=MESSAGE, name="", value="1")
