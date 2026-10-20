from datetime import datetime
from pathlib import Path

import pytest
import yaml

from eacore.report import to_json
from eaedit import InvalidOperationError, LoggedOp, Session
from eaedit.changefile import load, replay, save

FIXED = datetime(2026, 1, 2, 3, 4, 5)
PKG = "Model::core::message::Gadgets"
THING = f"{PKG}::Thing1"


def _build(session):
    session.create_package(parent="Model::core::message", name="Gadgets")
    session.create_element(package=PKG, name="Thing1", stereotype="MINI::Thing")
    session.add_attribute(el=THING, name="size", type="int")
    session.connect(source=THING, target="Model::core::message::Message", type="Dependency")
    session.set_tag(target=THING, name="kind", value="b")
    session.set_tag(target=THING, name="extra", value="x")  # a new tag row: an op without a guid parameter


def test_replay_reproduces_changeset(nafv4_path, qea_copy, mini_mdg_path, tmp_path):
    # the real clock: `at` loses its microseconds in the file, which every stored timestamp drops too
    first = Session.open(qea_copy(nafv4_path, "a.qea"), catalogues=[mini_mdg_path], author="tester")
    _build(first)
    changes_file = tmp_path / "changes.yaml"
    save(first, changes_file)

    second = Session.open(qea_copy(nafv4_path, "b.qea"), catalogues=[mini_mdg_path], author="someone else")
    results = replay(second, changes_file)

    assert len(results) == len(first.log) == 6
    # set_tag takes no guid: its tag row's GUID is logged in `created` only, and replay queues it
    new_tag = first.log[-1]
    assert new_tag.name == "set_tag" and "guid" not in new_tag.args and len(new_tag.created) == 1
    assert [r.guid for r in results][:2] == [first.log[0].args["guid"], first.log[1].args["guid"]]
    expected = to_json(first.changes())
    assert expected != to_json(Session.open(qea_copy(nafv4_path, "c.qea")).changes())
    assert to_json(second.changes()) == expected
    assert [op.name for op in second.log] == [op.name for op in first.log]


def test_changefile_roundtrip_yaml(nafv4_path, qea_copy, mini_mdg_path, tmp_path):
    session = Session.open(qea_copy(nafv4_path), catalogues=[mini_mdg_path], author="tester", clock=lambda: FIXED)
    _build(session)
    out = tmp_path / "changes.yaml"
    save(session, out)

    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert raw["eaedit"] == 1 and raw["author"] == "tester" and raw["source"] == "copy.qea"
    first = raw["ops"][0]
    assert first["op"] == "create_package" and first["at"] == "2026-01-02 03:04:05"
    assert first["args"]["name"] == "Gadgets" and first["created"] == session.log[0].created

    assert load(out) == session.log
    assert all(isinstance(op, LoggedOp) for op in load(out))


def test_replay_accepts_ops_and_fixes_the_clock(nafv4_path, qea_copy):
    session = Session.open(qea_copy(nafv4_path))
    at = datetime(2020, 5, 6, 7, 8, 9)
    op = LoggedOp("create_element", {"package": "Model::core::message", "name": "Old"}, at)
    [result] = replay(session, [op])
    created = session.working.get("t_object", result.guid)
    assert created.values["attr_createddate"] == "2020-05-06 07:08:09"
    assert session.log[0].at == at
    assert session.clock is not None and session.clock() != at  # restored afterwards


def test_replay_author_override(nafv4_path, qea_copy, tmp_path):
    first = Session.open(qea_copy(nafv4_path, "a.qea"), author="writer")
    first.create_element(package="Model::core::message", name="Authored")
    changes_file = tmp_path / "changes.yaml"
    save(first, changes_file)

    def author_of(session, result):
        return session.working.get("t_object", result.guid).values["attr_author"]

    second = Session.open(qea_copy(nafv4_path, "b.qea"), author="reader")
    [result] = replay(second, changes_file)
    assert author_of(second, result) == "writer" and second.author == "reader"
    third = Session.open(qea_copy(nafv4_path, "c.qea"), author="reader")
    [result] = replay(third, changes_file, author="reviewer")
    assert author_of(third, result) == "reviewer" and third.author == "reader"


