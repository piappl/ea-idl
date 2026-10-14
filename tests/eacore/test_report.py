import json

from eacore.backends.sql import load_file
from eacore.changes import ChangeSet, Update
from eacore.report import dump_text, package_path, render_text, to_json
from eacore.records import Record, RecordSet, Ref

CORE = "{753A4DFC-7876-4b00-BB5A-6274AD3817C3}"


def test_owner_package_follows_parents(nafv4_path):
    rs = load_file(nafv4_path)
    attribute = next(rs.records("t_attribute"))
    owner = rs.owner_package(Ref("t_attribute", attribute.key))
    assert owner is not None and owner.table == "t_package"
    xref = next(x for x in rs.records("t_xref") if x.values["attr_type"] == "element property")
    assert rs.owner_package(Ref("t_xref", xref.key)) is not None
    assert rs.owner_package(Ref("t_datatypes", next(rs.records("t_datatypes")).key)) is None
    assert package_path(rs, Ref("t_package", CORE)) == "Model/core"


def test_render_groups_by_package_and_shows_change(nafv4_path):
    rs = load_file(nafv4_path)
    obj = next(o for o in rs.records("t_object") if o.values["attr_object_type"] == "Class")
    cs = ChangeSet(updates=[Update("t_object", obj.key, {"attr_name": (obj.values["attr_name"], "Renamed")})])
    text = render_text(cs, rs, rs)
    assert "== Model/" in text
    assert f"'{obj.values['attr_name']}' -> 'Renamed'" in text
    data = json.loads(to_json(cs))
    assert data["updates"][0]["changes"]["attr_name"] == [obj.values["attr_name"], "Renamed"]


def test_dump_text_is_stable_and_one_line_per_value(nafv4_path):
    first, second = dump_text(load_file(nafv4_path)), dump_text(load_file(nafv4_path))
    assert first == second
    assert all(line.count("\t") >= 3 for line in first.splitlines())


def test_attribute_change_nests_under_class_heading(nafv4_path):
    rs = load_file(nafv4_path)
    attribute = next(a for a in rs.records("t_attribute") if a.values["attr_name"])
    owner = rs.resolve(attribute.values["attr_object_id"])
    cs = ChangeSet(
        updates=[Update("t_attribute", attribute.key, {"attr_name": (attribute.values["attr_name"], "Zed")})]
    )
    lines = render_text(cs, rs, rs).splitlines()
    heading = next(i for i, line in enumerate(lines) if line.startswith("  ") and not line.startswith("    "))
    assert f"{owner.values['attr_name']} ({owner.values['attr_object_type']})" in lines[heading]
    assert lines[heading + 1].startswith("    ~ t_attribute")
    assert lines[heading + 2].startswith("        attr_name: ")


def test_dump_text_is_lossless_for_long_strings_and_bytes():
    def dump(note, blob):
        rs = RecordSet()
        rs.add(Record("t_x", "k", {"attr_note": note, "attr_blob": blob}))
        return dump_text(rs)

    assert dump("a" * 300 + "x", b"\x00\x01") != dump("a" * 300 + "y", b"\x00\x01")
    assert dump("n", b"\x00\x01") != dump("n", b"\x00\x02")
    assert len(dump("l1\nl2", b"").splitlines()) == 2
