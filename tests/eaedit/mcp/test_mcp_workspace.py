import re
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
    original = ws2.working_file.read_text()
    result = ws2.open_session(resume=True)
    assert "resumed 1 of 3" in result.message and "op 2" in result.message
    assert re.search(
        r"op 2 create_element\(guid='\{[0-9A-Fa-f-]+\}', name='B', package='Model::core::nope'\) failed", result.message
    )
    assert "1 later operation" in result.message
    rejected = config.out_dir / "working.rejected.yaml"
    assert str(rejected) in result.message
    assert rejected.read_text() == original  # the full log, failing op and its tail included
    assert (result.resumed, result.total) == (1, 3)
    assert len(ws2.session.log) == 1
    _create(ws2, "D")
    assert len(ws2.session.log) == 2
    assert len(yaml.safe_load(ws2.working_file.read_text())["ops"]) == 2
    assert len(yaml.safe_load(rejected.read_text())["ops"]) == 3


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


def test_resume_on_stale_session_rebases_onto_the_new_file(qea_copy, nafv4_path, tmp_path):
    path, config = _make(qea_copy, nafv4_path, tmp_path)
    other = qea_copy(nafv4_path, "other.qea")
    ws = Workspace(config)
    ws.open_session()
    _create(ws, "Mine")
    changed = Workspace(Config(other, focus=[CORE], out_dir=tmp_path / "o2"))
    changed.open_session()
    changed.run("create_element", {"package": MSG, "name": "Theirs"})
    changed.commit()
    shutil.copyfile(other, path)
    with pytest.raises(EaeditError, match=r"open_session\(resume=True\) replays your edits onto it, or discard\(\)"):
        ws.commit()
    with pytest.raises(EaeditError, match="already open"):
        ws.open_session()  # without resume an open session still refuses
    result = ws.open_session(resume=True)
    assert (result.resumed, result.total) == (1, 1)
    assert not ws.stale() and ws.working_file.is_file()
    ws.commit()
    snapshot = ws.snapshot()
    assert snapshot.find(f"{MSG}::Mine") and snapshot.find(f"{MSG}::Theirs")


def test_focus_and_policy_survive_restart_and_rebase(qea_copy, nafv4_path, tmp_path):
    path, config = _make(qea_copy, nafv4_path, tmp_path)
    other = qea_copy(nafv4_path, "other.qea")
    ws = Workspace(config)
    ws.open_session(focus=[MSG], policy="advisory")
    _create(ws, "Mine")
    saved = yaml.safe_load(ws.working_file.read_text())
    assert saved["policy"] == "advisory" and len(saved["focus"]) == 1

    def focus(w):
        return [w.session.working.resolve(r).values["attr_name"] for r in w.session.scope.focus]

    restarted = Workspace(config)  # the config's focus is Model::core, its policy "connected"
    restarted.open_session(resume=True)
    assert focus(restarted) == ["message"] and restarted.session.scope.policy == "advisory"
    changed = Workspace(Config(other, focus=[CORE], out_dir=tmp_path / "o2"))
    changed.open_session()
    changed.run("create_element", {"package": MSG, "name": "Theirs"})
    changed.commit()
    shutil.copyfile(other, path)
    assert restarted.stale()
    restarted.open_session(resume=True)  # rebase
    assert focus(restarted) == ["message"] and restarted.session.scope.policy == "advisory"
    restarted._close(keep_working_file=True)
    restarted.open_session(focus=[CORE], policy="package", resume=True)  # new ones win
    assert focus(restarted) == ["core"] and restarted.session.scope.policy == "package"
    assert yaml.safe_load(restarted.working_file.read_text())["policy"] == "package"


def test_read_only_refuses_editing(qea_copy, nafv4_path, tmp_path):
    path = qea_copy(nafv4_path)
    ws = Workspace(Config(path, out_dir=tmp_path / "out", read_only=True))
    assert ws.snapshot().find(CORE)
    for call in (ws.open_session, ws.require_session, ws.discard, ws.commit, lambda: _create(ws, "X")):
        with pytest.raises(EaeditError, match="read-only"):
            call()
    assert not (tmp_path / "out").exists()


def test_read_only_discard_keeps_a_saved_working_file(qea_copy, nafv4_path, tmp_path):
    path, config = _make(qea_copy, nafv4_path, tmp_path)
    ws = Workspace(config)
    ws.open_session()
    _create(ws, "Kept")
    ws.close()
    ro = Workspace(Config(path, out_dir=config.out_dir, read_only=True))
    with pytest.raises(EaeditError, match="read-only"):
        ro.discard()
    assert ro.working_file.is_file()


def test_close_keeps_working_file_and_resume_restores(qea_copy, nafv4_path, tmp_path):
    path, config = _make(qea_copy, nafv4_path, tmp_path)
    ws = Workspace(config)
    ws.snapshot()
    ws.open_session()
    _create(ws, "Thing1")
    ws.close()
    assert ws.session is None and ws.working_file.is_file()
    again = Workspace(config)
    assert again.open_session(resume=True).resumed == 1