def test_replay_reports_the_failing_operation(nafv4_path, qea_copy, tmp_path):
    session = Session.open(qea_copy(nafv4_path))
    ops = [
        LoggedOp("create_element", {"package": "Model::core::message", "name": "Fine"}, FIXED),
        # a misspelt argument: no operation would accept it
        LoggedOp("set_tag", {"target": "Model::core::message::Message", "name": "n", "value": "1", "bogus": 1}, FIXED),
    ]
    with pytest.raises(InvalidOperationError, match="bogus") as info:
        replay(session, ops)
    assert any("operation 2" in note for note in getattr(info.value, "__notes__", []))


def test_load_rejects_unknown_format(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("eaedit: 2\nops: []\n", encoding="utf-8")
    with pytest.raises(InvalidOperationError, match="version"):
        load(bad)


def test_example_change_file_applies_to_empty_model(empty_path, qea_copy):
    examples = Path(__file__).parents[2] / "docs" / "examples"
    model = qea_copy(empty_path)
    session = Session.open(model, catalogues=[examples / "eaedit-catalogue.yaml"], policy="package", focus=["Model"])
    replay(session, examples / "eaedit-example.yaml")

    assert not session.warnings
    assert [i for i in session.preview().new_issues if i.severity == "error"] == []
    session.commit()
    reopened = Session.open(model)
    assert reopened.get("Model::Demo::Engine")["stereotypes"]
    assert len(reopened.find_connectors(source="Model::Demo::Controller")) == 1


EXAMPLES = Path(__file__).parents[2] / "docs" / "examples"


def _diagram_rows(model):
    session = Session.open(model)
    return [
        sorted(
            (r.table, str(r.key), sorted((k, str(v)) for k, v in r.values.items())) for r in session.working.records(t)
        )
        for t in ("t_diagram", "t_diagramobjects", "t_diagramlinks")
    ]


def test_example_diagram_change_file_applies(empty_path, qea_copy):
    model = qea_copy(empty_path)
    session = Session.open(model, policy="package", focus=["Model"])
    replay(session, EXAMPLES / "eaedit-diagram.yaml")

    # A Class diagram has no hand-made sample in nafv4.qea, so this one warning is expected.
    assert [w.code for w in session.warnings] == ["unverified-default"]
    assert [i for i in session.preview().new_issues if i.severity == "error"] == []
    session.commit()
    reopened = Session.open(model)
    diagram = reopened.find("Model::Shapes::Overview", kinds=("diagram",))
    assert diagram is not None
    assert len(list(reopened.working.records("t_diagramobjects"))) == 3  # two classes and the note


def test_replay_diagram_ops_identical(empty_path, qea_copy, tmp_path):
    first = qea_copy(empty_path, "one.qea")
    second = qea_copy(empty_path, "two.qea")
    for model in (first, second):
        s = Session.open(model, policy="package", focus=["Model"])
        replay(s, EXAMPLES / "eaedit-diagram.yaml")
        s.commit()
    assert _diagram_rows(first) == _diagram_rows(second)
    assert any("DUID=" in str(rows) for rows in _diagram_rows(first)[1])

    # The session that ran the ops and a replay of its change file write the same rows, DUIDs included.
    original = qea_copy(empty_path, "original.qea")
    session = Session.open(original, policy="off", clock=lambda: FIXED, author="tester")
    session.create_package(parent="Model", name="Shapes")
    shape = session.create_element(package="Model::Shapes", name="Shape", type="Class").guid
    circle = session.create_element(package="Model::Shapes", name="Circle", type="Class").guid
    link = session.connect(source=circle, target=shape, type="Generalization").guid
    diagram = session.create_diagram("Model::Shapes", "Overview", "Class").guid
    session.layout(diagram, {"pattern": "layers", "rows": [[shape], [circle]]})
    note = session.add_note(diagram, "a note", rect=[300, 40, 480, 100]).guid
    session.link_note(note, circle)
    session.set_bounds(diagram, circle, rect=[40, 200, 160, 280])
    session.set_stacking(diagram, shape, 3)
    session.hide_connector(diagram, link)
    session.update_diagram(diagram, name="Shapes overview")
    changes_file = tmp_path / "diagram.yaml"
    save(session, changes_file)
    session.commit()
    replayed = qea_copy(empty_path, "replayed.qea")
    again = Session.open(replayed, policy="off", clock=lambda: FIXED, author="tester")
    replay(again, changes_file)
    again.commit()
    assert _diagram_rows(original) == _diagram_rows(replayed)
    assert len(_diagram_rows(original)[1]) == 3
