from datetime import datetime

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
