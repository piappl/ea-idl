import shutil

import pytest
import yaml

from eacore.backends.sql import load_file
from eaedit.errors import EaeditError
from eaedit.mcp.workspace import Config, Workspace

CORE = "Model::core"
MSG = "Model::core::message"


def _make(qea_copy, nafv4_path, tmp_path):
    path = qea_copy(nafv4_path)
    return path, Config(path, focus=[CORE], out_dir=tmp_path / "out")


def _create(ws, name):
    return ws.run("create_element", {"package": MSG, "name": name})


def test_snapshot_reloads_when_file_changes(qea_copy, nafv4_path, empty_path, tmp_path):
    path, config = _make(qea_copy, nafv4_path, tmp_path)
    ws = Workspace(config)
    assert ws.snapshot().find(CORE)
    assert ws.snapshot() is ws.snapshot()
    shutil.copyfile(empty_path, path)
    with pytest.raises(EaeditError):
        ws.snapshot().find(CORE)


def test_session_lifecycle_and_working_file(qea_copy, nafv4_path, tmp_path):
    path, config = _make(qea_copy, nafv4_path, tmp_path)
    ws = Workspace(config)
    ws.open_session()
    _create(ws, "Thing1")
    assert len(yaml.safe_load(ws.working_file.read_text())["ops"]) == 1
    assert ws.undo() == "create_element"
    assert len(yaml.safe_load(ws.working_file.read_text())["ops"]) == 0
    _create(ws, "Thing2")
    with pytest.raises(EaeditError, match="discard"):
        ws.open_session()
    ws.commit()
    assert not ws.working_file.exists() and ws.session is None
    assert Workspace(config).snapshot().find(f"{MSG}::Thing2")
    assert load_file(path)  # the file still loads


def test_stale_session_refuses_commit(qea_copy, nafv4_path, tmp_path):
    path, config = _make(qea_copy, nafv4_path, tmp_path)
    other = qea_copy(nafv4_path, "other.qea")
    ws = Workspace(config)
    ws.open_session()
    _create(ws, "Thing1")
    assert not ws.stale()
    changed = Workspace(Config(other, focus=[CORE], out_dir=tmp_path / "o2"))
    changed.open_session()
    changed.run("create_element", {"package": MSG, "name": "Other"})
    changed.commit()
    shutil.copyfile(other, path)
    assert ws.stale()
    with pytest.raises(EaeditError, match="discard"):
        ws.commit()
    assert ws.snapshot().find(f"{MSG}::Other")


def test_resume_replays_and_stops_at_failing_op(qea_copy, nafv4_path, tmp_path):
    _, config = _make(qea_copy, nafv4_path, tmp_path)
    ws = Workspace(config)
    ws.open_session()
    for n in ("A", "B", "C"):
        _create(ws, n)
    ws2 = Workspace(config)
    data = yaml.safe_load(ws2.working_file.read_text())
    data["ops"][1]["args"]["package"] = "Model::core::nope"
    ws2.working_file.write_text(yaml.safe_dump(data))
    result = ws2.open_session(resume=True)
    assert "resumed 1 of 3" in result.message and "op 2" in result.message
    assert (result.resumed, result.total) == (1, 3)
    assert len(ws2.session.log) == 1
    _create(ws2, "D")
    assert len(ws2.session.log) == 2
    assert len(yaml.safe_load(ws2.working_file.read_text())["ops"]) == 2


def test_open_without_resume_refuses_saved_session(qea_copy, nafv4_path, tmp_path):
    _, config = _make(qea_copy, nafv4_path, tmp_path)
    ws = Workspace(config)
    ws.open_session()
    _create(ws, "A")
    again = Workspace(config)  # a restart: the working file holds an operation
    with pytest.raises(EaeditError, match="resume=True"):
        again.open_session()
    assert again.session is None and len(yaml.safe_load(again.working_file.read_text())["ops"]) == 1
    again.discard()
    assert not again.working_file.exists()
    again.open_session()


def test_corrupt_working_file_leaves_no_session(qea_copy, nafv4_path, tmp_path):
    _, config = _make(qea_copy, nafv4_path, tmp_path)
    config.out_dir.mkdir()
    (config.out_dir / "working.yaml").write_text("not: [an eaedit file")
    ws = Workspace(config)
    with pytest.raises(EaeditError):
        ws.open_session(resume=True)
    assert ws.session is None
